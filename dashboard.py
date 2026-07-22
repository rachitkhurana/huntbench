#!/usr/bin/env python3
"""dashboard - interactive split-pane TUI for the Huntbench job database.

Launch:              ./jobsdb.py dashboard     (or)   ./dashboard.py
Headless self-test:  ./jobsdb.py dashboard --selftest   (or)   ./dashboard.py --selftest

Pure stdlib (curses + webbrowser). Reuses jobsdb.py as the data layer; every write goes
through jobsdb.save_db() so jobs.ndjson stays the single source of truth. The generated
markdown views are refreshed with the `R` key (or `./jobsdb.py render`).

Keys — list:   j/k or up/down move · PgUp/PgDn · g/G ends · Enter focus detail
               / search · r region filter · f status filter · o sort
               s status · n note · t fit · O open URL · p promote · R re-render · ? help · q quit
Keys — detail: j/k or up/down scroll JD · Esc back · (s/n/t/O/p also work) · q quit
"""

import contextlib
import curses
import io
import os
import re
import subprocess
import sys
import textwrap
import types
import webbrowser

import jobsdb

ROOT = jobsdb.HERE  # repo root (scaffolds land under output/)

STATUS_ABBR = {
    "new": "new", "shortlisted": "shl", "skip": "skp", "applied": "app",
    "screening": "scr", "interviewing": "int", "offer": "off",
    "closed": "cls", "passed": "pss",
}
REGION_ABBR = {
    "uae": "uae", "remote-emea": "rem", "europe": "eu", "australia": "au",
    "india": "in", "other": "oth",
}
SORTS = ["fit", "company", "status"]

_ASCII = {"—": "-", "–": "-", "·": "-", "…": "...", "→": "->",
          "’": "'", "“": '"', "”": '"', "•": "*", "≥": ">=",
          "≤": "<=", "↑": "^", "↓": "v"}


# ---- pure helpers (no curses; exercised by selftest) -------------------------

def ascii_safe(s):
    """Best-effort ASCII so curses never chokes on wide/odd glyphs."""
    if s is None:
        return ""
    s = str(s)
    for k, v in _ASCII.items():
        s = s.replace(k, v)
    return s.encode("ascii", "replace").decode("ascii")


def matches_query(rec, q):
    if not q:
        return True
    q = q.lower()
    hay = " ".join([
        rec.get("company") or "", rec.get("title") or "",
        " ".join(rec.get("tags") or []), rec.get("notes") or "",
        rec.get("location") or "",
    ]).lower()
    return q in hay


def _region_rank(r):
    rb = r.get("region_bucket", "other")
    return jobsdb.REGIONS.index(rb) if rb in jobsdb.REGIONS else 99


def _status_rank(r):
    st = r.get("status", "new")
    return jobsdb.STATUSES.index(st) if st in jobsdb.STATUSES else 99


def build_view(records, region, status, query, sort_mode):
    rows = [r for r in records
            if (not region or r.get("region_bucket") == region)
            and (not status or r.get("status") == status)
            and matches_query(r, query)]
    if sort_mode == "company":
        rows.sort(key=lambda r: (r.get("company") or "").lower())
    elif sort_mode == "status":
        rows.sort(key=lambda r: (_status_rank(r), -(r.get("fit_score") or 0)))
    else:  # fit
        rows.sort(key=lambda r: (-(r.get("fit_score") or 0), _region_rank(r),
                                 (r.get("company") or "").lower()))
    return rows


def detail_lines(rec, width):
    """List of (text, style) lines for the detail pane, wrapped to `width`."""
    W = max(20, width)
    out = []

    def add(text="", style="normal"):
        text = ascii_safe(text)
        if text == "":
            out.append(("", style))
            return
        for seg in (textwrap.wrap(text, W) or [""]):
            out.append((seg, style))

    def field(label, val):
        if val:
            add("%s: %s" % (label, val), "dim")

    add(rec.get("company") or "(no company)", "title")
    add(rec.get("title") or "", "title")
    add()
    add("fit %s  |  %s  |  %s  |  %s" % (
        rec.get("fit_score"), rec.get("status"),
        jobsdb.REGION_LABEL.get(rec.get("region_bucket", ""), rec.get("region_bucket", "")),
        rec.get("work_mode")), "meta")
    field("Location", rec.get("location"))
    field("Salary", rec.get("salary"))
    field("Experience", rec.get("experience_tag"))
    field("Posted", rec.get("date_posted"))
    if rec.get("live"):
        field("Live", "%s (%s)" % (rec.get("live"), rec.get("live_checked", "")))
    field("Why (fit)", rec.get("fit_reason"))
    enr = rec.get("enrichment") or {}
    field("Skills", ", ".join(enr.get("skills") or []) or None)
    field("Seniority", enr.get("seniority"))
    field("Type", enr.get("employment_type"))
    field("Applicants", enr.get("num_applicants"))
    field("Tags", ", ".join(rec.get("tags") or []) or None)
    if rec.get("notes"):
        add()
        add("Notes:", "hd")
        add(rec.get("notes"))
    field("Promoted to", rec.get("promoted_to"))
    field("URL", rec.get("url"))
    if enr.get("description"):
        add()
        add("Job description:", "hd")
        add(enr.get("description"))
    if not rec.get("enriched"):
        add()
        add("(not yet enriched - run: ./jobsdb.py enrich)", "dim")
    return out


def slugify(rec):
    base = ("%s %s" % (rec.get("company") or "", rec.get("title") or "")).lower()
    s = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return s[:60] or ("job-" + (rec.get("id") or "x"))


# ---- curses primitives -------------------------------------------------------

C = {}


def _init_colors():
    names = {"green": curses.COLOR_GREEN, "cyan": curses.COLOR_CYAN,
             "yellow": curses.COLOR_YELLOW, "white": curses.COLOR_WHITE,
             "magenta": curses.COLOR_MAGENTA, "blue": curses.COLOR_BLUE,
             "red": curses.COLOR_RED}
    C.clear()
    if not curses.has_colors():
        for k in names:
            C[k] = 0
    else:
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for i, (name, color) in enumerate(names.items(), start=1):
            curses.init_pair(i, color, bg)
            C[name] = curses.color_pair(i)
    C["bar"] = curses.A_REVERSE
    C["dim"] = curses.A_DIM
    # semantic aliases used by the detail pane
    C["title"] = C["cyan"]
    C["meta"] = C["green"]
    C["hd"] = C["yellow"]
    C["msg"] = C["green"]


# per-column colour maps for the list
_STATUS_COLOR = {
    "new": "white", "shortlisted": "green", "skip": "dim", "applied": "cyan",
    "screening": "yellow", "interviewing": "magenta", "offer": "green",
    "closed": "red", "passed": "red",
}
_REGION_COLOR = {
    "uae": "yellow", "remote-emea": "magenta", "europe": "cyan",
    "australia": "blue", "india": "red", "other": "white",
}


def _fit_attr(fit):
    return {5: C["green"] | curses.A_BOLD, 4: C["cyan"],
            3: C["yellow"]}.get(fit or 0, C["dim"])


def _status_attr(status):
    name = _STATUS_COLOR.get(status, "white")
    if name == "dim":
        return C["dim"]
    attr = C.get(name, 0)
    if status in ("shortlisted", "offer"):
        attr |= curses.A_BOLD
    return attr


def _region_attr(region):
    return C.get(_REGION_COLOR.get(region, "white"), 0)


def _put(win, y, x, text, attr=0, maxx=None):
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        limit = (maxx if maxx is not None else w) - x
        if limit <= 0:
            return
        win.addnstr(y, x, ascii_safe(text), max(0, limit), attr)
    except curses.error:
        pass


def _detail_style(style):
    return {"title": C["title"] | curses.A_BOLD, "meta": C["meta"],
            "hd": C["hd"] | curses.A_BOLD, "dim": C["dim"]}.get(style, 0)


# ---- popups ------------------------------------------------------------------

def popup_input(stdscr, label, initial=""):
    rows, cols = stdscr.getmaxyx()
    w = min(cols - 4, max(44, len(label) + 12))
    win = curses.newwin(3, w, max(0, rows // 2 - 1), max(0, (cols - w) // 2))
    win.keypad(True)
    buf = list(initial)
    curses.curs_set(1)
    try:
        while True:
            win.erase()
            win.box()
            _put(win, 0, 2, " %s " % label, curses.A_BOLD)
            inner = w - 4
            s = "".join(buf)
            shown = s[-inner:]
            _put(win, 1, 2, shown.ljust(inner))
            try:
                win.move(1, 2 + min(len(s), inner))
            except curses.error:
                pass
            win.refresh()
            ch = win.getch()
            if ch == 27:            # Esc
                return None
            if ch in (10, 13, curses.KEY_ENTER):
                return "".join(buf).strip()
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if buf:
                    buf.pop()
            elif 32 <= ch < 127:
                buf.append(chr(ch))
    finally:
        curses.curs_set(0)


def popup_menu(stdscr, title, options):
    rows, cols = stdscr.getmaxyx()
    h = min(len(options) + 2, rows - 2)
    w = min(cols - 4, max(len(title) + 6, max((len(o) for o in options), default=8) + 6))
    win = curses.newwin(h, w, max(0, (rows - h) // 2), max(0, (cols - w) // 2))
    win.keypad(True)
    sel = 0
    while True:
        win.erase()
        win.box()
        _put(win, 0, 2, " %s " % title, curses.A_BOLD)
        for i, o in enumerate(options[:h - 2]):
            _put(win, 1 + i, 2, o.ljust(w - 4),
                 curses.A_REVERSE if i == sel else 0)
        win.refresh()
        ch = win.getch()
        if ch in (27, ord("q")):
            return None
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(options)
        elif ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(options)
        elif ch in (10, 13, curses.KEY_ENTER):
            return sel


def popup_help(stdscr):
    lines = [
        "MOVE    j/k or arrows, PgUp/PgDn, g/G ends",
        "OPEN    Enter -> focus detail (j/k scroll JD), Esc back",
        "FIND    /  search   r region filter   f status filter   o sort",
        "ACT     s status   n note   t fit(1-5)   O open URL   p promote",
        "TOOLS   S scan ATS portals   L liveness (selected)",
        "MAKE    V cv+letter PDF (offline)   A AI-tailor CV to JD via Claude (+PDF)",
        "APPLY   X build apply packet, then say 'apply to <id>' in chat to fill the form",
        "SYS     R re-render markdown views    ? this help    q quit",
        "",
        "Edits save to jobs.ndjson immediately. Press any key.",
    ]
    rows, cols = stdscr.getmaxyx()
    w = min(cols - 4, max(len(x) for x in lines) + 4)
    h = len(lines) + 2
    win = curses.newwin(h, w, max(0, (rows - h) // 2), max(0, (cols - w) // 2))
    win.box()
    _put(win, 0, 2, " Keys ", curses.A_BOLD)
    for i, ln in enumerate(lines):
        _put(win, 1 + i, 2, ln)
    win.refresh()
    win.getch()


# ---- state -------------------------------------------------------------------

class State:
    def __init__(self):
        self.region = None
        self.status = None
        self.query = ""
        self.sort = "fit"
        self.sel = 0
        self.sel_id = None
        self.top = 0
        self.focus = "list"
        self.dscroll = 0
        self.msg = ""


def _save(records, rec):
    rec["updated"] = jobsdb.TODAY
    jobsdb.save_db(records)


def _cycle(current, options):
    i = options.index(current) if current in options else -1
    return options[(i + 1) % len(options)]


# ---- draw --------------------------------------------------------------------

def draw(stdscr, records, view, st):
    stdscr.erase()
    rows, cols = stdscr.getmaxyx()
    if cols < 40 or rows < 8:
        _put(stdscr, 0, 0, "Terminal too small - need at least 40x8.")
        stdscr.refresh()
        return None
    left_w = min(46, max(24, int(cols * 0.42)))
    right_x = left_w + 1
    right_w = cols - right_x
    body_h = rows - 2

    # clamp selection + keep it on-screen
    if view:
        st.sel = max(0, min(st.sel, len(view) - 1))
    else:
        st.sel = 0
    if st.sel < st.top:
        st.top = st.sel
    elif st.sel >= st.top + body_h:
        st.top = st.sel - body_h + 1
    st.top = max(0, min(st.top, max(0, len(view) - body_h)))

    # ---- headers: the ACTIVE pane gets a bright bar, the idle pane is dimmed ----
    list_active = st.focus == "list"
    active_hdr = curses.A_REVERSE | curses.A_BOLD
    idle_hdr = C["dim"]
    filt = []
    if st.region:
        filt.append("region=%s" % st.region)
    if st.status:
        filt.append("status=%s" % st.status)
    if st.query:
        filt.append("/%s" % st.query)
    filt.append("sort=%s" % st.sort)
    lhdr = " %s LIST  %d/%d  %s " % (">" if list_active else " ",
                                    len(view), len(records), "  ".join(filt))
    _put(stdscr, 0, 0, lhdr.ljust(left_w), active_hdr if list_active else idle_hdr, maxx=left_w)
    rhdr = (" > DETAIL   j/k scroll - Esc back " if not list_active
            else "   detail   (Enter to scroll) ")
    _put(stdscr, 0, right_x, rhdr.ljust(right_w),
         active_hdr if not list_active else idle_hdr, maxx=cols)

    # divider — brighten toward the active pane
    div_attr = (C["cyan"] | curses.A_BOLD) if not list_active else C["dim"]
    for y in range(1, rows - 1):
        _put(stdscr, y, left_w, "|", div_attr)

    # list
    if not view:
        _put(stdscr, 2, 1, "no jobs match filters", C["dim"], maxx=left_w)
    for i in range(st.top, min(len(view), st.top + body_h)):
        r = view[i]
        y = 1 + (i - st.top)
        fit = r.get("fit_score") or 0
        stt = r.get("status")
        reg = r.get("region_bucket")
        st_ab = STATUS_ABBR.get(stt, "?")
        rg_ab = REGION_ABBR.get(reg, "?")
        comp = ascii_safe(r.get("company") or "")
        title = ascii_safe(r.get("title") or "")
        if i == st.sel:
            row = "%s %-3s %-3s %s" % (fit, st_ab, rg_ab, comp + " - " + title)
            # bright block when the list is active; a softer reverse when you're in the detail pane
            sel_attr = (curses.A_REVERSE | curses.A_BOLD) if list_active else curses.A_REVERSE
            _put(stdscr, y, 0, row.ljust(left_w), sel_attr, maxx=left_w)
            continue
        # columns: fit(x0) status(x2) region(x6) company/title(x10) - each its own colour
        _put(stdscr, y, 0, str(fit)[:1], _fit_attr(fit), maxx=left_w)
        _put(stdscr, y, 2, "%-3s" % st_ab, _status_attr(stt), maxx=left_w)
        _put(stdscr, y, 6, "%-3s" % rg_ab, _region_attr(reg), maxx=left_w)
        nx = 10
        _put(stdscr, y, nx, comp, C["white"] | curses.A_BOLD, maxx=left_w)
        nx += len(comp)
        if nx < left_w:
            _put(stdscr, y, nx, " - ", C["dim"], maxx=left_w)
            nx += 3
        if nx < left_w:
            _put(stdscr, y, nx, title, C["dim"], maxx=left_w)

    # detail
    cur = view[st.sel] if view else None
    if cur:
        dl = detail_lines(cur, right_w - 1)
        st.dscroll = max(0, min(st.dscroll, max(0, len(dl) - 1)))
        for j in range(st.dscroll, min(len(dl), st.dscroll + body_h)):
            text, style = dl[j]
            _put(stdscr, 1 + (j - st.dscroll), right_x + 1, text,
                 _detail_style(style), maxx=cols)
        if len(dl) > body_h:
            _put(stdscr, rows - 2, cols - 6,
                 "%d%%" % int(100 * (st.dscroll + body_h) / max(1, len(dl))), C["dim"])

    # footer
    if st.msg:
        _put(stdscr, rows - 1, 0, (" " + st.msg).ljust(cols),
             C["msg"] | curses.A_BOLD | curses.A_REVERSE, maxx=cols)
    else:
        if st.focus == "detail":
            bar = " Esc back  j/k scroll  s status  n note  O open  p promote  V cv  A ai-cv  q quit "
        else:
            bar = " Enter detail  / search  s status  p promote  V cv  A ai-tailor  X apply  ? help  q quit "
        _put(stdscr, rows - 1, 0, bar.ljust(cols), C["bar"], maxx=cols)
    stdscr.refresh()
    return body_h


# ---- actions -----------------------------------------------------------------

def act_status(stdscr, records, rec, st):
    idx = popup_menu(stdscr, "Set status", jobsdb.STATUSES)
    if idx is not None:
        rec["status"] = jobsdb.STATUSES[idx]
        _save(records, rec)
        st.msg = "status -> %s" % rec["status"]


def act_note(stdscr, records, rec, st):
    val = popup_input(stdscr, "Note (Esc cancel)", rec.get("notes") or "")
    if val is not None:
        rec["notes"] = val
        _save(records, rec)
        st.msg = "note saved"


def act_fit(stdscr, records, rec, st):
    val = popup_input(stdscr, "Fit 1-5", str(rec.get("fit_score") or ""))
    if val:
        try:
            f = max(1, min(5, int(val)))
        except ValueError:
            st.msg = "fit must be a number 1-5"
            return
        rec["fit_score"] = f
        _save(records, rec)
        st.msg = "fit -> %d" % f


def act_open(rec, st):
    url = rec.get("url")
    if url:
        webbrowser.open(url)
        st.msg = "opened URL in browser"
    else:
        st.msg = "no URL on this record"


def act_promote(stdscr, records, rec, st):
    slug = popup_input(stdscr, "Promote - slug", slugify(rec))
    if not slug:
        return
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    path, text = jobsdb.build_opportunity_scaffold(rec, slug)
    _save(records, rec)
    full = os.path.join(ROOT, path)
    if os.path.exists(full):
        st.msg = "promoted (folder already existed): %s" % path
        return
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        st.msg = "promoted -> created %s" % path
    except OSError as e:
        st.msg = "promote: could not write file (%s)" % e


def act_rerender(records, st):
    jobsdb.write_note("overview.md", jobsdb.render_index(records))
    jobsdb.write_note("pipeline.md", jobsdb.render_pipeline(records))
    jobsdb.write_note("shortlist.md", jobsdb.render_shortlist(records))
    st.msg = "re-rendered markdown views"


# ---- main loop ---------------------------------------------------------------

def _main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    _init_colors()
    records = jobsdb.load_db()
    st = State()

    while True:
        view = build_view(records, st.region, st.status, st.query, st.sort)
        # keep the selection anchored to the same record across filter/sort changes
        if st.sel_id is not None:
            ids = [r.get("id") for r in view]
            if st.sel_id in ids:
                st.sel = ids.index(st.sel_id)
        if view:
            st.sel = max(0, min(st.sel, len(view) - 1))
            st.sel_id = view[st.sel].get("id")
        else:
            st.sel_id = None

        body_h = draw(stdscr, records, view, st)
        if body_h is None:              # too small; wait for resize
            if stdscr.getch() == ord("q"):
                break
            continue

        cur = view[st.sel] if view else None
        ch = stdscr.getch()
        st.msg = ""

        if ch == curses.KEY_RESIZE:
            continue
        if ch == ord("q"):
            break
        if ch == ord("?"):
            popup_help(stdscr)
            continue

        # global actions (work in either focus, need a current record)
        if cur is not None and ch == ord("s"):
            act_status(stdscr, records, cur, st); st.sel_id = cur.get("id"); continue
        if cur is not None and ch == ord("n"):
            act_note(stdscr, records, cur, st); continue
        if cur is not None and ch == ord("t"):
            act_fit(stdscr, records, cur, st); continue
        if cur is not None and ch == ord("O"):
            act_open(cur, st); continue
        if cur is not None and ch == ord("p"):
            act_promote(stdscr, records, cur, st); continue
        if ch == ord("R"):
            act_rerender(records, st); continue
        if ch == ord("S"):                       # scan ATS portals into the DB
            st.msg = "scanning ATS portals... (~10s)"
            draw(stdscr, records, view, st)
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    import scan
                    scan.run(dry_run=False)
                records = jobsdb.load_db()
                lines = [l for l in buf.getvalue().splitlines() if l.startswith("scan:")]
                st.msg = lines[-1] if lines else "scan complete"
            except Exception as e:               # noqa
                st.msg = "scan failed: %s" % e
            continue
        if cur is not None and ch == ord("L"):   # liveness check of selected job
            st.msg = "checking liveness..."
            draw(stdscr, records, view, st)
            try:
                import liveness
                verdict, reason = liveness.classify(cur.get("url"))
                cur["live"] = verdict
                cur["live_checked"] = jobsdb.TODAY
                cur["updated"] = jobsdb.TODAY
                jobsdb.save_db(records)
                st.msg = "liveness: %s (%s)" % (verdict, reason)
            except Exception as e:               # noqa
                st.msg = "liveness failed: %s" % e
            continue
        if cur is not None and ch == ord("V"):   # generate CV + cover letter (HTML+PDF+TXT)
            try:
                import cvgen
                outdir = cvgen._outdir(cur, None)
                subprocess.Popen(
                    [sys.executable, os.path.join(jobsdb.HERE, "jobsdb.py"),
                     "cv", "--id", cur["id"]],
                    cwd=jobsdb.HERE, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)       # detached; survives dashboard quit
                st.msg = "CV+letter (HTML+PDF+TXT) rendering in background -> %s (~40s)" % outdir
            except Exception as e:               # noqa
                st.msg = "cv failed to launch: %s" % e
            continue
        if cur is not None and ch == ord("A"):   # AI-tailor the CV to the JD (via claude), then render
            try:
                import cvgen
                outdir = cvgen._outdir(cur, None)
                subprocess.Popen(
                    [sys.executable, os.path.join(jobsdb.HERE, "jobsdb.py"),
                     "tailor", "--id", cur["id"]],
                    cwd=jobsdb.HERE, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                st.msg = "AI-tailoring CV via Claude in background -> %s (~60-120s)" % outdir
            except Exception as e:               # noqa
                st.msg = "ai-tailor failed to launch: %s" % e
            continue
        if cur is not None and ch == ord("X"):   # build the apply packet (CV + fields + answers)
            try:
                import cvgen
                outdir = cvgen._outdir(cur, None)
                subprocess.Popen(
                    [sys.executable, os.path.join(jobsdb.HERE, "jobsdb.py"),
                     "apply", "--id", cur["id"]],
                    cwd=jobsdb.HERE, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                st.msg = ("Prepping apply packet -> %s. Then say 'apply to %s' in chat "
                          "(Claude fills the form, stops before submit)." % (outdir, cur["id"]))
            except Exception as e:               # noqa
                st.msg = "apply-prep failed to launch: %s" % e
            continue

        if st.focus == "list":
            if ch in (curses.KEY_DOWN, ord("j")):
                st.sel += 1
            elif ch in (curses.KEY_UP, ord("k")):
                st.sel -= 1
            elif ch == curses.KEY_NPAGE:
                st.sel += body_h
            elif ch == curses.KEY_PPAGE:
                st.sel -= body_h
            elif ch == ord("g"):
                st.sel = 0
            elif ch == ord("G"):
                st.sel = len(view) - 1
            elif ch in (10, 13, curses.KEY_ENTER):
                st.focus = "detail"; st.dscroll = 0
            elif ch == ord("/"):
                q = popup_input(stdscr, "Search (blank clears)", st.query)
                if q is not None:
                    st.query = q; st.sel = 0
            elif ch == ord("r"):
                st.region = _cycle(st.region, [None] + jobsdb.REGIONS)
            elif ch == ord("f"):
                st.status = _cycle(st.status, [None] + jobsdb.STATUSES)
            elif ch == ord("o"):
                st.sort = _cycle(st.sort, SORTS)
            if view:
                st.sel = max(0, min(st.sel, len(view) - 1))
                st.sel_id = view[st.sel].get("id")
        else:  # detail focus
            if ch == 27:
                st.focus = "list"
            elif ch in (curses.KEY_DOWN, ord("j")):
                st.dscroll += 1
            elif ch in (curses.KEY_UP, ord("k")):
                st.dscroll -= 1
            elif ch == curses.KEY_NPAGE:
                st.dscroll += body_h
            elif ch == curses.KEY_PPAGE:
                st.dscroll -= body_h


def run():
    if not sys.stdout.isatty():
        sys.stderr.write("dashboard: needs an interactive terminal (a TTY).\n")
        return 1
    curses.wrapper(_main)
    return 0


# ---- headless self-test ------------------------------------------------------

def selftest():
    import shutil
    import tempfile
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    recs = jobsdb.load_db()
    check("load_db returns records", len(recs) > 0)
    v = build_view(recs, None, None, "", "fit")
    check("build_view keeps all when unfiltered", len(v) == len(recs))
    check("build_view sorted by fit desc",
          all((v[i].get("fit_score") or 0) >= (v[i + 1].get("fit_score") or 0)
              for i in range(len(v) - 1)))
    check("region filter works",
          all(r.get("region_bucket") == "uae"
              for r in build_view(recs, "uae", None, "", "fit")))
    check("query filter narrows",
          len(build_view(recs, None, None, "react", "fit")) <= len(recs))
    dl = detail_lines(v[0], 50)
    check("detail_lines non-empty", len(dl) > 0)
    check("detail_lines wrapped to width", all(len(t) <= 50 for t, _ in dl))
    check("ascii_safe strips non-ascii",
          ascii_safe("a—b·c…").isascii())
    check("slugify -> ascii kebab",
          slugify({"company": "EDGE (FADA)", "title": "Sr Front-End", "id": "1"})
          == "edge-fada-sr-front-end")

    orig = jobsdb.DB_PATH
    before = os.path.getsize(orig)
    tmpdir = tempfile.mkdtemp()
    try:
        tmp = os.path.join(tmpdir, "jobs.ndjson")
        shutil.copy(orig, tmp)
        jobsdb.DB_PATH = tmp
        db = jobsdb.load_db()
        rid = db[0]["id"]
        jobsdb.index_by_id(db)[rid]["status"] = "shortlisted"
        jobsdb.save_db(db)
        check("status write persists",
              jobsdb.index_by_id(jobsdb.load_db())[rid]["status"] == "shortlisted")
        d2 = jobsdb.load_db()
        jobsdb.index_by_id(d2)[rid]["notes"] = "selftest-note"
        jobsdb.save_db(d2)
        check("note write persists",
              jobsdb.index_by_id(jobsdb.load_db())[rid]["notes"] == "selftest-note")
        d3 = jobsdb.load_db()
        jobsdb.index_by_id(d3)[rid]["fit_score"] = 2
        jobsdb.save_db(d3)
        check("fit write persists",
              jobsdb.index_by_id(jobsdb.load_db())[rid]["fit_score"] == 2)
        rec = jobsdb.index_by_id(jobsdb.load_db())[rid]
        path, text = jobsdb.build_opportunity_scaffold(rec, "selftest-slug")
        check("scaffold path", path == "output/selftest-slug/selftest-slug.md")
        check("scaffold sets promoted_to + text",
              rec["promoted_to"] == path and "Status:" in text)
    finally:
        jobsdb.DB_PATH = orig
        shutil.rmtree(tmpdir, ignore_errors=True)
    check("real jobs.ndjson untouched", os.path.getsize(orig) == before)

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("PASS" if c else "FAIL"), name)
    passed = sum(1 for _, c in checks if c)
    print("\n%s (%d/%d)" % ("ALL PASS" if ok else "FAILURES", passed, len(checks)))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(run())
