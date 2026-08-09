# Huntbench project guide

## What this project is

Huntbench is a local-first job-search workbench. It combines a dependency-free Python 3.9+ engine,
an NDJSON database, generated application artifacts, and two local interfaces. The software handles
repeatable mechanics; a user-controlled coding agent supplies tasks that need judgment or connected
tools. Huntbench itself does not host accounts or call an LLM service.

The key design choice is separation of powers:

- **Huntbench** stores, normalizes, scores, renders, and serves local state.
- **The coding agent** discovers, interprets, drafts, and optionally fills browser forms.
- **The user** owns factual claims and authorizes every external action.

## System map

```mermaid
flowchart TB
    User([User]) <--> Agent[Coding agent<br/>judgment + connected tools]
    User <--> Web[Local web dashboard<br/>127.0.0.1:8765]
    User <--> TUI[Terminal dashboard]

    Agent --> CLI[jobsdb.py CLI]
    Web --> API[webui.py JSON API]
    TUI --> Core[jobsdb.py core]
    CLI --> Core
    API --> Core

    Core <--> DB[(jobs.ndjson<br/>source of truth)]
    Core <--> Config[config/<br/>profile + portals + master CV]
    Core --> Features[scan · add · evaluate<br/>liveness · CV · tailor · apply]
    Features --> DB
    Features --> Output[output/<br/>CVs + letters + packets]

    ATS[ATS APIs / feeds] --> Features
    LLM[Optional claude CLI] -. tailor/evaluate/draft .-> Features
    Browser[Application website] -. fill only; stop before submit .-> Agent
    Mail[Inbox] -. read only .-> Agent
```

## Repository anatomy

| Area | Purpose | Important files |
|---|---|---|
| Command/data core | CLI routing, normalization, fit/evaluation baseline, NDJSON persistence | `jobsdb.py` |
| Configuration | Dependency-free YAML loading and candidate/search settings | `configlib.py`, `config/*.example.*` |
| Discovery | ATS/feed scanning, URL/board ingestion, liveness | `scan.py`, `addjob.py`, `liveness.py` |
| Decision support | Deterministic evaluation plus optional Claude refinement | `evaluate.py` |
| Documents/application | CV/letter rendering, truthful overrides, packet assembly | `cvgen.py`, `tailor.py`, `apply.py` |
| Interfaces | Loopback HTTP API, browser UI, terminal UI | `webui.py`, `webui.html`, `static/`, `dashboard.py` |
| Agent runbooks | Safety and operating procedures | `AGENTS.md`, `APPLY-RUNBOOK.md`, `INBOX-RUNBOOK.md`, `.agents/` |
| Verification | Unit and integration-style standard-library tests | `test_jobsdb.py`, `test_scan.py`, `test_cvgen.py`, `test_addjob.py` |

## Data flow

```mermaid
flowchart LR
    A[profile.yml + portals.yml] --> B[Discover]
    B --> C[Normalize + dedupe]
    C --> D[(jobs.ndjson)]
    D --> E[Score / evaluate / liveness]
    E --> F{User triage}
    F -->|skip| Z[Closed path]
    F -->|shortlist| G[Attach full JD]
    G --> H[Tailor CV + letter]
    H --> I[Build apply packet]
    I --> J[Fill application]
    J --> K{{User review + submit}}
    K --> L[Mark applied]
    L --> M[Read-only inbox matching]
    M --> N{{User confirms proposal}}
    N --> D
```

`jobs.ndjson` contains one JSON object per line. A record normally moves through
`new → shortlisted → applied → screening → interviewing → offer`; `skip`, `closed`, and `passed`
capture exits. `saved` is independent of pipeline status. Enrichment, evaluation, and activity are
nested on the same record so the web and terminal interfaces always reload a single current source.

## Sensitive workflow gates

```mermaid
sequenceDiagram
    actor U as User
    participant A as Coding agent
    participant H as Huntbench
    participant X as External site / inbox

    A->>H: Prepare CV, answers, and apply packet
    H-->>A: Local artifact paths + gaps
    A->>X: Fill verified application fields
    A-->>U: Screenshot and unresolved questions
    Note over A,X: STOP — no submission or terms acceptance
    U->>X: Reviews and submits (or explicitly authorizes next action)
    U->>A: Confirms submission
    A->>H: Set status=applied

    A->>X: Read job-related mail
    X-->>A: Threads (read-only)
    A-->>U: Proposed activities and status changes
    Note over A,H: STOP — no database mutation yet
    U->>A: Confirms selected proposals
    A->>H: Add activity / update status
```

## Agent-to-workflow map

```mermaid
flowchart LR
    P[Profile Steward] --> W1[Onboard]
    S[Job Scout] --> W2[Discover + enrich]
    F[Fit Analyst] --> W3[Triage recommendation]
    A[Application Writer] --> W4[Tailor + prepare]
    I[Inbox Analyst] --> W5[Mail proposal]
    L[Career Ops Lead] --> W1 & W2 & W3 & W4 & W5
    M[Huntbench Maintainer] --> Platform[Engine + UI + tests]
```

The complete responsibilities and handoff format are in [`.agents/README.md`](../.agents/README.md).

## Extension points

- Add an ATS/feed by implementing a provider adapter in `scan.py`, mapping it to normalized fields,
  and covering it in `test_scan.py`.
- Add a CLI capability in `jobsdb.py`; if exposed in the browser, add a narrowly scoped API route and
  UI call. Long-running web tasks must remain allowlisted.
- Extend the job schema through normalization defaults so old NDJSON records remain readable.
- Change CV layout in `cvgen.py`; verify text and PDF behavior without relying on invented data.
- Add a specialist agent only when it has a distinct evidence boundary or approval gate; document its
  handoff in `.agents/README.md`.

## Developer orientation

```bash
python3 jobsdb.py doctor
python3 test_jobsdb.py && python3 test_scan.py
python3 test_cvgen.py && python3 test_addjob.py
python3 jobsdb.py serve --no-open
```

Start with `jobsdb.py` for the data contract and command routing, then follow imports into a feature
module. For frontend work, begin at `webui.html` and `static/app.js`; API behavior lives in `webui.py`.
Use only example/demo records when testing. Runtime files such as `jobs.ndjson`, real `config/`, and
generated `output/` are local user data rather than source fixtures.
