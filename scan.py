#!/usr/bin/env python3
"""scan - zero-token ATS portal scanner for Huntbench.

Pulls fresh openings straight from company career-board JSON APIs (Greenhouse, Ashby,
Lever, Workable, Recruitee, SmartRecruiters), applies the portals.yml title/location
filters, and upserts them into jobs.ndjson via jobsdb. Pure Python stdlib (urllib).

    ./jobsdb.py scan                 # scan every enabled tracked company
    ./jobsdb.py scan --company Vercel
    ./jobsdb.py scan --dry-run
"""

import html
import json
import re
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import configlib
import jobsdb

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 14


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        return None


def _strip_html(s):
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---- providers: each returns list of {ext_id,title,location,url,description} --

def _p_greenhouse(slug):
    data = _get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug)
    out = []
    for j in (data or {}).get("jobs", []):
        out.append({"ext_id": j.get("id"), "title": j.get("title") or "",
                    "location": (j.get("location") or {}).get("name", ""),
                    "url": j.get("absolute_url"),
                    "description": _strip_html(j.get("content"))})
    return out


def _p_ashby(slug):
    data = _get_json("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true" % slug)
    out = []
    for j in (data or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name") or ""
        out.append({"ext_id": j.get("id"), "title": j.get("title") or "",
                    "location": loc or "",
                    "url": j.get("jobUrl") or j.get("applyUrl"),
                    "description": j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml"))})
    return out


def _p_lever(slug):
    data = _get_json("https://api.lever.co/v0/postings/%s?mode=json" % slug)
    out = []
    for j in (data or []):
        out.append({"ext_id": j.get("id"), "title": j.get("text") or "",
                    "location": (j.get("categories") or {}).get("location", ""),
                    "url": j.get("hostedUrl"),
                    "description": j.get("descriptionPlain") or _strip_html(j.get("description"))})
    return out


def _p_workable(slug):
    data = _get_json("https://apply.workable.com/api/v1/widget/accounts/%s?details=true" % slug)
    out = []
    for j in (data or {}).get("jobs", []):
        loc = j.get("location") or {}
        loc = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x) if isinstance(loc, dict) else str(loc)
        out.append({"ext_id": j.get("shortcode") or j.get("id"), "title": j.get("title") or "",
                    "location": loc, "url": j.get("url") or j.get("application_url"),
                    "description": _strip_html(j.get("description"))})
    return out


def _p_recruitee(slug):
    data = _get_json("https://%s.recruitee.com/api/offers/" % slug)
    out = []
    for j in (data or {}).get("offers", []):
        loc = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        out.append({"ext_id": j.get("id"), "title": j.get("title") or "",
                    "location": loc or "", "url": j.get("careers_url") or j.get("url"),
                    "description": _strip_html(j.get("description"))})
    return out


def _p_smartrecruiters(slug):
    data = _get_json("https://api.smartrecruiters.com/v1/companies/%s/postings?status=PUBLIC&limit=100" % slug)
    out = []
    for j in (data or {}).get("content", []):
        loc = j.get("location") or {}
        loc = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x) if isinstance(loc, dict) else str(loc)
        out.append({"ext_id": j.get("id"), "title": j.get("name") or "", "location": loc,
                    "url": "https://jobs.smartrecruiters.com/%s/%s" % (slug, j.get("id")),
                    "description": ""})
    return out


PROVIDERS = {"greenhouse": _p_greenhouse, "ashby": _p_ashby, "lever": _p_lever,
             "workable": _p_workable, "recruitee": _p_recruitee,
             "smartrecruiters": _p_smartrecruiters}


def resolve_provider(entry):
    if entry.get("provider") in PROVIDERS:
        return entry["provider"]
    blob = (entry.get("api") or "") + " " + (entry.get("careers_url") or "")
    for key, host in (("greenhouse", "greenhouse"), ("ashby", "ashbyhq"),
                      ("lever", "lever.co"), ("workable", "workable"),
                      ("recruitee", "recruitee"), ("smartrecruiters", "smartrecruiters")):
        if host in blob:
            return key
    return None


def resolve_slug(entry, provider):
    url = entry.get("careers_url") or ""
    host, path = urlparse(url).netloc, urlparse(url).path.strip("/")
    if provider == "recruitee" and host:
        return host.split(".")[0]
    seg = path.split("/")[-1] if path else ""
    if not seg and entry.get("api"):
        m = re.search(r"/boards/([^/]+)/jobs", entry["api"])
        if m:
            return m.group(1)
    return seg


# ---- filters (portals.yml) ---------------------------------------------------

def title_ok(title, tf):
    t = (title or "").lower()
    pos = [w.lower() for w in (tf.get("positive") or [])]
    neg = [w.lower() for w in (tf.get("negative") or [])]
    if pos and not any(w in t for w in pos):
        return False
    if any(w in t for w in neg):
        return False
    return True


def location_ok(location, lf):
    loc = (location or "").lower()
    if not loc:
        return True
    if any(a.lower() in loc for a in (lf.get("always_allow") or [])):
        return True
    if any(b.lower() in loc for b in (lf.get("block") or [])):
        return False
    allow = [a.lower() for a in (lf.get("allow") or [])]
    if allow and not any(a in loc for a in allow):
        return False
    return True


def _exp_tag(title):
    t = (title or "").lower()
    if any(w in t for w in ("principal", "staff", "head of", "director")):
        return "10-12yr"
    if any(w in t for w in ("lead", "manager")):
        return "director"
    if any(w in t for w in ("senior", "sr.", "sr ")):
        return "mid-senior"
    return "unknown"


def _to_record(entry, provider, job):
    if not job.get("ext_id") or not job.get("title"):
        return None
    desc = (job.get("description") or "")[:2200]
    rec = {
        "id": "%s:%s" % (provider, job["ext_id"]),
        "company": entry.get("name") or "",
        "title": job["title"],
        "location": job.get("location") or "",
        "url": job.get("url") or "",
        "source": "portal:%s" % provider,
        "search_query": "scan:%s" % (entry.get("name") or provider),
        "experience_tag": _exp_tag(job["title"]),
        "tags": ["portal", provider],
    }
    if desc:
        rec["enriched"] = True
        rec["enrichment"] = {"description": desc, "skills": [],
                             "fetched_at": jobsdb.TODAY, "source": "ats-scan"}
    return rec


def run(companies=None, provider=None, dry_run=False):
    portals, ppath = configlib.load_portals()
    if not portals:
        print("scan: no portals.yml found (looked in module, $CAREER_OPS_HOME, external tool)")
        return 1
    tf = portals.get("title_filter") or {}
    lf = portals.get("location_filter") or {}
    tracked = portals.get("tracked_companies") or []
    if companies:
        want = {c.lower() for c in companies}
        tracked = [t for t in tracked if (t.get("name") or "").lower() in want]
    if provider:
        tracked = [t for t in tracked if resolve_provider(t) == provider]

    fresh = []
    scanned = skipped_companies = raw = kept = 0
    print("scan: %d tracked companies (source: %s)%s"
          % (len(tracked), ppath, "  [DRY-RUN]" if dry_run else ""))

    # resolve each enabled company to (entry, provider, slug); skip the ones with no direct API
    targets = []
    for entry in tracked:
        if entry.get("enabled") is False:
            continue
        prov = resolve_provider(entry)
        slug = resolve_slug(entry, prov) if prov else None
        if not prov or not slug:
            print("  - %-16s SKIP (no direct API; scan_method=%s)"
                  % (entry.get("name"), entry.get("scan_method") or "websearch"))
            skipped_companies += 1
            continue
        targets.append((entry, prov, slug))

    # fetch every board CONCURRENTLY (each is a blocking urllib call) - ThreadPoolExecutor.map
    # preserves input order, so per-company output + counts stay deterministic.
    def _fetch(t):
        entry, prov, slug = t
        try:
            return t, PROVIDERS[prov](slug) or []
        except Exception:  # noqa - a dead board must not sink the whole scan
            return t, []

    with ThreadPoolExecutor(max_workers=min(16, len(targets) or 1)) as ex:
        fetched = list(ex.map(_fetch, targets))

    for (entry, prov, slug), jobs in fetched:
        scanned += 1
        got = len(jobs)
        raw += got
        matched = []
        for j in jobs:
            if title_ok(j["title"], tf) and location_ok(j["location"], lf):
                rec = _to_record(entry, prov, j)
                if rec:
                    matched.append(rec)
        kept += len(matched)
        fresh.extend(matched)
        print("  - %-16s %-13s %3d found -> %2d match" % (entry.get("name"), prov, got, len(matched)))

    if dry_run:
        print("\nscan (dry-run): %d companies, %d raw postings, %d passed filters. Nothing written."
              % (scanned, raw, kept))
        for r in fresh[:40]:
            print("    [%s] %s - %s (%s)" % (r["id"], r["company"], r["title"], r["location"]))
        if len(fresh) > 40:
            print("    ... +%d more" % (len(fresh) - 40))
        return 0

    db = jobsdb.load_db()
    recs = [jobsdb.normalize(r) for r in fresh]
    added, updated = jobsdb.upsert(db, recs)
    jobsdb.save_db(db)
    print("\nscan: +%d new, %d updated (%d companies, %d skipped, %d total in DB)"
          % (added, updated, scanned, skipped_companies, len(db)))
    if added:
        print("Tip: ./jobsdb.py render   and   ./jobsdb.py list --keyword scan")
    return 0
