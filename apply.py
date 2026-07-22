#!/usr/bin/env python3
"""apply - assemble an "apply packet" so the browser step can fill a job's application form.

Pure offline prep (NO browser, NO submit). It:
  1. ensures a tailored CV PDF exists for the job (AI-tailor by default, or --no-tailor for master),
  2. maps the shared profile.yml to the standard ATS form fields (name/email/phone/links/work-auth/...),
  3. drafts first-person answers to the common application questions via headless `claude`
     (reusing tailor's plumbing), and
  4. writes apply-packet.json (machine-readable, consumed by the browser-drive step) plus
     apply-packet.md (human copy-paste fallback) into the job's output folder.

    ./jobsdb.py apply --id greenhouse:5778418004
    ./jobsdb.py apply --id 4425858770 --no-tailor --slug pikky-fe

The actual form-filling is done by Claude in chat via the Claude-in-Chrome browser tools, which
drive your real logged-in Chrome - see APPLY-RUNBOOK.md. This command never opens a browser and
never submits anything; the browser step always STOPS before submit for your review.
"""

import json
import os
import re
import sys
import types
from urllib.parse import urlparse

import configlib
import cvgen
import jobsdb
import tailor

# EEO / diversity / identity questions ATS forms often require but the profile can't answer.
# The browser step must ASK the user for these - never invent a legal/diversity attestation.
GAPS = [
    {"field": "gender", "note": "EEO/diversity - not in profile; ask the user or 'Decline to self-identify'"},
    {"field": "race_ethnicity", "note": "EEO (US) - ask the user or 'Decline to self-identify'"},
    {"field": "hispanic_latino", "note": "EEO (US) - ask the user or 'Decline to self-identify'"},
    {"field": "veteran_status", "note": "EEO (US) - ask the user or 'I am not a protected veteran'"},
    {"field": "disability_status", "note": "EEO (US) - ask the user or 'I do not wish to answer'"},
    {"field": "pronouns", "note": "not in profile - ask the user only if the form requires it"},
    {"field": "requires_sponsorship", "note": "answer from work_authorization: yes for US/EU/AU, no for UAE"},
]

_QUESTION_BANK = [
    "Why do you want to work at {company}?",
    "Why are you interested in this {title} role?",
    "What relevant experience makes you a strong fit for this role?",
    "How did you hear about this role?",
    "Is there anything else you'd like us to know?",
]

_ANSWER_RULES = """You are drafting the candidate's answers to a job application form. Output ONLY
a single JSON object mapping each question (verbatim, as given) to a 2-4 sentence first-person answer.

HARD RULES:
- First person as the candidate ("I ...").
- Use ONLY real facts from the profile and JD below. NEVER invent employers, metrics, tools, or dates.
- Tone: confident and specific - proof, not adjectives; the "I'm choosing you" posture; 2-4 sentences each.
- Do NOT name anything the candidate marked private/STEALTH; refer to such work neutrally.
- Do NOT sign off, and NEVER add "via Claude" or any AI attribution - these are the candidate's own words.
- For "How did you hear about this role?" give a natural, true-sounding answer (found via the company's
  careers page / a job board / following the company's work).
- If "THE CANDIDATE'S OWN NOTES FOR THIS ROLE" are given, treat them as HIGH-PRIORITY steering on what to
  emphasize and how to angle the answers - but still only use real facts (never invent to satisfy a note).
- Output valid JSON only. No commentary, no markdown fences."""


def _provider_from_url(url):
    host = urlparse(url or "").netloc.lower()
    for key, needle in (("greenhouse", "greenhouse"), ("ashby", "ashbyhq"), ("lever", "lever.co"),
                        ("workable", "workable"), ("recruitee", "recruitee"),
                        ("smartrecruiters", "smartrecruiters"), ("linkedin", "linkedin.")):
        if needle in host:
            return key
    return "other"


def _split_name(full):
    parts = (full or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _https(u):
    u = (u or "").strip()
    if not u:
        return ""
    return u if u.startswith(("http://", "https://")) else "https://" + u


def build_fields(profile, rec, region):
    cand = profile.get("candidate") or {}
    loc = profile.get("location") or {}
    comp = profile.get("compensation") or {}
    first, last = _split_name(cand.get("full_name"))
    phones = cand.get("phone") or []
    band = configlib.comp_band(profile, region) or {}
    return {
        "first_name": first,
        "last_name": last,
        "full_name": cand.get("full_name") or "",
        "email": cand.get("email") or "",
        "phone": phones[0] if phones else "",
        "location": cand.get("location") or "",
        "city": loc.get("city") or "",
        "country": loc.get("country") or "",
        "linkedin": _https(cand.get("linkedin")),
        "github": _https(cand.get("github")),
        "portfolio": cand.get("portfolio_url") or "",
        "website": cand.get("portfolio_url") or "",
        "twitter": cand.get("twitter") or "",
        "work_authorization": loc.get("visa_status") or "",
        "relocation": comp.get("location_flexibility") or "",
        "salary_expectation": band.get("target_range") or "",
        "notice_period": "Immediate (currently on a career break)",
        "years_experience": "~7",
        "current_title": "Frontend Lead",
        "current_company": "Ultrahuman",
    }


def _extra_questions(desc, cap=3):
    """Explicit application questions embedded in the JD (lines ending in '?')."""
    seen, out = set(), []
    for line in (desc or "").splitlines():
        line = line.strip().lstrip("-*0123456789. ").strip()
        if line.endswith("?") and 8 <= len(line) <= 180:
            k = line.lower()
            if k not in seen:
                seen.add(k)
                out.append(line)
        if len(out) >= cap:
            break
    return out


def draft_answers(rec, profile, model=None):
    """Return (answers_dict, error_or_None). Empty dict + error if claude can't run."""
    company = rec.get("company") or "the company"
    title = rec.get("title") or "this role"
    enr = rec.get("enrichment") or {}
    jd = enr.get("description") or ""
    notes = (rec.get("notes") or "").strip()
    questions = [q.format(company=company, title=title) for q in _QUESTION_BANK]
    questions += _extra_questions(jd or notes)
    narrative = profile.get("narrative") or {}
    prof_blob = json.dumps({
        "headline": narrative.get("headline"),
        "exit_story": narrative.get("exit_story"),
        "superpowers": narrative.get("superpowers"),
        "proof_points": narrative.get("proof_points"),
        "target_roles": (profile.get("target_roles") or {}).get("primary"),
    }, ensure_ascii=False, indent=2)
    sections = [
        _ANSWER_RULES,
        "TARGET JOB\nCompany: %s\nTitle: %s\nLocation: %s"
        % (company, title, rec.get("location") or ""),
        "JOB DESCRIPTION (may be partial or absent):\n" + (jd[:4000] if jd else "(none captured)"),
    ]
    if notes:
        sections.append("THE CANDIDATE'S OWN NOTES FOR THIS ROLE (steering - honor these):\n" + notes)
    sections.append("THE CANDIDATE'S PROFILE (real facts only):\n" + prof_blob)
    sections.append("QUESTIONS TO ANSWER (use each verbatim as a JSON key):\n"
                    + "\n".join("- " + q for q in questions))
    prompt = "\n\n".join(sections)
    out, err = tailor._call_claude(prompt, model)
    if err:
        return {}, err
    obj = tailor._extract_json(out)
    if not isinstance(obj, dict) or not obj:
        return {}, "claude did not return a valid JSON answers object"
    return obj, None


def ensure_cv(rec, args, outdir):
    """Return (resume_path, note). Generates the CV if the role-named PDF isn't present yet."""
    names = cvgen.artifact_names(rec)
    pdf = os.path.join(outdir, names["cv_pdf"])
    html = os.path.join(outdir, names["cv_html"])
    if os.path.exists(pdf):
        return pdf, "reused existing cv.pdf"
    ns = types.SimpleNamespace(
        id=args.id, slug=getattr(args, "slug", None), region=getattr(args, "region", None),
        overrides=None, no_pdf=getattr(args, "no_pdf", False), no_letter=False,
        model=getattr(args, "model", None), no_generate=False)
    if getattr(args, "no_tailor", False):
        cvgen.run(ns)
    else:
        rc = tailor.run(ns)          # AI-tailor + render
        if rc != 0:                  # claude missing/timeout/etc -> master CV fallback
            print("apply: AI-tailor unavailable; falling back to master CV")
            cvgen.run(ns)
    if os.path.exists(pdf):
        return pdf, "generated"
    if os.path.exists(html):
        return html, "HTML only (Chrome missing/slow - no PDF); print cv.html manually"
    return None, "no CV produced"


def _scrub(obj):
    """Belt-and-braces: strip any leftover STEALTH marker from user-facing CONTENT (answers/
    fields), so a private line the model echoed doesn't reach a form. Paths are never scrubbed."""
    raw = json.dumps(obj, ensure_ascii=False)
    if re.search(r"\[stealth\]", raw, re.I):
        obj = json.loads(re.sub(r"(?i)\s*\[stealth\]", "", raw))
    return obj


def _abs_if(path):
    return os.path.abspath(path) if os.path.exists(path) else None


def render_md(p):
    L = ["# Apply packet - %s / %s" % (p.get("company"), p.get("title")), ""]
    L += ["- **URL:** %s" % (p.get("url") or ""),
          "- **Provider:** %s" % p.get("provider"),
          "- **Region:** %s" % p.get("region"),
          "- **Resume:** %s" % (p.get("resume_pdf") or p.get("resume_html") or "(none)"),
          "- **Cover letter:** %s" % (p.get("cover_letter_txt") or "(none)"),
          "- **Generated:** %s" % p.get("generated"), ""]
    L += ["## Form fields", ""]
    for k, v in (p.get("fields") or {}).items():
        L.append("- **%s:** %s" % (k, v))
    L += ["", "## Drafted answers", ""]
    ca = p.get("custom_answers") or {}
    if ca:
        for q, a in ca.items():
            L += ["**%s**" % q, "", a, ""]
    else:
        L += ["_(none drafted - run on a machine with `claude`, or answer in chat)_", ""]
    L += ["## Needs your input (do NOT auto-fill)", ""]
    for g in (p.get("gaps") or []):
        L.append("- **%s** - %s" % (g["field"], g["note"]))
    L += ["", "---", "Next: in chat, say **apply to %s**. Claude fills the form in your logged-in "
          "Chrome and STOPS before submit for your review. See APPLY-RUNBOOK.md." % p.get("id")]
    return "\n".join(L) + "\n"


def run(args):
    rec = jobsdb.index_by_id(jobsdb.load_db()).get(args.id)
    if not rec:
        print("apply: id %s not found" % args.id)
        return 1
    profile, _ = configlib.load_profile()
    if not profile:
        print("apply: no profile.yml found")
        return 1
    region = getattr(args, "region", None) or rec.get("region_bucket") or "other"
    outdir = cvgen._outdir(rec, getattr(args, "slug", None))
    _names = cvgen.artifact_names(rec)
    os.makedirs(outdir, exist_ok=True)

    print("apply: preparing packet for %s / %s" % (rec.get("company"), rec.get("title")))
    resume, note = ensure_cv(rec, args, outdir)
    print("apply: resume -> %s (%s)" % (resume or "(none)", note))

    # scrub CONTENT only (answers/fields), never the file paths below
    fields = _scrub(build_fields(profile, rec, region))
    answers, aerr = draft_answers(rec, profile, getattr(args, "model", None))
    if aerr:
        print("apply: custom answers skipped (%s) - draft them in chat or by hand" % aerr)
    else:
        answers = _scrub(answers)
        print("apply: drafted %d answers" % len(answers))

    # leak check on CONTENT only (paths are never scrubbed)
    content = json.dumps({"fields": fields, "answers": answers}, ensure_ascii=False)
    if re.search(r"\[stealth\]", content, re.I):
        print("apply: ABORT - a STEALTH marker leaked into packet content.")
        return 1

    packet = {
        "id": rec.get("id"), "company": rec.get("company"), "title": rec.get("title"),
        "location": rec.get("location"), "url": rec.get("url"),
        "provider": _provider_from_url(rec.get("url")), "region": region,
        "resume_pdf": os.path.abspath(resume) if (resume and resume.endswith(".pdf")) else None,
        "resume_html": _abs_if(os.path.join(outdir, _names["cv_html"])),
        "resume_txt": _abs_if(os.path.join(outdir, _names["cv_txt"])),
        "cover_letter_pdf": _abs_if(os.path.join(outdir, _names["cl_pdf"])),
        "cover_letter_txt": _abs_if(os.path.join(outdir, _names["cl_txt"])),
        "fields": fields, "custom_answers": answers, "gaps": GAPS,
        "generated": jobsdb.TODAY,
    }

    jpath = os.path.join(outdir, "apply-packet.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, ensure_ascii=False)
    mpath = os.path.join(outdir, "apply-packet.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(render_md(packet))

    print("apply: wrote %s" % jpath)
    print("apply: wrote %s" % mpath)
    print()
    print("Next: in chat, tell Claude  ->  apply to %s" % rec.get("id"))
    print("Claude opens the form in your logged-in Chrome, fills it from this packet, uploads the")
    print("CV, and STOPS before submit for your review. (See APPLY-RUNBOOK.md.)")
    return 0
