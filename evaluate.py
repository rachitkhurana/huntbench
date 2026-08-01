#!/usr/bin/env python3
"""Deep evaluation of a job: deterministic baseline + an optional claude pass.

The baseline (jobsdb.evaluate_job) scores role / seniority / comp / location / stack
and raises risk flags, offline and zero-token. `--ai` adds a nuanced read + a real
scam/ghost verdict via the `claude` CLI (reusing tailor's plumbing), merged onto the
record. A hint, not gospel.

  ./jobsdb.py evaluate --id <id>          # deterministic re-eval of one job
  ./jobsdb.py evaluate --id <id> --ai     # claude deep read + merge
  ./jobsdb.py evaluate --all              # backfill baseline for jobs lacking one
  ./jobsdb.py evaluate --all --force      # recompute every job
"""

import jobsdb

AXES = ["role", "seniority", "comp", "location", "stack"]

_RULES = """You are evaluating whether ONE job posting fits a specific candidate, and \
whether the posting looks legitimate. Read the candidate profile and the job below.

Return ONLY a single JSON object (no prose, no markdown fences), exactly this shape:
{"overall": <1-5>,
 "axes": {"role": <1-5>, "seniority": <1-5>, "comp": <1-5 or null>,
          "location": <1-5>, "stack": <1-5 or null>},
 "flags": [<short kebab-case risk slugs; [] if none>],
 "verdict": "<2-3 sentences: is it worth pursuing, plus any scam/ghost red flags>"}

Scoring: 5 = excellent fit, 3 = neutral, 1 = poor. Use null for comp/stack only when \
the posting gives no signal. For flags, judge scam/ghost-job likelihood from vagueness, \
unrealistic or missing comp, generic boilerplate, pressure tactics, or a mismatch between \
title seniority and stated requirements. Common slugs: "ghost-job", "vague-jd", \
"comp-lowball", "comp-outlier", "commission-only", "title-mismatch", "scam-signals"."""


def build_eval_prompt(rec, profile):
    enr = rec.get("enrichment") or {}
    tr = (profile or {}).get("target_roles") or {}
    loc = (profile or {}).get("location") or {}
    levels = ", ".join(str(a.get("level", "")) for a in (tr.get("archetypes") or [])
                       if isinstance(a, dict))
    lines = [
        "CANDIDATE",
        "Target roles: %s" % ", ".join(tr.get("primary") or []),
        "Seniority: %s" % (levels or "senior / staff / lead"),
        "Visa & location: %s / %s" % (loc.get("visa_status", "n/a"),
                                      loc.get("onsite_availability", "n/a")),
        "",
        "TARGET JOB",
        "Title: %s" % rec.get("title"),
        "Company: %s" % rec.get("company"),
        "Location: %s (work_mode: %s, region: %s)" % (
            rec.get("location"), rec.get("work_mode"), rec.get("region_bucket")),
        "Experience level: %s" % rec.get("experience_tag"),
        "Salary: %s" % (rec.get("salary") or "not stated"),
        "Skills: %s" % ", ".join(enr.get("skills") or []),
        "",
        "Job description:",
        (enr.get("description") or "(no description captured)"),
    ]
    return "%s\n\n%s" % (_RULES, "\n".join(lines))


def _clamp(v):
    try:
        return max(1, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


def _ai_eval(rec, profile, model=None):
    """Ask claude for a nuanced evaluation. Returns (data, None) or (None, error)."""
    import tailor
    out, err = tailor._call_claude(build_eval_prompt(rec, profile), model)
    if err:
        return None, err
    data = tailor._extract_json(out)
    if not data:
        return None, "claude did not return valid JSON"
    return data, None


def _merge_ai(base, data):
    """Merge claude's evaluation onto the deterministic baseline."""
    ev = dict(base)
    axes = dict(base.get("axes") or {})
    for k in AXES:
        if k in (data.get("axes") or {}):
            axes[k] = _clamp(data["axes"][k])   # may be None (unknown)
    ev["axes"] = axes
    if data.get("overall") is not None:
        ev["overall"] = _clamp(data["overall"]) or base.get("overall")
    seen = []                                    # union heuristic + AI flags, keep order
    for f in (base.get("flags") or []) + [str(x).strip().lower()
                                          for x in (data.get("flags") or []) if str(x).strip()]:
        if f not in seen:
            seen.append(f)
    ev["flags"] = seen
    ev["verdict"] = (data.get("verdict") or "").strip()
    ev["method"] = "ai"
    ev["evaluated_at"] = jobsdb.TODAY
    return ev


def run(args):
    db = jobsdb.load_db()
    idx = jobsdb.index_by_id(db)
    profile = jobsdb._profile()

    if getattr(args, "id", None):
        rec = idx.get(args.id)
        if not rec:
            print("evaluate: id %s not found" % args.id)
            return 1
        targets = [rec]
    elif getattr(args, "all", False):
        targets = [r for r in db if getattr(args, "force", False) or not r.get("evaluation")]
        if not targets:
            print("evaluate: nothing to do (all jobs already evaluated; use --force to redo)")
            return 0
    else:
        print("evaluate: pass --id <id> or --all")
        return 2

    use_ai = getattr(args, "ai", False)
    n_ai = n_h = 0
    for rec in targets:
        base = jobsdb.evaluate_job(rec, profile)
        if use_ai:
            data, err = _ai_eval(rec, profile, getattr(args, "model", None))
            if err:
                print("evaluate: %s / %s - AI unavailable: %s; kept heuristic"
                      % (rec.get("company"), rec.get("id"), err))
                rec["evaluation"] = base
                n_h += 1
            else:
                rec["evaluation"] = _merge_ai(base, data)
                n_ai += 1
                v = rec["evaluation"]
                print("evaluate: %s / %s -> overall %s%s"
                      % (rec.get("company"), rec.get("title"), v.get("overall"),
                         (" [flags: %s]" % ", ".join(v["flags"])) if v.get("flags") else ""))
        else:
            rec["evaluation"] = base
            n_h += 1
        rec["updated"] = jobsdb.TODAY

    jobsdb.save_db(db)
    print("evaluate: %d job(s) - %d AI, %d heuristic" % (len(targets), n_ai, n_h))
    return 0
