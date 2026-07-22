#!/usr/bin/env python3
"""cvgen - tailored CV + cover letter for a job record.

A clean monochrome, ATS-safe resume design (system sans, no embedded fonts): bold name, grey
subtitle, letter-spaced uppercase section headers with hairline rules, right-aligned dates,
bulleted achievements, an Independent Work section, a two-column Skills grid, and Education +
Honours side-by-side.

Content comes from your master CV at config/master-cv.md (see config/master-cv.example.md).
Each CV is rendered to PDF (headless Chrome, if found) AND a plain-text .txt; the cover letter
likewise gets PDF + copy-paste .txt. Output lands in output/<company>-<id>/.

    ./jobsdb.py cv --id greenhouse:5778418004
    ./jobsdb.py cv --id 4425858770 --no-pdf

STEALTH: any line in master-cv.md that ends with the marker `[STEALTH]` (or is inside a
`<!--STEALTH ... -->` block) is stripped from every output - use it for private/unnamed work.
"""

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

import configlib
import jobsdb

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = MODULE_DIR
MASTER_CV = os.path.join(MODULE_DIR, "config", "master-cv.md")
if not os.path.exists(MASTER_CV):
    _ex = os.path.join(MODULE_DIR, "config", "master-cv.example.md")
    if os.path.exists(_ex):
        MASTER_CV = _ex


def _find_chrome():
    """Locate a Chrome/Chromium binary cross-platform; $CHROME overrides. None if not found."""
    env = os.environ.get("CHROME")
    if env and os.path.exists(env):
        return env
    cands = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    from shutil import which
    for n in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        p = which(n)
        if p:
            return p
    return None


CHROME = _find_chrome() or ""

_TECH_VOCAB = ["react", "next.js", "nextjs", "typescript", "javascript", "gsap", "three.js",
               "threejs", "webgl", "r3f", "node.js", "node", "graphql", "tailwind", "redux",
               "zustand", "react query", "design system", "design systems", "accessibility",
               "wcag", "performance", "animation", "motion", "canvas", "d3", "storybook",
               "vue", "svelte", "css", "html", "react native", "ssr", "micro-frontends",
               "shopify", "stripe", "figma", "postgres", "docker"]

_PAGESIZE = {"us": "Letter"}  # A4 default


# ---- ATS text normalization --------------------------------------------------

def _ats(t):
    if not t:
        return t
    for a, b in [("—", "-"), ("–", "-"),
                 ("“", '"'), ("”", '"'), ("„", '"'), ("‟", '"'),
                 ("‘", "'"), ("’", "'"), ("‚", "'"), ("‛", "'"),
                 ("…", "..."), ("​", ""), ("‌", ""), ("‍", ""),
                 ("⁠", ""), ("﻿", ""), (" ", " ")]:
        t = t.replace(a, b)
    t = re.sub(r"\s*→\s*", " to ", t)
    t = re.sub(r"\s*←\s*", " from ", t)
    t = re.sub(r"\s*[↑↓]\s*", " ", t)
    t = re.sub(r"\s*·\s*", " | ", t)
    t = re.sub(r"\s*•\s*", " | ", t)
    t = t.replace("€", "EUR ").replace("£", "GBP ")
    return t


def _clean(s, html_ctx=True):
    """Strip markdown/wikilinks; bold -> <strong> (html) or plain; ATS-normalize."""
    s = s or ""
    if html_ctx:
        s = html.escape(s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", s)   # [[path|Label]] -> Label
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)             # [[Label]] -> Label
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)        # [text](url) -> text
    if html_ctx:
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    else:
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+)\*(?!\*)", r"\1", s)  # *italic* -> plain
    return _ats(s).strip()


# ---- master.md parser --------------------------------------------------------

def _sections(text):
    text = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.S)
    parts = re.split(r"^##\s+(.+)$", text, flags=re.M)
    sec = {"_preamble": parts[0]}
    for i in range(1, len(parts), 2):
        sec[parts[i].strip().lower()] = parts[i + 1] if i + 1 < len(parts) else ""
    return sec


def _get(sec, kw):
    for k, v in sec.items():
        if kw in k:
            return v
    return ""


def _bullets(body):
    return [b.strip() for b in re.findall(r"^\s*-\s+(.+)$", body, flags=re.M)]


def _parse_experience(body):
    jobs = []
    chunks = re.split(r"^###\s+(.+)$", body, flags=re.M)
    for i in range(1, len(chunks), 2):
        title, content = chunks[i].strip(), chunks[i + 1]
        company, _, role = title.partition("—")
        if not role:
            company, _, role = title.partition("-")
        period = location = descriptor = ""
        for ln in content.strip().splitlines():
            s = ln.strip()
            bm = re.match(r"\*\*(.+?)\*\*(.*)", s)
            if bm and not period:
                period = bm.group(1).strip()
                location = bm.group(2).strip().lstrip("·").strip()
                continue
            im = re.match(r"^\*([^*].*?)\*$", s)
            if im and not descriptor:
                descriptor = im.group(1).strip()
        jobs.append({"company": company.strip(), "role": role.strip(), "period": period,
                     "location": location, "descriptor": descriptor,
                     "bullets": _bullets(content)})
    return jobs


def _parse_projects(body):
    projs = []
    for ln in _bullets(body):
        if "STEALTH" in ln.upper():          # drop lines the user marked private
            continue
        name_m = re.search(r"\*\*(.+?)\*\*", ln)
        tech_m = re.search(r"\*\(([^)]+)\)\*", ln)
        name = _clean(name_m.group(1)) if name_m else ""
        tech = _clean(tech_m.group(1)) if tech_m else ""
        desc = ln
        if name_m:
            desc = desc.replace(name_m.group(0), "")
        if tech_m:
            desc = desc.replace(tech_m.group(0), "")
        desc = _clean(desc).strip(" -—|")
        projs.append({"name": name, "desc": desc, "tech": tech})
    return projs


def _parse_skills(body):
    cats = []
    for ln in body.strip().splitlines():
        m = re.match(r"\*\*(.+?):\*\*\s*(.+)", ln.strip())
        if m:
            cats.append({"cat": _clean(m.group(1)), "items": _clean(m.group(2))})
    return cats


def _parse_edu(s):
    tm = re.search(r"\*\*(.+?)\*\*", s)
    title = _clean(tm.group(1)) if tm else _clean(s)
    ym = re.search(r"\(?(\d{4}\s*[–-]\s*\d{4})\)?", s)
    year = _clean(ym.group(1)) if ym else ""
    rest = s
    if tm:
        rest = rest.replace(tm.group(0), "")
    if ym:
        rest = rest.replace(ym.group(0), "")
    return title, _clean(rest).strip(" -—|()"), year


def _subtitle(sec):
    m = re.search(r"\*\*(.+?)\*\*", sec.get("_preamble", ""))
    return _clean(m.group(1)) if m else "Frontend Lead"


def parse_master():
    if not os.path.exists(MASTER_CV):
        return {}
    sec = _sections(open(MASTER_CV, encoding="utf-8").read())
    summ = [p.strip() for p in _get(sec, "summary").strip().split("\n\n") if p.strip()]
    return {
        "subtitle": _subtitle(sec),
        "summary": summ[0] if summ else "",
        "experience": _parse_experience(_get(sec, "experience")),
        "projects": _parse_projects(_get(sec, "side project")),
        "skills": _parse_skills(_get(sec, "skills")),
        "education": [_parse_edu(i) for i in _bullets(_get(sec, "education"))],
        "honours": _bullets(_get(sec, "honour")),
    }


# ---- per-job tailoring overlay ----------------------------------------------
# A cv-overrides.json in the job's output/opportunity folder (or via --overrides) lets the
# agent deep-tailor a CV to a specific JD. Any present section overrides master wholesale.
# Schema (all optional): {subtitle, summary, experience[{company,role,period,location,
# descriptor,bullets[]}], projects[{name,desc,tech}], skills[{cat,items}],
# education[{title,org,year}], honours[]}.  Content may use markdown (**bold**); it is
# ATS-normalized and STEALTH-stripped like everything else.

def _load_overlay(outdir, path):
    for cand in [path, os.path.join(outdir, "cv-overrides.json")]:
        if cand and os.path.exists(cand):
            try:
                return json.load(open(cand, encoding="utf-8")), cand
            except (ValueError, OSError) as e:
                return {"_error": str(e)}, cand
    return {}, None


def _edu_from_ov(e):
    if isinstance(e, dict):
        return (e.get("title", ""), e.get("org", ""), e.get("year", ""))
    if isinstance(e, (list, tuple)):
        return tuple((list(e) + ["", "", ""])[:3])
    return (str(e), "", "")


def _merge_overlay(master, ov):
    m = dict(master)
    for k in ("subtitle", "summary"):
        if ov.get(k):
            m[k] = ov[k]
    if ov.get("experience"):
        m["experience"] = [{"company": j.get("company", ""), "role": j.get("role", ""),
                            "period": j.get("period", ""), "location": j.get("location", ""),
                            "descriptor": j.get("descriptor", ""),
                            "bullets": j.get("bullets", [])} for j in ov["experience"]]
    if ov.get("projects"):
        m["projects"] = [{"name": p.get("name", ""), "desc": p.get("desc", ""),
                         "tech": p.get("tech", "")} for p in ov["projects"]]
    if ov.get("skills"):
        m["skills"] = [{"cat": c.get("cat", ""), "items": c.get("items", "")}
                       for c in ov["skills"]]
    if ov.get("education"):
        m["education"] = [_edu_from_ov(e) for e in ov["education"]]
    if ov.get("honours"):
        m["honours"] = ov["honours"]
    return m


def jd_keywords(rec, limit=8):
    enr = rec.get("enrichment") or {}
    kws = []
    for s in (enr.get("skills") or []):
        if s.lower() not in [k.lower() for k in kws]:
            kws.append(s)
    hay = ((enr.get("description") or "") + " " + " ".join(rec.get("tags") or [])).lower()
    for v in _TECH_VOCAB:
        if v in hay and v not in [k.lower() for k in kws]:
            kws.append(v if "." in v or v == "r3f" else v.title())
    return (kws or ["React", "Next.js", "TypeScript"])[:limit]


# ---- CSS (clean monochrome, hairline rules, teal links) ----------------------

_CV_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
body{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;font-size:10.5px;line-height:1.5;color:#222;}
a{color:#2b7a78;text-decoration:underline;}
.name{font-size:30px;font-weight:700;color:#111;letter-spacing:-0.4px;line-height:1.05;}
.subtitle{font-size:12px;color:#555;margin-top:3px;}
.contact{font-size:9.5px;color:#666;margin-top:9px;line-height:1.65;}
.contact a{color:#2b7a78;}
.section{margin-top:15px;}
.sec-head{font-size:9.5px;font-weight:700;letter-spacing:2px;color:#111;text-transform:uppercase;border-bottom:1px solid #dddddd;padding-bottom:5px;margin-bottom:9px;}
.job{margin-bottom:11px;break-inside:avoid;page-break-inside:avoid;}
.job-top{display:flex;justify-content:space-between;align-items:baseline;gap:14px;}
.job-title{font-size:11.5px;font-weight:700;color:#111;}
.job-date{font-size:9.5px;color:#777;white-space:nowrap;}
.job-sub{font-size:9.5px;color:#888;margin:1px 0 4px;}
.job ul{margin:0;padding-left:15px;}
.job li{font-size:10.2px;line-height:1.5;margin-bottom:3px;color:#2a2a2a;}
.job li strong{font-weight:700;color:#111;}
.intro{font-size:10px;color:#888;font-style:italic;margin-bottom:7px;}
.prod{margin-bottom:6px;font-size:10.2px;color:#2a2a2a;break-inside:avoid;}
.prod strong{color:#111;}
.tech{color:#999;}
table.skills{width:100%;border-collapse:collapse;}
table.skills td{vertical-align:top;padding:2.5px 0;font-size:10.2px;}
td.cat{font-weight:700;color:#111;width:172px;padding-right:14px;}
td.val{color:#333;}
.cols{display:flex;gap:30px;margin-top:15px;}
.cols>div{flex:1;min-width:0;}
.cols .section{margin-top:0;}
.edu{margin-bottom:6px;}
.edu-year{float:right;color:#777;font-size:9.5px;font-weight:400;}
.edu-title{font-weight:700;font-size:10.5px;color:#111;}
.edu-org{color:#777;font-size:9.5px;}
.hon{font-size:10px;color:#2a2a2a;margin-bottom:4px;line-height:1.45;}
"""


# ---- builders ----------------------------------------------------------------

def _contact(cand):
    li = cand.get("linkedin") or ""
    li_url = li if li.startswith("http") else ("https://" + li)
    pf = cand.get("portfolio_url") or ""
    email = cand.get("email") or ""
    phones = cand.get("phone") or []
    tags = ["(UAE)", "(IN)"]
    bits = [_clean(cand.get("location")), "open to UAE / Europe"]
    if pf:
        bits.append('<a href="%s">%s</a>' % (html.escape(pf), _clean(pf.replace("https://", ""))))
    if li:
        bits.append('<a href="%s">%s</a>' % (html.escape(li_url), _clean(li)))
    if email:
        bits.append('<a href="mailto:%s">%s</a>' % (html.escape(email), _clean(email)))
    for i, ph in enumerate(phones):
        bits.append("%s %s" % (_clean(ph), tags[i] if i < len(tags) else ""))
    return " &nbsp;|&nbsp; ".join(b for b in bits if b)


def _exp_html(jobs):
    out = ""
    for j in jobs:
        sub = " | ".join(x for x in [_clean(j["location"]), _clean(j["descriptor"])] if x)
        bl = "".join("<li>%s</li>" % _clean(b) for b in j["bullets"])
        out += ('<div class="job"><div class="job-top">'
                '<span class="job-title">%s - %s</span><span class="job-date">%s</span></div>'
                '%s%s</div>') % (
            _clean(j["company"]), _clean(j["role"]), _clean(j["period"]),
            ('<div class="job-sub">%s</div>' % sub) if sub else "",
            ("<ul>%s</ul>" % bl) if bl else "")
    return out


def _proj_html(projs):
    out = ""
    for p in projs[:6]:
        out += ('<div class="prod"><strong>%s</strong> - %s%s</div>') % (
            p["name"], p["desc"],
            (' <span class="tech">(%s)</span>' % p["tech"]) if p["tech"] else "")
    return out


def _skills_html(cats):
    rows = "".join('<tr><td class="cat">%s</td><td class="val">%s</td></tr>'
                   % (c["cat"], c["items"]) for c in cats)
    return '<table class="skills">%s</table>' % rows


def _edu_html(items):
    out = ""
    for title, org, year in items:
        out += ('<div class="edu"><span class="edu-year">%s</span>'
                '<div class="edu-title">%s</div><div class="edu-org">%s</div></div>') % (
            year, title, org)
    return out


def build_cv(profile, rec, master, region):
    cand = profile.get("candidate") or {}
    pagesize = _PAGESIZE.get(region, "A4")
    edu = _edu_html(master.get("education") or [])
    hon = "".join('<div class="hon">%s</div>' % _clean(h) for h in (master.get("honours") or []))
    edu_hon = (
        '<div class="cols">'
        '<div><div class="section"><div class="sec-head">Education</div>%s</div></div>'
        '<div><div class="section"><div class="sec-head">Honours</div>%s</div></div>'
        '</div>' % (edu, hon)) if hon else (
        '<div class="section"><div class="sec-head">Education</div>%s</div>' % edu)
    body = (
        '<div class="name">%s</div><div class="subtitle">%s</div>'
        '<div class="contact">%s</div>'
        '<div class="section"><div class="sec-head">Summary</div>'
        '<div style="font-size:10.4px;line-height:1.6;color:#2a2a2a;">%s</div></div>'
        '<div class="section"><div class="sec-head">Experience</div>%s</div>'
        '<div class="section"><div class="sec-head">Independent Product Work</div>'
        '<div class="intro">Side products I build and ship solo, end-to-end - AI-aided.</div>%s</div>'
        '<div class="section"><div class="sec-head">Skills</div>%s</div>'
        '%s'
    ) % (
        _clean(cand.get("full_name")), _clean(master.get("subtitle")), _contact(cand),
        _clean(master.get("summary")),
        _exp_html(master.get("experience") or []),
        _proj_html(master.get("projects") or []),
        _skills_html(master.get("skills") or []),
        edu_hon,
    )
    head = ("<!doctype html><html><head><meta charset=\"utf-8\"><style>"
            + ("@page{size:%s;margin:15mm;}" % pagesize) + _CV_CSS
            + "</style></head><body>")
    return head + body + "</body></html>"


def build_cv_txt(profile, rec, master):
    cand = profile.get("candidate") or {}
    L = [_clean(cand.get("full_name"), False), _clean(master.get("subtitle"), False),
         " | ".join(x for x in [(cand.get("phone") or [""])[0], cand.get("email"),
                                cand.get("linkedin"), cand.get("portfolio_url"),
                                cand.get("location")] if x), "",
         "SUMMARY", _wrap(_clean(master.get("summary"), False)), "", "EXPERIENCE"]
    for j in master.get("experience") or []:
        L.append("%s - %s  (%s)" % (_clean(j["company"], False), _clean(j["role"], False),
                                    _clean(j["period"], False)))
        sub = " | ".join(x for x in [_clean(j["location"], False), _clean(j["descriptor"], False)] if x)
        if sub:
            L.append("  " + sub)
        for b in j["bullets"]:
            L.append(_wrap("- " + _clean(b, False), sub="  "))
        L.append("")
    L.append("INDEPENDENT PRODUCT WORK")
    for p in (master.get("projects") or [])[:6]:
        nm, de, te = (re.sub(r"<[^>]+>", "", p[k]) for k in ("name", "desc", "tech"))
        L.append(_wrap("- %s: %s%s" % (nm, de, (" (%s)" % te) if te else ""), sub="  "))
    L += ["", "SKILLS"]
    for c in master.get("skills") or []:
        L.append(_wrap("%s: %s" % (re.sub(r"<[^>]+>", "", c["cat"]),
                                   re.sub(r"<[^>]+>", "", c["items"])), sub="  "))
    L += ["", "EDUCATION"]
    for title, org, year in master.get("education") or []:
        L.append("%s (%s) - %s" % (re.sub(r"<[^>]+>", "", title), year, re.sub(r"<[^>]+>", "", org)))
    if master.get("honours"):
        L += ["", "HONOURS"] + [_clean(h, False) for h in master["honours"]]
    return "\n".join(L) + "\n"


def _wrap(text, width=96, sub=""):
    return "\n".join(textwrap.wrap(text, width, subsequent_indent=sub)) or text


# ---- cover letter ------------------------------------------------------------

def _cl_paragraphs(profile, rec):
    narr = profile.get("narrative") or {}
    comp = profile.get("compensation") or {}
    role = rec.get("title") or "the role"
    company = rec.get("company") or "your team"
    kws = jd_keywords(rec, 4)
    kw_phrase = ", ".join(kws[:3]) if kws else "modern frontend"
    paras = ["I'm writing about the %s role at %s. I own products end to end - scope, design, "
             "build, and measurement - and %s is exactly the kind of %s work I do best."
             % (role, company, company, kw_phrase)]
    for p in (narr.get("proof_points") or [])[:2]:
        m, n = (p.get("hero_metric") or ""), (p.get("name") or "")
        if m:
            paras.append(("%s: %s" % (n, m)) if n else m)
    if narr.get("exit_story"):
        paras.append(narr["exit_story"])
    paras.append("On logistics: %s I'd love to talk about how I can help %s."
                 % (comp.get("location_flexibility") or "", company))
    return [_ats(p) for p in paras if p]


def build_cover_letter(profile, rec, master):
    cand = profile.get("candidate") or {}
    body = "".join("<p>%s</p>" % _clean(p, True) for p in _cl_paragraphs(profile, rec))
    contact = " &nbsp;|&nbsp; ".join(_clean(x) for x in [
        (cand.get("phone") or [""])[0], cand.get("email"), cand.get("location"),
        cand.get("portfolio_url")] if x)
    css = ("*{margin:0;padding:0;box-sizing:border-box;}"
           "body{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;font-size:11.5px;line-height:1.65;color:#222;}"
           "a{color:#2b7a78;}"
           ".name{font-size:22px;font-weight:700;color:#111;letter-spacing:-0.3px;}"
           ".subtitle{font-size:11px;color:#555;margin-top:2px;}"
           ".rule{height:1px;background:#ddd;margin:8px 0 4px;}"
           ".contact{font-size:9.5px;color:#666;margin-bottom:18px;}"
           "p{margin:0 0 11px;}.sign{margin-top:14px;}")
    head = ("<!doctype html><html><head><meta charset=\"utf-8\"><style>"
            "@page{size:A4;margin:18mm;}" + css + "</style></head><body>")
    return (head + '<div class="name">%s</div><div class="subtitle">%s</div>'
            '<div class="rule"></div><div class="contact">%s</div>'
            '<p>Dear %s team,</p>%s<p class="sign">Warmly,<br>%s</p></body></html>'
            % (_clean(cand.get("full_name")), _clean(master.get("subtitle")), contact,
               _clean(rec.get("company") or "your"), body, _clean(cand.get("full_name"))))


def build_cover_letter_txt(profile, rec):
    cand = profile.get("candidate") or {}
    L = [_clean(cand.get("full_name"), False),
         " | ".join(x for x in [(cand.get("phone") or [""])[0], cand.get("email"),
                                cand.get("location"), cand.get("portfolio_url")] if x), "",
         "Dear %s team," % _clean(rec.get("company") or "your", False), ""]
    for p in _cl_paragraphs(profile, rec):
        L += [_wrap(re.sub(r"<[^>]+>", "", p)), ""]
    L += ["Warmly,", _clean(cand.get("full_name"), False)]
    return "\n".join(L) + "\n"


# ---- render / io -------------------------------------------------------------

def _assert_no_stealth(*blobs):
    b = " ".join(blobs).lower()
    if "[stealth]" in b or "stealth-marker" in b:
        sys.exit("cv: ABORT - a STEALTH marker leaked into output (a private line wasn't stripped).")


def _safe(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "x"


def _outdir(rec, slug):
    if slug:
        return os.path.join(MODULE_DIR, "output", _safe(slug))
    return os.path.join(MODULE_DIR, "output", _safe("%s-%s" % (rec.get("company"), rec.get("id"))))


_CAND_SLUG = None


def _candidate_slug():
    """The candidate's name as a filename slug (e.g. 'jane-doe'), cached."""
    global _CAND_SLUG
    if _CAND_SLUG is None:
        prof, _ = configlib.load_profile()
        name = ((prof or {}).get("candidate") or {}).get("full_name") or ""
        _CAND_SLUG = _safe(name) if name else "cv"
    return _CAND_SLUG


def artifact_names(rec):
    """Canonical, role-bearing output filenames for a job record. Single source of truth
    for every writer (cvgen) and reader (apply, webui) so they always agree.
    e.g. cv-jane-doe-acme-senior-frontend-engineer.pdf"""
    role = _safe("%s-%s" % (rec.get("company") or "", rec.get("title") or ""))[:70].strip("-")
    base = ("%s-%s" % (_candidate_slug(), role)).strip("-") or _candidate_slug()
    return {
        "cv_html": "cv-%s.html" % base, "cv_txt": "cv-%s.txt" % base, "cv_pdf": "cv-%s.pdf" % base,
        "cl_html": "cover-letter-%s.html" % base, "cl_txt": "cover-letter-%s.txt" % base,
        "cl_pdf": "cover-letter-%s.pdf" % base,
    }


def _to_pdf(html_path, pdf_path, timeout=30):
    if not os.path.exists(CHROME):
        return False, "Chrome not found (HTML written; print manually)"
    profdir = tempfile.mkdtemp()
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--disable-extensions", "--disable-background-networking",
           "--disable-crash-reporter", "--disable-crashpad", "--disable-sync",
           "--no-default-browser-check", "--no-pdf-header-footer",
           "--user-data-dir=" + profdir,
           "--print-to-pdf=" + pdf_path, "file://" + os.path.abspath(html_path)]
    slow = False
    try:
        subprocess.run(cmd, timeout=timeout, capture_output=True, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        slow = True
    except Exception as e:  # noqa
        return False, "chrome error: %s" % e
    if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            if f.read(4) == b"%PDF":
                return True, "OK" + (" (chrome slow to exit)" if slow else "")
    return False, "chrome timed out (%ds); HTML written, print manually" % timeout


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run(args):
    prof, _ = configlib.load_profile()
    if not prof:
        print("cv: no profile.yml found")
        return 1
    master = parse_master()
    if not master.get("experience"):
        print("cv: could not parse master CV at %s" % MASTER_CV)
        return 1
    rec = jobsdb.index_by_id(jobsdb.load_db()).get(args.id)
    if not rec:
        print("cv: id %s not found" % args.id)
        return 1
    region = args.region or rec.get("region_bucket") or "other"
    outdir = _outdir(rec, args.slug)
    os.makedirs(outdir, exist_ok=True)

    overlay, ov_path = _load_overlay(outdir, getattr(args, "overrides", None))
    if overlay.get("_error"):
        print("cv: overlay %s is invalid JSON (%s) - using master only"
              % (ov_path, overlay["_error"]))
    elif overlay:
        master = _merge_overlay(master, overlay)

    cv_html = build_cv(prof, rec, master, region)
    cv_txt = build_cv_txt(prof, rec, master)
    cl_html = "" if args.no_letter else build_cover_letter(prof, rec, master)
    cl_txt = "" if args.no_letter else build_cover_letter_txt(prof, rec)
    _assert_no_stealth(cv_html, cv_txt, cl_html, cl_txt)

    names = artifact_names(rec)
    written = []
    for key, content in [("cv_html", cv_html), ("cv_txt", cv_txt),
                         ("cl_html", cl_html), ("cl_txt", cl_txt)]:
        if content:
            _write(os.path.join(outdir, names[key]), content)
            written.append(names[key])

    print("cv: %s / %s  ->  %s" % (rec.get("company"), rec.get("title"), outdir))
    print("    wrote: %s" % ", ".join(written))
    if ov_path and not overlay.get("_error"):
        print("    tailored via overlay: %s (%s)"
              % (ov_path, ", ".join(k for k in overlay if not k.startswith("_"))))
    else:
        print("    (master content, untailored - drop a cv-overrides.json here to tailor)")
    if not args.no_pdf:
        pairs = [("cv_html", "cv_pdf")] + ([] if args.no_letter else [("cl_html", "cl_pdf")])
        for hk, pk in pairs:
            ok, msg = _to_pdf(os.path.join(outdir, names[hk]), os.path.join(outdir, names[pk]))
            print("    PDF %-40s %s" % (names[pk] + ":", msg))
    return 0
