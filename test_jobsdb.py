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

    print("test_jobsdb: OK")


if __name__ == "__main__":
    main()
