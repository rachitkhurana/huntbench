# AGENTS.md — how to drive Huntbench

You are a coding agent (Claude Code, Codex, Cursor, …) helping a user run their job search with
Huntbench. Huntbench is a zero-dependency Python engine + local web dashboard; **you** do the smart
work (discovery, tailoring, applying, inbox sync) using whatever tools you have, and Huntbench
stores and serves the results. Everything runs locally from this repo with `python3 jobsdb.py …`.

## Golden rules
- **Never submit an application, send an email, or accept terms without the user's explicit OK.**
  Fill forms and draft messages, then stop for review.
- **Inbox is read-only.** When syncing email, propose status/activity changes and wait for a yes.
- **Only real facts.** Never invent skills, employers, metrics, or dates in a CV or an answer.
- Keep the user's data local. Don't push anything anywhere unless they ask.

## The commands (your API)
```
./jobsdb.py setup                      # scaffold config/ from the examples
./jobsdb.py doctor                     # check setup
./jobsdb.py serve                      # web dashboard (http://127.0.0.1:8765)
./jobsdb.py scan [--company X] [--dry-run]   # pull jobs from ATS boards in config/portals.yml
./jobsdb.py add / bulk-add --file f.ndjson   # add jobs you found elsewhere (JSON/NDJSON)
./jobsdb.py list [--region uae] [--min-fit 4] [--status new] [--json]
./jobsdb.py update --id <id> --status shortlisted   # (also --fit, --notes, --add-tag)
./jobsdb.py enrich --id <id> --attach jd.json       # attach a full JD ({"description": "..."})
./jobsdb.py cv --id <id> [--slug foo] [--no-pdf]     # render a tailored CV + cover letter
./jobsdb.py tailor --id <id>           # AI-tailor the CV to the JD (uses the `claude` CLI if present)
./jobsdb.py apply --id <id>            # build an apply packet (CV + fields + drafted answers)
./jobsdb.py activity --id <id> --kind interview --date 2026-08-15 --status interviewing
./jobsdb.py reset --yes [--demo]       # clear (or reseed demo) the database
```
A job record is one JSON line in `jobs.ndjson`: `id, company, title, location, url, status, tags,
fit_score, region_bucket, work_mode, experience_tag, salary, notes, enrichment{description,skills},
activity[]`. Statuses: `new, shortlisted, skip, applied, screening, interviewing, offer, closed, passed`.

## Workflow 1 — Onboard a new user ("set me up")
1. **Interview** them briefly: name, contact (email/phone/LinkedIn/portfolio), location + work
   authorization, target roles, seniority, must-have vs nice-to-have, comp expectations, and 3–6
   real proof points (projects with impact). Ask for a resume/LinkedIn if they have one.
2. Write **`config/profile.yml`** (see `config/profile.example.yml` for the schema) and
   **`config/master-cv.md`** (see `config/master-cv.example.md` — sections: Summary, Experience with
   `### Company — Role`, Side Projects, Skills, Education, Honours). Mark any private/unnamed work
   with a trailing `[STEALTH]` — those lines are stripped from every generated output.
3. Tune **`config/portals.yml`**: set `title_filter.positive/negative` to their target titles,
   `location_filter` to their geography, and replace `tracked_companies` with companies they care
   about (each entry: `name`, `careers_url`, `provider`, and `api` for Greenhouse).
4. `./jobsdb.py doctor` to confirm, then `./jobsdb.py reset --yes` to drop the demo data.

## Workflow 2 — Discover jobs (use whatever tools you have, degrade gracefully)
- **ATS scan (works for everyone, no creds):** `./jobsdb.py scan` — pulls openings from the boards
  in `config/portals.yml`. Grow that list as you learn their targets.
- **Web search / job boards:** if you can browse or search, find roles and `bulk-add` them as an
  NDJSON file (`{"id","company","title","location","url","tags"}` per line — use a stable id).
- **LinkedIn / other MCP tools:** if the user has a LinkedIn (or similar) MCP connected, search
  there and `bulk-add` the results; enrich the promising ones with the full JD via `enrich --attach`.
- **Manual:** paste a posting → you extract the fields → `add`.

## Workflow 3 — Triage
Open `./jobsdb.py serve` and let the user triage on the board, or drive it yourself with `list` +
`update` (status/fit/notes). Enrich the shortlisted ones with their full JD (`enrich --attach`) so
CV tailoring + answers are grounded.

## Workflow 4 — Tailor a CV
`./jobsdb.py cv --id <id>` renders from the master CV. To tailor to a JD: either run
`./jobsdb.py tailor --id <id>` (if the `claude` CLI is installed), **or** do it yourself — write a
`cv-overrides.json` into the job's `output/<company>-<id>/` folder (keys: `subtitle, summary,
experience[], skills[], projects[]`; real facts only, reorder to lead with what the JD asks) and run
`cv`. If the user saved notes on the job, honor them as steering.

## Workflow 5 — Apply (stop before submit)
1. `./jobsdb.py apply --id <id>` builds `output/<company>-<id>/apply-packet.json` (a tailored CV +
   profile-mapped form fields + drafted answers). Follow **APPLY-RUNBOOK.md**.
2. Open the posting in the user's browser (your browser tool), fill the fields from the packet,
   upload `resume_pdf`, paste the answers into matching questions.
3. For anything in `packet.gaps` (EEO/diversity/sponsorship), **ask the user** — never invent.
4. **Screenshot the filled form and STOP.** Only after the user says so, they submit; then
   `./jobsdb.py update --id <id> --status applied`.

## Workflow 6 — Sync the inbox
On "sync inbox", follow **INBOX-RUNBOOK.md**: read the user's job mail (read-only), match threads to
jobs, and propose per job an `email` activity (subject/from/snippet + a deep-link to the thread) plus
a status/interview transition. Show a proposal table; on confirm, apply with
`./jobsdb.py activity …` / `update …`. The dashboard's **Inbox** view then shows it all.

## Notes
- The web dashboard's "Scan / Sync inbox / Re-render" buttons and "Prep apply" only *prepare* work
  or *signal* you — the AI itself always runs here in chat (the server can't reach your tools).
- Scoring (`fit_score`) is a simple, tunable heuristic; adjust `config/portals.yml` title filters or
  re-score. It's a hint, not gospel.
