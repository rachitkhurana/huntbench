#!/usr/bin/env python3
"""tailor - AI-tailor a CV to a specific job's JD via headless `claude -p`.

Sends the job's JD + the master CV to Claude with strict rules, gets back a cv-overrides.json
(the per-JD tailoring overlay that cvgen renders), writes it into the job's folder, then renders
the tailored CV. Pure orchestration; the intelligence is the `claude` CLI.

    ./jobsdb.py tailor --id greenhouse:5778418004 --slug vercel-fde
    ./jobsdb.py tailor --id 4425858770 --no-pdf

Requires the `claude` CLI on PATH (Claude Code). Fails gracefully otherwise.
"""

import json
import os
import subprocess
import sys
import types

import cvgen
import jobsdb

CLAUDE_TIMEOUT = 240

_RULES = """You are tailoring the candidate's CV to a specific job. Output ONLY a single JSON
object (no prose, no markdown fences) that overrides sections of his master CV to lead with what
THIS job's description asks for.

JSON schema (all keys optional; include the ones worth tailoring):
{
  "subtitle": "one line, e.g. 'Product Engineer | Frontend Lead | ~7 years'",
  "summary": "3-5 sentence summary reframed for this role; **bold** key facts/metrics",
  "experience": [ { "company": "...", "role": "...", "period": "...", "location": "...",
                    "descriptor": "...", "bullets": ["**bold** metric-led bullet", ...] } ],
  "skills": [ { "cat": "Category", "items": "A | B | C" } ],
  "projects": [ { "name": "...", "desc": "...", "tech": "..." } ]
}

HARD RULES:
- Use ONLY real facts from the master CV below. NEVER invent skills, tools, employers, or metrics.
  You may reorder, reframe, and emphasize what is already true.
- Reorder experience bullets, skills, and projects so the most JD-relevant come FIRST.
- Keep it to ~2 pages: <=5 bullets on the current role, <=1-2 on older roles; <=4 projects; <=6 skill rows.
- EXCLUDE any line marked with a `[STEALTH]` marker in the master CV - never mention it.
- Preserve real company names, dates, and locations from the master CV.
- If "THE CANDIDATE'S OWN NOTES FOR THIS ROLE" are given, treat them as HIGH-PRIORITY steering on what to
  emphasize, which angle to lead with, and which experience/skills to surface first - but still only
  use real facts from the master CV (never invent something to satisfy a note).
- Output valid JSON only. No commentary before or after."""


def _extract_json(text):
    """Return the first balanced {...} object parsed from Claude's output, or None."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def build_prompt(rec, master_text):
    enr = rec.get("enrichment") or {}
    notes = (rec.get("notes") or "").strip()
    jd = "\n".join([
        "TARGET JOB",
        "Title: %s" % rec.get("title"),
        "Company: %s" % rec.get("company"),
        "Location: %s" % rec.get("location"),
        "Tags: %s" % ", ".join(rec.get("tags") or []),
        "Salary: %s" % (rec.get("salary") or "n/a"),
        "",
        "Job description:",
        (enr.get("description") or "(no description captured)"),
    ])
    if notes:
        jd += ("\n\n=== THE CANDIDATE'S OWN NOTES FOR THIS ROLE (steering - honor these) ===\n" + notes)
    return "%s\n\n%s\n\n=== MASTER CV (source of truth - real facts only) ===\n%s" % (
        _RULES, jd, master_text)


def _call_claude(prompt, model=None):
    cmd = ["claude", "-p", "--dangerously-skip-permissions"]
    if model:
        cmd += ["--model", model]
    cmd += [prompt]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return None, "the `claude` CLI is not on PATH"
    except subprocess.TimeoutExpired:
        return None, "claude timed out after %ds" % CLAUDE_TIMEOUT
    if r.returncode != 0:
        return None, "claude exited %d: %s" % (r.returncode, (r.stderr or "").strip()[:200])
    return r.stdout, None


def run(args):
    db = jobsdb.load_db()
    rec = jobsdb.index_by_id(db).get(args.id)
    if not rec:
        print("tailor: id %s not found" % args.id)
        return 1
    if not os.path.exists(cvgen.MASTER_CV):
        print("tailor: master CV not found at %s" % cvgen.MASTER_CV)
        return 1
    master_text = open(cvgen.MASTER_CV, encoding="utf-8").read()

    print("tailor: asking claude to tailor CV for %s / %s ..." % (rec.get("company"), rec.get("title")))
    out, err = _call_claude(build_prompt(rec, master_text), getattr(args, "model", None))
    if err:
        print("tailor: %s (CV left untailored - use master, or tailor in chat)" % err)
        return 1
    overlay = _extract_json(out)
    if not overlay:
        print("tailor: claude did not return valid JSON overlay; leaving untailored")
        return 1

    outdir = cvgen._outdir(rec, args.slug)
    os.makedirs(outdir, exist_ok=True)
    ov_path = os.path.join(outdir, "cv-overrides.json")
    with open(ov_path, "w", encoding="utf-8") as f:
        json.dump(overlay, f, indent=2, ensure_ascii=False)
    print("tailor: wrote overlay (%s) -> %s"
          % (", ".join(k for k in overlay if not k.startswith("_")), ov_path))

    if getattr(args, "no_generate", False):
        print("tailor: --no-generate; run ./jobsdb.py cv --id %s to render" % args.id)
        return 0
    ns = types.SimpleNamespace(id=args.id, slug=args.slug,
                               region=getattr(args, "region", None),
                               overrides=ov_path,
                               no_pdf=getattr(args, "no_pdf", False),
                               no_letter=getattr(args, "no_letter", False))
    return cvgen.run(ns)
