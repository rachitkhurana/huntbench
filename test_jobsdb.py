#!/usr/bin/env python3
"""Self-check for the job DB merge/upsert rules: python3 test_jobsdb.py

Covers the bit with real consequences: a re-scan of a job already in the DB must
NOT reset the user's status (applied -> new) or wipe fit/notes, while still
refreshing objective posting fields. dedupe's "new wins" merge must stay intact.
"""

import jobsdb


def main():
    # --- a re-scan must not clobber user/workflow state -----------------------
    existing = jobsdb.normalize({
        "id": "co:1", "company": "Acme", "title": "Frontend Engineer",
        "location": "Remote", "status": "applied", "fit_score": 5,
        "notes": "loved the JD", "saved": True,
    })
    assert existing["status"] == "applied"
    assert existing["fit_score"] == 5
    assert existing["saved"] is True
    db = [existing]

    # scan re-detects the same posting; normalize stamps a fresh 'new' status
    scanned = jobsdb.normalize({
        "id": "co:1", "company": "Acme", "title": "Senior Frontend Engineer",
        "location": "Dubai, UAE",
    })
    assert scanned["status"] == "new", scanned["status"]

    added, updated = jobsdb.upsert(db, [scanned])
    assert (added, updated) == (0, 1), (added, updated)
    rec = db[0]
    # user/workflow state preserved
    assert rec["status"] == "applied", rec["status"]
    assert rec["fit_score"] == 5, rec["fit_score"]
    assert rec["notes"] == "loved the JD", rec["notes"]
    assert rec["saved"] is True, rec["saved"]          # ★ survives a re-scan
    # objective posting fields refreshed
    assert rec["title"] == "Senior Frontend Engineer", rec["title"]
    assert rec["location"] == "Dubai, UAE", rec["location"]

    # a brand-new posting still inserts as 'new'
    added, updated = jobsdb.upsert(db, [jobsdb.normalize(
        {"id": "co:2", "company": "Beta", "title": "FE"})])
    assert (added, updated) == (1, 0), (added, updated)
    assert jobsdb.index_by_id(db)["co:2"]["status"] == "new"
    assert jobsdb.index_by_id(db)["co:2"]["saved"] is False   # default off

    # --- merge_record modes ---------------------------------------------------
    old = {"id": "x", "status": "applied", "fit_score": 4}
    new = {"id": "x", "status": "new", "fit_score": 1}
    # default: new wins (dedupe relies on this)
    assert jobsdb.merge_record(old, new)["status"] == "new"
    # preserve: old's user state kept
    keep = jobsdb.merge_record(old, new, preserve_user_state=True)
    assert keep["status"] == "applied", keep["status"]
    assert keep["fit_score"] == 4, keep["fit_score"]

    # --- experience filter + sort + counts ------------------------------------
    import dashboard
    exp = [jobsdb.normalize({"id": "e:%d" % i, "experience_tag": t, "fit_score": f})
           for i, (t, f) in enumerate([("senior", 3), ("10-12yr", 2), ("mid", 5), ("unknown", 4)])]
    assert jobsdb.experience_counts(exp) == {"senior": 1, "10-12yr": 1, "mid": 1, "unknown": 1}
    only = dashboard.build_view(exp, "", "", "", "fit", experience="senior")
    assert [r["experience_tag"] for r in only] == ["senior"], only
    order = [r["experience_tag"] for r in dashboard.build_view(exp, "", "", "", "experience")]
    assert order == ["10-12yr", "senior", "mid", "unknown"], order   # senior-first, unknown last
    assert "experience" in dashboard.SORTS

    # --- source filter + sort + counts ----------------------------------------
    src = [jobsdb.normalize({"id": "s:%d" % i, "source": s, "fit_score": f})
           for i, (s, f) in enumerate([("linkedin-search", 3), ("portal:greenhouse", 2),
                                       ("manual", 5), ("portal:ashby", 4)])]
    assert jobsdb.source_counts(src) == {"linkedin-search": 1, "portal:greenhouse": 1,
                                         "manual": 1, "portal:ashby": 1}
    only = dashboard.build_view(src, "", "", "", "fit", source="manual")
    assert [r["source"] for r in only] == ["manual"], only
    order = [r["source"] for r in dashboard.build_view(src, "", "", "", "source")]
    assert order == ["portal:greenhouse", "portal:ashby", "linkedin-search", "manual"], order  # canonical group order
    assert "source" in dashboard.SORTS

    # --- deep evaluation: salary parse + rubric + flags -----------------------
    ps = jobsdb.parse_salary
    r = ps("$185K - $245K"); assert r["cur"] == "USD" and r["low"] == 185000 and r["high"] == 245000, r
    r = ps("EUR 90,000-110,000"); assert r["cur"] == "EUR" and r["low"] == 90000 and r["high"] == 110000, r
    r = ps("AED 22,500/mo"); assert r["cur"] == "AED" and r["high"] == 22500 and r["period"] == "month", r
    r = ps("up to 160K"); assert r["low"] is None and r["high"] == 160000, r
    r = ps("USD 130-220K base + 50-80K equity"); assert r["low"] == 130000 and r["high"] == 220000, r
    assert ps("Competitive") is None and ps(None) is None

    strong = jobsdb.normalize({
        "id": "ev:1", "title": "Senior Frontend Engineer", "experience_tag": "senior",
        "work_mode": "remote", "region_bucket": "europe", "salary": "$150K - $190K",
        "enrichment": {"skills": ["React", "TypeScript", "GSAP", "CSS"],
                       "description": "Build delightful, animated React interfaces in TypeScript. "
                                      "Work closely with designers on a polished, high-craft product. " * 3}})
    ev = strong["evaluation"]
    assert ev["method"] == "heuristic", ev
    assert ev["overall"] >= 4, ev
    assert ev["axes"]["stack"] == 5 and ev["axes"]["location"] == 5, ev["axes"]
    assert ev["flags"] == [], ev["flags"]          # a clean, legit posting

    scam = jobsdb.normalize({
        "id": "ev:2", "title": "Senior Software Engineer", "experience_tag": "senior", "salary": None,
        "enrichment": {"skills": [],
                       "description": "Great opportunity! Commission only. No experience needed. Apply now!"}})
    fl = scam["evaluation"]["flags"]
    for f in ("vague-jd", "commission-only", "title-mismatch"):
        assert f in fl, (f, fl)

    import evaluate
    prompt = evaluate.build_eval_prompt(strong, {})
    assert isinstance(prompt, str) and "TARGET JOB" in prompt and "Senior Frontend Engineer" in prompt

    # --- momentum: status auto-logging -> dated activity ----------------------
    m1 = jobsdb.normalize({"id": "m:1", "status": "new"})
    e = jobsdb.log_status_activity(m1, "new", "applied", today="2026-08-01")
    assert e and e["kind"] == "applied" and e["date"] == "2026-08-01" and e["source"] == "auto", e
    # idempotent: a same-day, same-kind entry is never duplicated
    assert jobsdb.log_status_activity(m1, "applied", "applied", today="2026-08-01") is None
    assert sum(1 for a in m1["activity"] if a["kind"] == "applied") == 1
    # funnel status maps to the matching activity kind; non-funnel + no-op log nothing
    assert jobsdb.log_status_activity(m1, "applied", "interviewing",
                                      today="2026-08-02")["kind"] == "interview"
    assert jobsdb.log_status_activity(m1, "new", "shortlisted", today="2026-08-02") is None
    assert jobsdb.log_status_activity(m1, "applied", "applied", today="2026-08-02") is None

    # --- momentum: daily heatmap counts (one dict entry per active day) --------
    hm = [{"id": "h:1", "activity": [{"date": "2026-08-05", "kind": "applied"},
                                     {"date": "2026-08-05", "kind": "email"},
                                     {"date": "2026-08-06", "kind": "note"}]},
          {"id": "h:2", "activity": [{"date": "2026-08-06", "kind": "applied"}]}]
    assert jobsdb.daily_activity_counts(hm) == {"2026-08-05": 2, "2026-08-06": 2}
    # trailing window drops days outside [today-days+1, today]
    assert jobsdb.daily_activity_counts(hm, days=2, today="2026-08-07") == {"2026-08-06": 2}
    # the auto heuristic evaluation is NOT effort; only an AI eval counts
    assert jobsdb.effort_events([strong]) == []            # strong has a heuristic eval only
    ai = dict(strong, id="ai:1", evaluation={"method": "ai", "evaluated_at": "2026-08-06"})
    assert jobsdb.daily_activity_counts([ai]) == {"2026-08-06": 1}

    # --- momentum: forgiving streak (grace today, rest tokens bridge a gap) ----
    cs = jobsdb.compute_streak
    assert cs([], today="2026-08-07") == 0
    assert cs(["2026-08-06", "2026-08-05", "2026-08-04"], today="2026-08-07") == 3   # today unworked = grace
    assert cs(["2026-08-07", "2026-08-05"], today="2026-08-07") == 2                 # 1 rest bridges 08-06
    assert cs(["2026-08-07", "2026-08-04"], today="2026-08-07") == 1                 # 2-day gap ends it
    assert cs(["2026-08-07", "2026-08-05"], today="2026-08-07", rest_budget=0) == 1  # no rest -> gap ends it

    # --- momentum: growth state (points -> stage, blossoms/fruit, never dead) --
    gs0 = jobsdb.growth_state([], today="2026-08-07")
    assert gs0 == {"points": 0.0, "growth": 0.0, "stage": "seed", "blossoms": 0,
                   "fruit": 0, "mood": "resting", "recent_actions": 0,
                   "planted_at": "2026-08-07"}, gs0
    g_recs = [jobsdb.normalize({"id": "g:1", "status": "offer",
                                "activity": [{"date": "2026-08-06", "kind": "interview"}]}),
              jobsdb.normalize({"id": "g:2", "status": "applied"}),
              jobsdb.normalize({"id": "g:3", "status": "interviewing"})]
    gs = jobsdb.growth_state(g_recs, today="2026-08-07")
    assert gs["blossoms"] == 2, gs      # g:1 logged interview + g:3 at interviewing (implicit)
    assert gs["fruit"] == 1, gs         # g:1 has an offer
    assert gs["points"] == 24.0 and gs["stage"] == "sapling", gs
    assert jobsdb.growth_stage(0.0) == "seed" and jobsdb.growth_stage(1.0) == "mature"

    # --- momentum: forgiving goal defaults ------------------------------------
    import configlib
    assert configlib.goals({}) == {"daily_actions": 3, "rest_allowance": 1}
    assert configlib.goals({"goals": {"daily_actions": 5}})["daily_actions"] == 5
    assert configlib.goals({"goals": {"daily_actions": -2}})["daily_actions"] == 3   # negatives rejected

    print("test_jobsdb: OK")


if __name__ == "__main__":
    main()
