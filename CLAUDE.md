# Huntbench

This project is driven by a coding agent. **See [AGENTS.md](AGENTS.md)** for the full playbook —
how to onboard the user, discover jobs, tailor CVs, apply (stop before submit), and sync the inbox —
plus the command reference and the golden safety rules.

Quick orientation:
- `python3 jobsdb.py serve` — the local web dashboard.
- `python3 jobsdb.py doctor` — check setup.
- User data is local: `jobs.ndjson`, `config/`, `output/` (all git-ignored).
- Never submit an application or send email without the user's explicit OK; inbox is read-only.
