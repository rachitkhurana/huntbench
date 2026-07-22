# APPLY-RUNBOOK — how the agent fills a job application

The procedure the coding agent follows when the user says **"apply to `<id>`"**. `./jobsdb.py apply
--id <id>` only *prepares* a packet; the actual form-filling happens here in chat, using your
browser tool to drive the user's real (logged-in) browser.

> ## THE RULE — never submit without review
> Fill every field, upload the CV, paste the answers, screenshot the completed form — then **STOP**.
> The user reviews and clicks Submit themselves. **Never click Submit / Apply / Send** unless the
> user explicitly says "submit it".

## Steps
1. **Prep the packet** if it doesn't exist: `./jobsdb.py apply --id <id>` writes
   `output/<company>-<id>/apply-packet.json` (a tailored CV PDF + profile-mapped form `fields` +
   drafted `custom_answers` + a `gaps` list of things only the user can answer).
2. **Read the packet** — note `url`, `provider`, `resume_pdf`, `fields`, `custom_answers`, `gaps`.
3. **Open the posting** (`url`) in the user's browser and click Apply.
4. **Fill by provider:**
   - Standard ATS (Greenhouse / Ashby / Lever / Workable): map `fields` → name, email, phone,
     location, LinkedIn, portfolio; upload `resume_pdf`; paste each `custom_answers[question]` into
     the matching textarea (match by the form's question text).
   - LinkedIn "Easy Apply" (if the user uses it): step through the modal from `fields`/`answers`.
5. **Gaps — ask, never invent.** For anything in `gaps` (gender/race/veteran/disability, pronouns,
   sponsorship) that the form *requires*, ask the user or offer a safe default ("Decline to
   self-identify"). Never fabricate a legal/diversity attestation. Sponsorship: derive from the
   profile's work-authorization.
6. **Screenshot + STOP.** Screenshot the completed form and tell the user exactly what's filled and
   what still needs them. "Ready — review and click Submit when happy."
7. **After the user submits** (or tells you to submit): `./jobsdb.py update --id <id> --status
   applied --notes "applied <date> via <provider>"`.

## Notes
- `custom_answers` may be empty if `apply` ran where the `claude` CLI wasn't available — just draft
  the answers yourself from `apply-packet.md` before filling.
- Never type anything the user marked `[STEALTH]` into a form.
- One application at a time; keep the browser visible so the user can watch.
