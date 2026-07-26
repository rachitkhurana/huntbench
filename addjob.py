#!/usr/bin/env python3
"""addjob - add a single job POSTING or a whole job BOARD from a pasted URL.

Two entry points used by the dashboard (POST /api/add) and the `jobsdb.py addurl` CLI:

  add_posting(url)  fetch the ATS posting, score + enrich it, upsert as a 'new' job.
                    If the URL isn't a recognised ATS posting, it's saved as a lead
                    (tagged 'needs-jd') so nothing ever bounces.
  add_board(url)    validate the URL is a real, scannable ATS board, then append it to
                    config/portals.yml's tracked_companies (preserving the whole file).

Zero new dependencies: reuses scan.py's per-provider board fetchers + jobsdb's normalize/
upsert. Supported ATS = the six scan.PROVIDERS handle: greenhouse, ashby, lever, workable,
recruitee, smartrecruiters.
"""

import hashlib
import os
import re
from urllib.parse import urlparse

import configlib
import jobsdb
import scan


# ---- URL parsing -------------------------------------------------------------

_HOST_PROVIDER = (
    ("greenhouse", "greenhouse"), ("ashby", "ashbyhq"), ("lever", "lever.co"),
    ("workable", "workable"), ("recruitee", "recruitee"), ("smartrecruiters", "smartrecruiters"),
)


def detect_provider(url):
    """Map a URL's host to an ATS provider key, or None."""
    host = urlparse(url or "").netloc.lower()
    for key, needle in _HOST_PROVIDER:
        if needle in host:
            return key
    return None


def board_slug(provider, url):
    """The board token for a provider, derived from either a board or a posting URL."""
    p = urlparse(url or "")
    host, path = p.netloc.lower(), p.path
    segs = [s for s in path.strip("/").split("/") if s]
    if provider == "recruitee":
        return host.split(".")[0] if host else ""
    if provider == "greenhouse":
        m = re.search(r"/boards/([^/]+)/jobs", path)   # boards-api.greenhouse.io/v1/boards/<slug>/jobs
        if m:
            return m.group(1)
        return segs[0] if segs else ""
    if provider == "workable":
        label = host.split(".")[0]
        if host.endswith(".workable.com") and label not in ("apply", "www"):
            return label
        return segs[0] if segs else ""
    return segs[0] if segs else ""   # ashby, lever, smartrecruiters


_CANON = {
    "greenhouse": "https://job-boards.greenhouse.io/%s",
    "ashby": "https://jobs.ashbyhq.com/%s",
    "lever": "https://jobs.lever.co/%s",
    "workable": "https://apply.workable.com/%s/",
    "recruitee": "https://%s.recruitee.com",
    "smartrecruiters": "https://careers.smartrecruiters.com/%s",
}


def canonical_board_url(provider, slug):
    """A clean careers_url for portals.yml — never store a pasted posting URL as the board."""
    return (_CANON.get(provider) or "%s") % slug


def company_from_slug(slug):
    return re.sub(r"[-_]+", " ", slug or "").strip().title() or "Unknown"


def _company_from_host(host):
    parts = (host or "").replace("www.", "").split(".")
    return (parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")).title() or "Unknown"


def _norm_url(u):
    return (u or "").split("?")[0].split("#")[0].rstrip("/").lower()


def _match_job(jobs, url):
    """Find the one posting in a fetched board that this URL points to."""
    nu = _norm_url(url)
    for j in jobs:                                   # by posting URL
        ju = _norm_url(j.get("url"))
        if ju and (ju == nu or ju.endswith(nu) or nu.endswith(ju)):
            return j
    for j in jobs:                                   # else by external id in the URL
        eid = str(j.get("ext_id") or "")
        if eid and eid in url:
            return j
    return None


# ---- add a posting -----------------------------------------------------------

def _lead_record(url, slug):
    """A minimal record for a URL we can't parse as a supported ATS posting."""
    p = urlparse(url)
    segs = [s for s in p.path.strip("/").split("/") if s]
    title = ""
    if segs:
        last = segs[-1]
        if not last.isdigit() and len(last) > 3 and not re.fullmatch(r"[0-9a-fA-F-]{8,}", last):
            title = re.sub(r"[-_]+", " ", last).strip().title()
    return {
        "id": "lead:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],
        "company": company_from_slug(slug) if slug else _company_from_host(p.netloc.lower()),
        "title": title or "Untitled role",
        "url": url,                        # explicit — else normalize() fabricates a LinkedIn URL
        "source": "manual",
        "tags": ["needs-jd"],
    }


def add_posting(url):
    """Fetch + score a single posting (or save a lead). Returns {ok, source, record, ...}."""
    url = (url or "").strip()
    if not url:
        return {"error": "Please paste a job posting URL."}
    provider = detect_provider(url)
    slug = board_slug(provider, url) if provider else ""
    rec, source = None, "lead"
    if provider and slug:
        try:
            jobs = scan.PROVIDERS[provider](slug) or []
        except Exception:                   # noqa - a dead board must not sink the add
            jobs = []
        job = _match_job(jobs, url)
        if job:
            rec = scan._to_record({"name": company_from_slug(slug)}, provider, job)
            source = "ats"
    if rec is None:
        rec = _lead_record(url, slug)
        source = "lead"

    db = jobsdb.load_db()
    existed = rec["id"] in jobsdb.index_by_id(db)
    added, _ = jobsdb.upsert(db, [jobsdb.normalize(rec)])
    jobsdb.save_db(db)
    final = jobsdb.index_by_id(db).get(rec["id"])
    return {"ok": True, "source": source, "existed": existed, "added": bool(added), "record": final}


# ---- add a board -------------------------------------------------------------

def add_board(url):
    """Validate an ATS board URL and append it to portals.yml. Returns {ok,...} or {error}."""
    url = (url or "").strip()
    if not url:
        return {"error": "Please paste a job board URL."}
    provider = detect_provider(url)
    slug = board_slug(provider, url) if provider else ""
    if not (provider and slug):
        return {"error": "That doesn't look like a supported ATS board "
                         "(Greenhouse, Ashby, Lever, Workable, Recruitee, SmartRecruiters)."}
    name = company_from_slug(slug)

    portals, _ = configlib.load_portals()
    for e in (portals.get("tracked_companies") or []):
        ep = scan.resolve_provider(e)
        es = scan.resolve_slug(e, ep) if ep else None
        if ep == provider and (es or "").lower() == slug.lower():
            return {"ok": True, "existed": True, "name": e.get("name") or name, "provider": provider}

    try:
        jobs = scan.PROVIDERS[provider](slug) or []
    except Exception:                       # noqa
        jobs = []
    if not jobs:
        return {"error": "Couldn't validate that board — no open roles found. Double-check the URL."}

    entry = {"name": name, "provider": provider, "careers_url": canonical_board_url(provider, slug)}
    if provider == "greenhouse":
        entry["api"] = "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug
    append_board_to_portals(entry)
    return {"ok": True, "added": True, "name": name, "provider": provider, "count": len(jobs)}


# ---- portals.yml append (preserve the whole file) ----------------------------

def _yq(s):
    """Double-quote a scalar for YAML (matches webui._yq)."""
    return '"%s"' % str(s or "").replace("\\", "\\\\").replace('"', '\\"')


def _entry_block(e):
    """The 2-space-indented tracked_companies entry, as a list of lines (leading blank)."""
    L = ["", "  - name: %s" % _yq(e["name"]),
         "    provider: %s" % e["provider"],
         "    careers_url: %s" % e["careers_url"]]
    if e.get("api"):
        L.append("    api: %s" % e["api"])
    L.append('    notes: "Added via dashboard"')
    L.append("    enabled: true")
    return L


def _insert_into_tracked(text, block_lines):
    """Insert block_lines at the end of the tracked_companies: block, preserving everything else."""
    lines = text.split("\n")
    ti = next((i for i, l in enumerate(lines) if re.match(r"^tracked_companies\s*:\s*$", l)), None)
    if ti is None:
        base = text.rstrip("\n")
        body = "\n".join(l for l in block_lines if l != "")
        return base + "\n\ntracked_companies:\n" + body + "\n"
    end = len(lines)                                   # end of block = next column-0 line, else EOF
    for j in range(ti + 1, len(lines)):
        if lines[j] and not lines[j][0].isspace():
            end = j
            break
    ins = end                                          # skip back over trailing blank lines
    while ins - 1 > ti and lines[ins - 1].strip() == "":
        ins -= 1
    return "\n".join(lines[:ins] + block_lines + lines[ins:])


def append_board_to_portals(entry):
    """Append one board to config/portals.yml, seeding from the example on a fresh clone."""
    target = os.path.join(configlib.CONFIG_DIR, "portals.yml")
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            text = f.read()
    else:
        ex = os.path.join(configlib.CONFIG_DIR, "portals.example.yml")
        text = open(ex, encoding="utf-8").read() if os.path.exists(ex) else "tracked_companies:\n"
    new = _insert_into_tracked(text, _entry_block(entry))
    os.makedirs(configlib.CONFIG_DIR, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(new)
    return target
