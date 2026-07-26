#!/usr/bin/env python3
"""Offline self-check for the feed providers: python3 test_scan.py

No network — _get_json/_get_text are monkeypatched with fixtures. Covers RSS + Atom parsing,
the JSON aggregators (RemoteOK/Remotive), per-job company in _to_record, and resolve_slug.
"""

import scan


_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>WWR</title>
  <item>
    <title>Acme Corp: Senior Frontend Engineer</title>
    <link>https://example.com/jobs/1</link>
    <region>Anywhere in the World</region>
    <guid>https://example.com/jobs/1</guid>
    <description><![CDATA[<p>Build <b>great</b> UIs.</p>]]></description>
  </item>
  <item>
    <title>Plain Title No Company</title>
    <link>https://example.com/jobs/2</link>
    <description>Second role</description>
  </item>
</channel></rss>"""

_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Globex: Backend Engineer</title>
    <link href="https://example.com/a/1"/>
    <id>atom-1</id>
    <summary>Do backend things</summary>
  </entry>
</feed>"""


def _with_text(text, fn):
    orig = scan._get_text
    scan._get_text = lambda url: text
    try:
        return fn()
    finally:
        scan._get_text = orig


def _with_json(obj, fn):
    orig = scan._get_json
    scan._get_json = lambda url: obj
    try:
        return fn()
    finally:
        scan._get_json = orig


def test_rss():
    jobs = _with_text(_RSS, lambda: scan._p_rss("http://feed"))
    assert len(jobs) == 2, len(jobs)
    a = jobs[0]
    assert a["company"] == "Acme Corp", a["company"]                 # 'Company: Title' split
    assert a["title"] == "Senior Frontend Engineer", a["title"]
    assert a["location"] == "Anywhere in the World", a["location"]   # <region>, not <category>
    assert a["url"] == "https://example.com/jobs/1"
    assert a["ext_id"] == "https://example.com/jobs/1"               # guid
    assert a["description"] == "Build great UIs.", a["description"]  # CDATA + html stripped
    b = jobs[1]
    assert b["company"] == "" and b["title"] == "Plain Title No Company"   # no colon -> no company
    assert b["ext_id"] == "https://example.com/jobs/2"              # falls back to link


def test_atom():
    jobs = _with_text(_ATOM, lambda: scan._p_rss("http://feed"))
    assert len(jobs) == 1
    j = jobs[0]
    assert j["company"] == "Globex" and j["title"] == "Backend Engineer"
    assert j["url"] == "https://example.com/a/1"                    # <link href>
    assert j["ext_id"] == "atom-1"
    assert j["description"] == "Do backend things"


def test_rss_empty_is_safe():
    assert _with_text(None, lambda: scan._p_rss("http://feed")) == []
    assert _with_text("<not xml", lambda: scan._p_rss("http://feed")) == []


def test_remoteok():
    fixture = [
        {"legal": "you agree to terms"},                            # index 0 metadata (no 'position')
        {"id": "1", "position": "Frontend Engineer", "company": "Acme",
         "location": "Remote, ", "url": "https://r/1", "description": "<p>hi</p>",
         "tags": ["react", "frontend"]},
    ]
    jobs = _with_json(fixture, lambda: scan._p_remoteok())
    assert len(jobs) == 1                                           # metadata blob skipped
    j = jobs[0]
    assert j["company"] == "Acme" and j["title"] == "Frontend Engineer"
    assert j["location"] == "Remote"                               # trailing ', ' stripped
    assert j["tags"] == ["react", "frontend"]
    assert j["description"] == "hi"


def test_remotive():
    fixture = {"jobs": [{"id": 2, "title": "Fullstack Dev", "company_name": "Beta",
                         "candidate_required_location": "Worldwide", "url": "https://rm/2",
                         "description": "<b>x</b>", "tags": ["node"]}]}
    jobs = _with_json(fixture, lambda: scan._p_remotive())
    assert len(jobs) == 1
    j = jobs[0]
    assert j["company"] == "Beta" and j["location"] == "Worldwide"
    assert j["url"] == "https://rm/2"


def test_to_record_company_and_tags():
    # feed job carries its own company -> wins over the portals entry name
    rec = scan._to_record({"name": "RemoteOK"}, "remoteok",
                          {"ext_id": "1", "title": "FE", "company": "Acme",
                           "location": "Remote", "url": "u", "tags": ["react"]})
    assert rec["company"] == "Acme", rec["company"]
    assert rec["id"] == "remoteok:1"
    assert "portal" in rec["tags"] and "remoteok" in rec["tags"] and "react" in rec["tags"]
    # ATS job with no per-job company -> falls back to the board name
    rec2 = scan._to_record({"name": "Vercel"}, "greenhouse", {"ext_id": "9", "title": "FE"})
    assert rec2["company"] == "Vercel"
    assert rec2["tags"] == ["portal", "greenhouse"]


def test_feed_work_mode():
    import jobsdb
    # remote-only aggregators are forced remote regardless of the location string
    rec = scan._to_record({"name": "RemoteOK"}, "remoteok",
                          {"ext_id": "1", "title": "FE", "company": "Acme", "location": "USA Only"})
    assert rec["work_mode"] == "remote", rec.get("work_mode")
    # ATS/rss set no work_mode -> normalize infers it; worldwide/anywhere now read as remote
    ats = scan._to_record({"name": "V"}, "greenhouse", {"ext_id": "9", "title": "FE", "location": "Berlin"})
    assert "work_mode" not in ats
    assert jobsdb.infer_work_mode("Anywhere in the World") == "remote"
    assert jobsdb.infer_work_mode("Worldwide") == "remote"
    assert jobsdb.infer_work_mode("Berlin, Germany") == "unknown"


def test_resolve():
    assert scan.resolve_provider({"provider": "remoteok"}) == "remoteok"
    assert scan.resolve_provider({"provider": "rss", "feed": "x"}) == "rss"
    assert scan.resolve_slug({"feed": "https://x/f.rss"}, "rss") == "https://x/f.rss"
    assert scan.resolve_slug({}, "remoteok") == "remoteok"          # fixed-feed token
    assert scan.resolve_slug({}, "remotive") == "remotive"
    # existing ATS behaviour intact
    assert scan.resolve_slug({"careers_url": "https://job-boards.greenhouse.io/vercel"},
                             "greenhouse") == "vercel"


def main():
    test_rss()
    test_atom()
    test_rss_empty_is_safe()
    test_remoteok()
    test_remotive()
    test_to_record_company_and_tags()
    test_feed_work_mode()
    test_resolve()
    print("test_scan: OK")


if __name__ == "__main__":
    main()
