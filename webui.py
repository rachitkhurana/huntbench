#!/usr/bin/env python3
"""webui - a local web GUI for Huntbench (jobsdb serve).

A tiny stdlib http.server that exposes jobsdb + dashboard + the CV/scan/apply tools as JSON
endpoints and serves one self-contained HTML page (webui.html). Browse, triage, and run tools
from the browser - no dependencies, no build step. Binds to 127.0.0.1 (loopback) only.

    ./jobsdb.py serve                      # opens http://127.0.0.1:8765
    ./jobsdb.py serve --port 9000 --no-open

Handlers are stateless: every request reloads jobs.ndjson (cheap), so a background tool that
writes the DB never leaves the server holding stale data. The apply *browser-drive* still happens
in chat - the GUI's "Prep apply" builds the packet, then say "apply to <id>" to Claude
(see APPLY-RUNBOOK.md).
"""

import datetime
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cvgen
import dashboard
import jobsdb

HERE = jobsdb.HERE
HTML_PATH = os.path.join(HERE, "webui.html")     # the Linear-style light UI, served at /
# A "sync inbox" click drops this signal file; Claude (in chat / watching) picks it up, runs the
# Gmail sync, then removes it. The server can't read Gmail itself (agent-side MCP only).
SYNC_REQ = os.path.join(HERE, ".sync-request.json")

# Roots the /api/file endpoint may serve from (CV PDFs, apply packets, generated views).
_FILE_ROOTS = [
    os.path.join(cvgen.MODULE_DIR, "output"),
    cvgen.MODULE_DIR,
]

ALLOWED_TASK_CMDS = {"scan", "liveness", "cv", "tailor", "apply", "render"}

# ---- background task registry (long-running tools) ---------------------------

_TASKS = {}
_TLOCK = threading.Lock()
_TSEQ = [0]


def _new_task(cmd):
    with _TLOCK:
        _TSEQ[0] += 1
        tid = "t%d" % _TSEQ[0]
        _TASKS[tid] = {"tid": tid, "cmd": cmd, "status": "running", "code": None, "log": ""}
    return tid


def _finish_task(tid, code, log):
    with _TLOCK:
        t = _TASKS.get(tid)
        if t:
            t["status"] = "done" if code == 0 else "error"
            t["code"] = code
            t["log"] = log


def _run_subprocess_task(tid, argv):
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "jobsdb.py")] + argv,
                           cwd=HERE, capture_output=True, text=True, timeout=600)
        log = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        _finish_task(tid, r.returncode, log[-8000:])
    except Exception as e:  # noqa
        _finish_task(tid, 1, "task error: %s" % e)


def _argv_for(cmd, params):
    argv = [cmd]
    if cmd in ("cv", "tailor", "apply", "liveness") and params.get("id"):
        argv += ["--id", params["id"]]
    if cmd == "scan":
        for c in (params.get("companies") or []):
            argv += ["--company", c]
        if params.get("provider"):
            argv += ["--provider", params["provider"]]
        if params.get("dry_run"):
            argv += ["--dry-run"]
    if cmd == "liveness" and params.get("prune"):
        argv += ["--prune"]
    if cmd in ("cv", "tailor", "apply"):
        if params.get("slug"):
            argv += ["--slug", params["slug"]]
        if params.get("region"):
            argv += ["--region", params["region"]]
        if params.get("no_pdf"):
            argv += ["--no-pdf"]
    if cmd == "apply" and params.get("no_tailor"):
        argv += ["--no-tailor"]
    return argv


def start_task(cmd, params):
    """Run a jobsdb subcommand in a worker thread; return its task id."""
    tid = _new_task(cmd)
    argv = _argv_for(cmd, params)
    threading.Thread(target=_run_subprocess_task, args=(tid, argv), daemon=True).start()
    return tid


# ---- payload builders --------------------------------------------------------

_ROW_KEYS = ("id", "company", "title", "fit_score", "status", "region_bucket",
             "work_mode", "location", "tags", "enriched", "url", "experience_tag", "salary")


def row(rec):
    return {k: rec.get(k) for k in _ROW_KEYS}


def apply_update(records, jid, changes):
    """Pure mutation of record `jid` from {status,fit,notes,add_tag}. Returns rec or None.
    Mirrors dashboard.act_status/act_note/act_fit semantics; caller persists via save_db."""
    rec = jobsdb.index_by_id(records).get(jid)
    if not rec:
        return None
    if changes.get("status") in jobsdb.STATUSES:
        rec["status"] = changes["status"]
    if changes.get("fit") not in (None, ""):
        try:
            f = int(changes["fit"])
            if 1 <= f <= 5:
                rec["fit_score"] = f
        except (ValueError, TypeError):
            pass
    if "notes" in changes:
        rec["notes"] = changes.get("notes") or ""
    tag = (changes.get("add_tag") or "").strip()
    if tag:
        tags = rec.get("tags") or []
        if tag not in tags:
            rec["tags"] = tags + [tag]
    rec["updated"] = jobsdb.TODAY
    return rec


def artifacts_payload(rec):
    outdir = cvgen._outdir(rec, None)
    n = cvgen.artifact_names(rec)
    # clean label -> [candidate filenames]: new role-named first, then legacy flat names
    # (cv.pdf etc.) so CVs generated BEFORE the role-in-filename change still surface.
    want = [
        ("cv.pdf",            [n["cv_pdf"], "cv.pdf"]),
        ("cv.html",           [n["cv_html"], "cv.html"]),
        ("cover-letter.pdf",  [n["cl_pdf"], "cover-letter.pdf"]),
        ("cover-letter.txt",  [n["cl_txt"], "cover-letter.txt"]),
        ("apply-packet.json", ["apply-packet.json"]),
        ("apply-packet.md",   ["apply-packet.md"]),
    ]
    files = {}
    for label, cands in want:
        files[label] = next(
            (os.path.abspath(os.path.join(outdir, f))
             for f in cands if os.path.exists(os.path.join(outdir, f))), None)
    return {"outdir": outdir, "files": files}


def interviews_payload():
    """Every interview activity across the DB, split into upcoming vs past (ISO dates compare fine)."""
    db = jobsdb.load_db()
    today = jobsdb.TODAY
    up, past = [], []
    for rec in db:
        for a in (rec.get("activity") or []):
            if a.get("kind") != "interview":
                continue
            row = {"id": rec.get("id"), "company": rec.get("company"), "title": rec.get("title"),
                   "status": rec.get("status"), "url": rec.get("url"),
                   "region_bucket": rec.get("region_bucket"), "date": a.get("date"),
                   "stage": a.get("title"), "detail": a.get("detail"),
                   "contact": a.get("contact"), "link": a.get("link")}
            (up if (a.get("date") or "") >= today else past).append(row)
    up.sort(key=lambda r: r.get("date") or "")
    past.sort(key=lambda r: r.get("date") or "", reverse=True)
    return {"upcoming": up, "past": past}


def activity_payload(kind=None, limit=300):
    """Every activity item across the DB (emails, interviews, status events), newest first,
    each tagged with its job. Powers the 'all communications' feed."""
    db = jobsdb.load_db()
    items = []
    for rec in db:
        for a in (rec.get("activity") or []):
            if kind and a.get("kind") != kind:
                continue
            items.append({"id": rec.get("id"), "company": rec.get("company"),
                          "title": rec.get("title"), "status": rec.get("status"),
                          "date": a.get("date"), "kind": a.get("kind"),
                          "subject": a.get("title"), "detail": a.get("detail"),
                          "contact": a.get("contact"), "link": a.get("link")})
    items.sort(key=lambda r: (r.get("date") or "", r.get("company") or ""), reverse=True)
    return {"items": items[:limit], "count": len(items)}


CONFIG_DIR = os.path.join(HERE, "config")


def status_payload():
    import configlib
    has_profile = os.path.exists(os.path.join(CONFIG_DIR, "profile.yml"))
    has_cv = os.path.exists(os.path.join(CONFIG_DIR, "master-cv.md"))
    has_portals = os.path.exists(os.path.join(CONFIG_DIR, "portals.yml"))
    db = jobsdb.load_db()
    demo = bool(db) and all((r.get("source") == "demo") for r in db)
    prof, _ = configlib.load_profile()
    name = ((prof.get("candidate") or {}).get("full_name")) or ""
    return {"configured": has_profile and has_cv, "has_profile": has_profile,
            "has_cv": has_cv, "has_portals": has_portals, "demo": demo,
            "jobs": len(db), "name": name}


def _yq(s):
    """Quote a scalar for YAML (double-quoted, escaping backslash + quote)."""
    return '"%s"' % str(s or "").replace("\\", "\\\\").replace('"', '\\"')


def _write_profile_yaml(d):
    """Emit a parser-compatible config/profile.yml from the onboarding form fields."""
    L = ["# Generated by the Huntbench setup wizard. Edit freely.", "", "candidate:"]
    L.append("  full_name: %s" % _yq(d.get("name")))
    L.append("  email: %s" % _yq(d.get("email")))
    L.append("  phone:")
    L.append("    - %s" % _yq(d.get("phone") or ""))
    L.append("  location: %s" % _yq(d.get("location")))
    L.append("  linkedin: %s" % _yq(d.get("linkedin")))
    L.append("  portfolio_url: %s" % _yq(d.get("portfolio")))
    L.append("  github: %s" % _yq(d.get("github")))
    roles = [r.strip() for r in (d.get("roles") or []) if r.strip()]
    L += ["", "target_roles:", "  primary:"]
    for r in (roles or ["Software Engineer"]):
        L.append("    - %s" % _yq(r))
    L += ["", "narrative:"]
    L.append("  headline: %s" % _yq(d.get("headline")))
    comp = d.get("comp") or {}
    if comp.get("region") and (comp.get("target") or comp.get("min")):
        L += ["", "compensation:", "  by_region:", "    %s:" % comp["region"]]
        if comp.get("target"):
            L.append("      target_range: %s" % _yq(comp["target"]))
        if comp.get("min"):
            L.append("      minimum: %s" % _yq(comp["min"]))
    L += ["", "location:"]
    L.append("  country: %s" % _yq(d.get("country")))
    L.append("  city: %s" % _yq(d.get("city")))
    L.append("  visa_status: %s" % _yq(d.get("work_auth")))
    with open(os.path.join(CONFIG_DIR, "profile.yml"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


_PORTALS_NEG = ["Junior", "Intern", "Internship", "Graduate", "Backend", "Back End",
                "Embedded", "Firmware", "QA", "Blockchain", "Crypto"]


def _write_portals_yaml(titles, companies):
    """Emit a valid config/portals.yml: user's target titles as the positive filter, a sensible
    negative list, permissive location filter, and the picked starter companies."""
    titles = [t.strip() for t in (titles or []) if t.strip()] or ["Software Engineer"]
    L = ["# Generated by the Huntbench setup wizard. Grow tracked_companies over time.", ""]
    L += ["location_filter:", "  always_allow:", "    - \"Remote\"", "  allow:",
          "    - \"Remote\"", "  # (add your cities/countries here)", ""]
    L += ["title_filter:", "  positive:"]
    for t in titles:
        L.append("    - %s" % _yq(t))
    L += ["  negative:"]
    for n in _PORTALS_NEG:
        L.append("    - %s" % _yq(n))
    L += ["", "tracked_companies:"]
    for c in (companies or []):
        name = (c.get("name") or "").strip()
        url = (c.get("careers_url") or "").strip()
        prov = (c.get("provider") or "").strip()
        if not (name and url):
            continue
        L.append("  - name: %s" % _yq(name))
        L.append("    careers_url: %s" % url)
        if prov:
            L.append("    provider: %s" % prov)
        if prov == "greenhouse":
            slug = url.rstrip("/").split("/")[-1]
            L.append("    api: https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug)
        L.append("    enabled: true")
    with open(os.path.join(CONFIG_DIR, "portals.yml"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# Starter companies offered in the onboarding "targets" step.
STARTER_COMPANIES = [
    {"name": "Vercel", "careers_url": "https://job-boards.greenhouse.io/vercel", "provider": "greenhouse"},
    {"name": "Linear", "careers_url": "https://jobs.ashbyhq.com/linear", "provider": "ashby"},
    {"name": "Supabase", "careers_url": "https://jobs.ashbyhq.com/supabase", "provider": "ashby"},
    {"name": "Stripe", "careers_url": "https://job-boards.greenhouse.io/stripe", "provider": "greenhouse"},
    {"name": "Figma", "careers_url": "https://job-boards.greenhouse.io/figma", "provider": "greenhouse"},
    {"name": "Ramp", "careers_url": "https://jobs.ashbyhq.com/ramp", "provider": "ashby"},
    {"name": "Notion", "careers_url": "https://jobs.ashbyhq.com/notion", "provider": "ashby"},
    {"name": "Replit", "careers_url": "https://jobs.ashbyhq.com/replit", "provider": "ashby"},
    {"name": "Cloudflare", "careers_url": "https://job-boards.greenhouse.io/cloudflare", "provider": "greenhouse"},
    {"name": "Airbnb", "careers_url": "https://job-boards.greenhouse.io/airbnb", "provider": "greenhouse"},
    {"name": "Spotify", "careers_url": "https://jobs.lever.co/spotify", "provider": "lever"},
    {"name": "GitLab", "careers_url": "https://job-boards.greenhouse.io/gitlab", "provider": "greenhouse"},
]


def meta_payload():
    db = jobsdb.load_db()
    upc = sum(1 for rec in db for a in (rec.get("activity") or [])
              if a.get("kind") == "interview" and (a.get("date") or "") >= jobsdb.TODAY)
    return {
        "upcoming_interviews": upc,
        "statuses": jobsdb.STATUSES, "regions": jobsdb.REGIONS,
        "work_modes": jobsdb.WORK_MODES, "sorts": dashboard.SORTS,
        "region_label": jobsdb.REGION_LABEL,
        "status_abbr": dashboard.STATUS_ABBR, "region_abbr": dashboard.REGION_ABBR,
        "status_color": dashboard._STATUS_COLOR, "region_color": dashboard._REGION_COLOR,
        "funnel": jobsdb.funnel_counts(db), "region_counts": jobsdb.region_counts(db),
        "fit_counts": jobsdb.fit_counts(db), "total": len(db),
    }


# ---- HTTP handler ------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            return {}

    # -- GET --
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                with open(HTML_PATH, "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/status":
                return self._send(200, status_payload())
            if path == "/api/setup/starter-companies":
                return self._send(200, {"companies": STARTER_COMPANIES})
            if path == "/api/setup/cv-template":
                ex = os.path.join(CONFIG_DIR, "master-cv.example.md")
                tpl = open(ex, encoding="utf-8").read() if os.path.exists(ex) else ""
                return self._send(200, {"template": tpl})
            if path == "/api/meta":
                return self._send(200, meta_payload())
            if path == "/api/interviews":
                return self._send(200, interviews_payload())
            if path == "/api/activity":
                return self._send(200, activity_payload((q.get("kind") or [None])[0]))
            if path == "/api/sync-request":
                if os.path.exists(SYNC_REQ):
                    try:
                        with open(SYNC_REQ, encoding="utf-8") as f:
                            return self._send(200, {"pending": True, **json.load(f)})
                    except (ValueError, OSError):
                        pass
                return self._send(200, {"pending": False})
            if path == "/api/jobs":
                db = jobsdb.load_db()
                rows = dashboard.build_view(
                    db, (q.get("region") or [""])[0], (q.get("status") or [""])[0],
                    (q.get("q") or [""])[0], (q.get("sort") or ["fit"])[0])
                return self._send(200, {"jobs": [row(r) for r in rows], "count": len(rows)})
            if path.startswith("/api/job/"):
                parts = path[len("/api/job/"):].split("/")
                jid = urllib.parse.unquote(parts[0])
                rec = jobsdb.index_by_id(jobsdb.load_db()).get(jid)
                if not rec:
                    return self._send(404, {"error": "not found"})
                if len(parts) >= 2 and parts[1] == "artifacts":
                    return self._send(200, artifacts_payload(rec))
                return self._send(200, {"record": rec})
            if path.startswith("/api/tasks/"):
                with _TLOCK:
                    t = dict(_TASKS.get(path[len("/api/tasks/"):], {}))
                return self._send(200 if t else 404, t or {"error": "no task"})
            if path == "/api/file":
                return self._serve_file((q.get("path") or [""])[0])
            return self._send(404, {"error": "unknown route"})
        except Exception as e:  # noqa
            return self._send(500, {"error": str(e)})

    # -- POST --
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path.startswith("/api/job/") and path.endswith("/update"):
                jid = urllib.parse.unquote(path[len("/api/job/"):-len("/update")])
                db = jobsdb.load_db()
                rec = apply_update(db, jid, self._json_body())
                if not rec:
                    return self._send(404, {"error": "not found"})
                jobsdb.save_db(db)
                return self._send(200, {"record": rec})
            if path.startswith("/api/job/") and path.endswith("/promote"):
                jid = urllib.parse.unquote(path[len("/api/job/"):-len("/promote")])
                body = self._json_body()
                db = jobsdb.load_db()
                rec = jobsdb.index_by_id(db).get(jid)
                if not rec:
                    return self._send(404, {"error": "not found"})
                slug = (body.get("slug") or "").strip() or dashboard.slugify(rec)
                relpath, fm = jobsdb.build_opportunity_scaffold(rec, slug, body.get("status"))
                jobsdb.save_db(db)
                abspath = os.path.join(jobsdb.HERE, relpath)
                created = False
                if not os.path.exists(abspath):
                    os.makedirs(os.path.dirname(abspath), exist_ok=True)
                    with open(abspath, "w", encoding="utf-8") as f:
                        f.write(fm)
                    created = True
                return self._send(200, {"path": relpath, "created": created, "record": rec})
            if path.startswith("/api/job/") and path.endswith("/activity"):
                jid = urllib.parse.unquote(path[len("/api/job/"):-len("/activity")])
                body = self._json_body()
                db = jobsdb.load_db()
                rec = jobsdb.index_by_id(db).get(jid)
                if not rec:
                    return self._send(404, {"error": "not found"})
                jobsdb.add_activity(rec, {k: body.get(k) for k in
                    ("date", "kind", "title", "detail", "contact", "link", "thread_id", "source")})
                st = body.get("status")
                if st and st in jobsdb.STATUSES:
                    rec["status"] = st
                rec["updated"] = jobsdb.TODAY
                jobsdb.save_db(db)
                return self._send(200, {"record": rec})
            if path == "/api/setup/profile":
                os.makedirs(CONFIG_DIR, exist_ok=True)
                _write_profile_yaml(self._json_body())
                return self._send(200, status_payload())
            if path == "/api/setup/master-cv":
                os.makedirs(CONFIG_DIR, exist_ok=True)
                md = (self._json_body() or {}).get("markdown") or ""
                with open(os.path.join(CONFIG_DIR, "master-cv.md"), "w", encoding="utf-8") as f:
                    f.write(md)
                return self._send(200, status_payload())
            if path == "/api/setup/portals":
                os.makedirs(CONFIG_DIR, exist_ok=True)
                b = self._json_body() or {}
                _write_portals_yaml(b.get("titles"), b.get("companies"))
                return self._send(200, status_payload())
            if path == "/api/setup/finish":
                if (self._json_body() or {}).get("clear_demo"):
                    jobsdb.save_db([])
                return self._send(200, {"ok": True, **status_payload()})
            if path == "/api/tasks":
                body = self._json_body()
                if body.get("cmd") not in ALLOWED_TASK_CMDS:
                    return self._send(400, {"error": "bad or missing cmd"})
                return self._send(200, {"tid": start_task(body["cmd"], body)})
            if path == "/api/sync-request":
                at = datetime.datetime.now().isoformat(timespec="seconds")
                with open(SYNC_REQ, "w", encoding="utf-8") as f:
                    json.dump({"at": at, "note": (self._json_body() or {}).get("note", "")}, f)
                return self._send(200, {"ok": True, "at": at})
            return self._send(404, {"error": "unknown route"})
        except Exception as e:  # noqa
            return self._send(500, {"error": str(e)})

    def _serve_file(self, p):
        if not p:
            return self._send(400, {"error": "no path"})
        real = os.path.realpath(p)
        ok = any(real == os.path.realpath(r) or real.startswith(os.path.realpath(r) + os.sep)
                 for r in _FILE_ROOTS)
        if not ok:
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(real):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(real)[1].lower()
        ctype = {".pdf": "application/pdf", ".md": "text/plain; charset=utf-8",
                 ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8",
                 ".json": "application/json"}.get(ext, "application/octet-stream")
        with open(real, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         'inline; filename="%s"' % os.path.basename(real))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def run(args):
    host = getattr(args, "host", None) or "127.0.0.1"
    port = int(getattr(args, "port", None) or 8765)
    if not os.path.exists(HTML_PATH):
        print("serve: webui.html not found next to webui.py")
        return 1
    try:
        httpd = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        print("serve: could not bind %s:%d (%s). Try --port <n>." % (host, port, e))
        return 1
    url = "http://%s:%d" % (host, port)
    print("Huntbench web UI  ->  %s   (Ctrl-C to stop)" % url)
    if not getattr(args, "no_open", False):
        try:
            webbrowser.open(url)
        except Exception:  # noqa
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nserve: stopped")
    finally:
        httpd.server_close()
    return 0
