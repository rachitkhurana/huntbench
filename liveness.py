#!/usr/bin/env python3
"""liveness - check whether job URLs are still live, and optionally prune dead ones.

Classifies each record's URL as active / expired / uncertain (stdlib urllib). LinkedIn
hosts are treated conservatively (their logged-out bot-wall means we only hard-expire on
404/410, never on page content). Writes `live` + `live_checked` onto each record; `--prune`
sets expired records to status=skip.

    ./jobsdb.py liveness                 # check all
    ./jobsdb.py liveness --region uae --limit 20
    ./jobsdb.py liveness --stale-only --prune
"""

import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import jobsdb

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15

_EXPIRED_PHRASES = [
    "no longer accepting applications", "no longer available",
    "this job is no longer", "position has been filled", "posting is closed",
    "this posting is closed", "job posting has expired", "position is closed",
    "job has expired", "role has been filled", "we are no longer accepting",
    "job you are looking for is not", "job not found", "posting not found",
]


def classify(url):
    """Return (verdict, reason). verdict in {active, expired, uncertain}."""
    if not url:
        return "uncertain", "no url"
    host = urlparse(url).netloc.lower()
    is_linkedin = "linkedin.com" in host
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            code = r.getcode()
            body = r.read(200_000).decode("utf-8", "replace").lower()
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return "expired", "HTTP %d" % e.code
        return "uncertain", "HTTP %d" % e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return "uncertain", "fetch error"
    if is_linkedin:
        if "no longer accepting applications" in body:
            return "expired", "linkedin: closed"
        return "uncertain", "linkedin (needs manual/MCP check)"
    if any(p in body for p in _EXPIRED_PHRASES):
        return "expired", "closed phrase"
    return "active", "HTTP %d" % code


def _select(db, args):
    rows = db
    if getattr(args, "id", None):
        rows = [r for r in rows if r.get("id") == args.id]
    if getattr(args, "region", None):
        rows = [r for r in rows if r.get("region_bucket") == args.region]
    if getattr(args, "stale_only", False):
        rows = [r for r in rows if not r.get("live")]
    if getattr(args, "limit", None):
        rows = rows[:args.limit]
    return rows


def run(args):
    db = jobsdb.load_db()
    targets = _select(db, args)
    if not targets:
        print("liveness: no matching records")
        return 0
    print("liveness: checking %d URLs%s ..."
          % (len(targets), " (--prune)" if getattr(args, "prune", False) else ""))
    with ThreadPoolExecutor(max_workers=8) as ex:
        verdicts = list(ex.map(lambda r: classify(r.get("url")), targets))
    counts = {"active": 0, "expired": 0, "uncertain": 0}
    pruned = 0
    for rec, (verdict, reason) in zip(targets, verdicts):
        rec["live"] = verdict
        rec["live_checked"] = jobsdb.TODAY
        counts[verdict] = counts.get(verdict, 0) + 1
        if getattr(args, "prune", False) and verdict == "expired" and rec.get("status") in ("new", "shortlisted"):
            rec["status"] = "skip"
            pruned += 1
        rec["updated"] = jobsdb.TODAY
        if verdict != "active":
            print("  %-9s %-22s %s (%s)" % (verdict, (rec.get("company") or "")[:22],
                                            (rec.get("title") or "")[:34], reason))
    jobsdb.save_db(db)
    print("\nliveness: active=%d  expired=%d  uncertain=%d%s"
          % (counts["active"], counts["expired"], counts["uncertain"],
             ("  (pruned %d -> skip)" % pruned) if pruned else ""))
    return 0
