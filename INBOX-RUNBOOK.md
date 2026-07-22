# INBOX-RUNBOOK — syncing the inbox into the pipeline

The procedure the coding agent follows when the user says **"sync inbox"** (or clicks the **✉ Sync
inbox** button in the dashboard, which drops a `.sync-request.json` signal). If the user applies to
jobs from one email account, that inbox is the source of truth for pipeline status. This runs in
chat because the email tools are agent-side, not reachable by the local server; the results land in
`jobs.ndjson` and show up in the dashboard's **Inbox** view.

> ## THE RULES
> - **Read-only.** Never send, reply, archive, label, or delete anything.
> - **Propose, then confirm.** Always show the user a table of proposed changes and wait for a yes
>   before writing. Never auto-apply.
> - Only real mail → real records. If a match is uncertain, mark it "unmatched" and ask.

## Steps
1. **Read the user's job mail** with whatever email tool you have (a Gmail/Outlook MCP, etc.). Search
   the last ~30–45 days: application/interview/"next steps"/"unfortunately"/offer, plus ATS senders
   (greenhouse.io, ashbyhq.com, lever.co, workable.com, smartrecruiters.com, myworkday.com) and the
   company names in the DB (`./jobsdb.py list --status applied`).
2. **Match each thread to a job** by company / ATS domain / title. Keep the thread id for a deep-link.
3. For each matched thread, prepare:
   - An **`email` activity** for every meaningful message: `kind:email`, `title`=subject,
     `contact`=from, `detail`=snippet, `date`=message date, `link`=a deep-link to the thread
     (e.g. `https://mail.google.com/mail/u/0/#all/<threadId>` for Gmail). Dedupe by thread+date.
   - A **proposed status transition**: received→`applied`; scheduling→`screening`; scheduled-with-a-
     date→an `interview` activity (date, stage, interviewer, join link) + status `interviewing`;
     rejection→`closed`; offer→`offer`. Flag any **action-needed** mail (e.g. "confirm your identity").
4. **Show the proposal table** (email → job → activity/status → thread link) and wait for the user's OK.
5. **On confirmation**, apply per job:
   ```
   ./jobsdb.py activity --id <id> --kind email --date <d> --title "<subject>" \
       --contact "<from>" --link "<thread url>" --thread-id <id> --source gmail
   ./jobsdb.py activity --id <id> --kind interview --date <d> --title "Screen call" \
       --contact "<interviewer>" --link "<join url>" --source gmail --status interviewing
   ./jobsdb.py update --id <id> --status applied     # plain status move, no interview
   ```
   Then, if the dashboard button triggered this, delete `.sync-request.json` so its pending dot clears.

## Notes
- If a thread has no matching job in the DB but represents a real application, offer to `add` it.
- Calendar (if the user has a calendar tool) can also get the scheduled interview as an event.
