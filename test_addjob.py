#!/usr/bin/env python3
"""Offline self-check for addjob URL parsing + portals append: python3 test_addjob.py

No network: covers provider/slug parsing for every ATS, the lead-stub fallback, and that
appending a board to portals.yml preserves the entire existing file.
"""

import addjob
import jobsdb


def test_url_parsing():
    # (url, provider, slug) — a board URL and a posting URL for each provider
    cases = [
        ("https://job-boards.greenhouse.io/vercel", "greenhouse", "vercel"),
        ("https://job-boards.greenhouse.io/vercel/jobs/5778418004", "greenhouse", "vercel"),
        ("https://boards-api.greenhouse.io/v1/boards/stripe/jobs/123", "greenhouse", "stripe"),
        ("https://jobs.ashbyhq.com/linear", "ashby", "linear"),
        ("https://jobs.ashbyhq.com/linear/2b1c9e00-uuid-here", "ashby", "linear"),
        ("https://jobs.lever.co/spotify", "lever", "spotify"),
        ("https://jobs.lever.co/spotify/abc-def-uuid", "lever", "spotify"),
        ("https://apply.workable.com/acme/", "workable", "acme"),
        ("https://apply.workable.com/acme/j/ABC123/", "workable", "acme"),
        ("https://acme.workable.com/", "workable", "acme"),
        ("https://acme.recruitee.com", "recruitee", "acme"),
        ("https://acme.recruitee.com/o/senior-frontend-engineer", "recruitee", "acme"),
        ("https://careers.smartrecruiters.com/Acme/12345-role", "smartrecruiters", "Acme"),
    ]
    for url, prov, slug in cases:
        assert addjob.detect_provider(url) == prov, (url, addjob.detect_provider(url))
        assert addjob.board_slug(prov, url) == slug, (url, addjob.board_slug(prov, url))
    assert addjob.detect_provider("https://www.linkedin.com/jobs/view/123") is None
    assert addjob.detect_provider("https://example.com/careers/role") is None


def test_canonical_and_company():
    assert addjob.canonical_board_url("ashby", "linear") == "https://jobs.ashbyhq.com/linear"
    assert addjob.canonical_board_url("greenhouse", "vercel") == "https://job-boards.greenhouse.io/vercel"
    assert addjob.canonical_board_url("recruitee", "acme") == "https://acme.recruitee.com"
    assert addjob.company_from_slug("acme-corp") == "Acme Corp"
    assert addjob.company_from_slug("scaleai") == "Scaleai"


def test_lead_record():
    r = addjob._lead_record(
        "https://weworkremotely.com/remote-jobs/acme-senior-frontend-engineer", "")
    assert r["id"].startswith("lead:"), r["id"]
    assert r["tags"] == ["needs-jd"]
    assert r["url"] == "https://weworkremotely.com/remote-jobs/acme-senior-frontend-engineer"
    assert r["company"] == "Weworkremotely", r["company"]
    assert r["title"] and r["title"] != "Untitled role", r["title"]   # guessed from slug


def test_match_job():
    jobs = [{"ext_id": 111, "url": "https://job-boards.greenhouse.io/vercel/jobs/111"},
            {"ext_id": 222, "url": "https://job-boards.greenhouse.io/vercel/jobs/222"}]
    assert addjob._match_job(jobs, "https://job-boards.greenhouse.io/vercel/jobs/222")["ext_id"] == 222
    assert addjob._match_job(jobs, "https://job-boards.greenhouse.io/vercel/jobs/999") is None


def test_add_posting_lead_path():
    # unknown host -> no network, lands as a 'new' needs-jd lead. In-memory DB via monkeypatch.
    store = []
    orig = (jobsdb.load_db, jobsdb.save_db)
    jobsdb.load_db = lambda: store
    jobsdb.save_db = lambda recs: None
    try:
        res = addjob.add_posting("https://example.com/careers/staff-frontend-engineer")
        assert res["ok"] and res["source"] == "lead", res
        rec = res["record"]
        assert rec["status"] == "new" and "needs-jd" in rec["tags"]
        assert rec["url"] == "https://example.com/careers/staff-frontend-engineer"
        assert rec["id"].startswith("lead:")
        assert res["added"] is True and res["existed"] is False
        # re-adding the same URL must not duplicate
        res2 = addjob.add_posting("https://example.com/careers/staff-frontend-engineer")
        assert res2["existed"] is True and res2["added"] is False
        assert len(store) == 1
    finally:
        jobsdb.load_db, jobsdb.save_db = orig


_SAMPLE = """location_filter:
  allow:
    - "Remote"
title_filter:
  positive:
    - "Frontend"
# grow the list below
tracked_companies:
  - name: Vercel
    provider: greenhouse
    careers_url: https://job-boards.greenhouse.io/vercel
    enabled: true
"""


def test_portals_append_preserves_everything():
    block = addjob._entry_block(
        {"name": "Acme", "provider": "ashby", "careers_url": "https://jobs.ashbyhq.com/acme"})
    out = addjob._insert_into_tracked(_SAMPLE, block)
    # every pre-existing line survives
    for keep in ("location_filter:", "title_filter:", "Frontend", "# grow the list below", "Vercel"):
        assert keep in out, keep
    assert out.count("tracked_companies:") == 1
    assert 'name: "Acme"' in out and "provider: ashby" in out
    assert out.index("Vercel") < out.index("Acme")           # appended after existing entries

    # greenhouse entry carries an api: line
    gblock = addjob._entry_block(
        {"name": "Figma", "provider": "greenhouse", "careers_url": "https://job-boards.greenhouse.io/figma",
         "api": "https://boards-api.greenhouse.io/v1/boards/figma/jobs"})
    assert any("api: https://boards-api" in l for l in gblock)

    # tracked_companies NOT last -> insert before the following key
    sample2 = ("tracked_companies:\n  - name: Vercel\n    provider: greenhouse\n"
               "    careers_url: https://x/vercel\n    enabled: true\n\n"
               "search_queries:\n  - name: q\n")
    out2 = addjob._insert_into_tracked(sample2, block)
    assert out2.index("Vercel") < out2.index("Acme") < out2.index("search_queries:")

    # no tracked_companies key -> the key is created
    out3 = addjob._insert_into_tracked("title_filter:\n  positive:\n    - X\n", block)
    assert "tracked_companies:" in out3 and "Acme" in out3 and "title_filter:" in out3


def main():
    test_url_parsing()
    test_canonical_and_company()
    test_lead_record()
    test_match_job()
    test_add_posting_lead_path()
    test_portals_append_preserves_everything()
    print("test_addjob: OK")


if __name__ == "__main__":
    main()
