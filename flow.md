# Pipeline flow

## 1. Extraction (`incontact_automation/extractor.py::IncontactExtractor.extract`)

A generator driven by Selenium against the live NICE CXone/MAX agent desktop:

- Accepts the next assigned email (Accept popup / agent-state handling).
- Extracts subject, body (via the `iframe.email-body` / `aria-label="Email Body"` element —
  see the iframe-locator fix), and a synthetic `message_id`.
- `yield ExtractedEmail(...)` — **execution pauses here and control returns to the
  orchestrator.** The extractor does *not* send a reply at this point. It only resumes
  (to wait for the next Accept popup) after the orchestrator calls `send_reply(...)`
  back on it, later.

`send_reply(reply_text)` and `close()` are separate methods the extractor exposes; they
are called *by the orchestrator*, not from inside the extraction loop itself.

## 2. Orchestration (`mitchel_pipeline/orchestrator.py::PipelineOrchestrator.run`)

For each extracted email, in order:

1. `on_extracted(email)` — fires the "Extracted email" debug popup (if enabled). Preview
   only, no reply sent.
2. `classify_email(...)` → NLP result → `on_nlp(result)` — fires the "NLP output" popup.
3. `jobs = deduplicate_jobs(jobs_from_result(result, ...))`.
4. Branch:
   - **Classification errored, or no jobs produced** (not `bill_status`, or missing
     claim info) → manual-review path:
     `on_reply(MANUAL_REVIEW_REPLY)` (fires "Simulated email reply" popup) →
     `extractor.send_reply(MANUAL_REVIEW_REPLY)` (the *real* paste + Park Email) →
     move to the next email.
   - **Jobs exist** → SmartAdvisor path (see below) → only *after* every job for this
     email finishes does the orchestrator call `extractor.send_reply(last_reply)` once.

### SmartAdvisor path (per job, when jobs exist)

For each `SmartAdvisorJob` built from the NLP result:

- Optional Salesforce Site ID lookup (`SiteIdLookup.site_id_for_claim`).
- `_run_smartadvisor_job(...)` → talks to the `SmartAdvisorHelperClient` subprocess,
  which drives `smartadvisor_automation` (UI Automation against the SmartAdvisor app,
  `NoBillOnFileWorkflow`) — a different function/module entirely from email extraction.
- The helper's result (`reply_template`) becomes `reply`; `on_reply(reply)` fires the
  "Simulated email reply" popup **at this point, per job** — this is the correct place
  in the flow, not right after extraction.
- `results_workbook.append_result(job, helper_result, reply_sent=True)`.

Once all jobs for the email are done, the orchestrator sends **one** real reply —
`extractor.send_reply(last_reply)` — using the last job's reply text, which pastes it
into MAX and clicks Park Email (never Send).

## Key point

Extraction and reply-sending are decoupled on purpose: `IncontactExtractor.extract`
only produces emails; `PipelineOrchestrator` decides *what* reply text to send and
*when*, based on classification and — for `bill_status` claims — the SmartAdvisor
automation result, not on the extraction step itself.
