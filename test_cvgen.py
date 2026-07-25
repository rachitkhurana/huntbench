#!/usr/bin/env python3
"""Self-check for the CV renderer: python3 test_cvgen.py

Covers the bits with real branching - template selection and the HTML/plain-text
escaping split (parsed fields are HTML-context, the .txt CV must be plain).
"""

import cvgen

MD = """# Ada Lovelace

**Tech Lead | Backend & AI | 7+ years**

## Summary

Ships **things** at scale & speed.

## Experience

### Acme - Tech Lead
**Jan 2020 - Present** · Remote
*Payments & ledger*
- Cut latency by 40% across R&D <systems>

## Skills

**Backend & Data:** Rails | Postgres

## Education

- **B.Tech, CS & Engineering** (2015-2019) - Some University
"""

PROFILE = {"candidate": {"full_name": "Ada Lovelace", "email": "ada@example.com",
                         "phone": ["+1 555"], "location": "London"}}


def main(tmp="/tmp/_cvgen_selfcheck.md"):
    open(tmp, "w").write(MD)
    cvgen.MASTER_CV = tmp
    m = cvgen.parse_master()
    assert m["subtitle"].startswith("Tech Lead"), m["subtitle"]
    assert m["experience"] and m["experience"][0]["company"] == "Acme"

    # every template renders a full document, and each swaps in its own CSS
    seen = set()
    for t in cvgen.CV_TEMPLATES:
        h = cvgen.build_cv(PROFILE, None, m, "other", t)
        assert h.startswith("<!doctype html>") and h.endswith("</body></html>"), t
        assert '<div class="name">Ada Lovelace</div>' in h, t
        seen.add(h)
    assert len(seen) == len(cvgen.CV_TEMPLATES), "templates produced identical output"
    # unknown template falls back instead of blowing up
    assert cvgen.build_cv(PROFILE, None, m, "other", "nope") == \
        cvgen.build_cv(PROFILE, None, m, "other", "classic")

    # escaping: HTML escapes once, plain text carries no entities
    h = cvgen.build_cv(PROFILE, None, m, "other")
    txt = cvgen.build_cv_txt(PROFILE, None, m)
    assert "Backend &amp; AI" in h and "&amp;amp;" not in h
    assert "&lt;systems&gt;" in h, "raw < > must be escaped in HTML"
    assert "Backend & AI" in txt and "Backend & Data: Rails" in txt
    assert "&amp;" not in txt and "&lt;" not in txt and "<strong>" not in txt

    # US region switches page size; everything else is A4
    assert "size:Letter" in cvgen.build_cv(PROFILE, None, m, "us")
    assert "size:A4" in cvgen.build_cv(PROFILE, None, m, "uae")

    print("test_cvgen: OK (%d templates)" % len(cvgen.CV_TEMPLATES))


if __name__ == "__main__":
    main()
