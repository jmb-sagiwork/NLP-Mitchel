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
     `_approve_or_stop(MANUAL_REVIEW_REPLY, ...)` → operator sees a blocking
     **Approve reply?** dialog with the reply text → `extractor.send_reply(...)` (the
     *real* paste + Park Email) → move to the next email.
   - **Jobs exist** → SmartAdvisor path (see below) → only *after* every job for this
     email finishes does the orchestrator call `extractor.send_reply(last_reply)` once.

### SmartAdvisor path (per job, when jobs exist)

For each `SmartAdvisorJob` built from the NLP result:

- Optional Salesforce Site ID lookup (`SiteIdLookup.site_id_for_claim`).
- `_run_smartadvisor_job(...)` → talks to the `SmartAdvisorHelperClient` subprocess,
  which drives `smartadvisor_automation` (UI Automation against the SmartAdvisor app,
  `NoBillOnFileWorkflow`) — a different function/module entirely from email extraction.
- The helper's result (`reply_template`) becomes `reply`; `_approve_or_stop(reply, ...)`
  fires the blocking **Approve reply?** dialog **at this point, per job** — this is the
  correct place in the flow, not right after extraction.
- `results_workbook.append_result(job, helper_result, reply_sent=True)`.

Once all jobs for the email are done, the orchestrator sends **one** real reply —
`extractor.send_reply(last_reply)` — using the last job's reply text, which pastes it
into MAX and clicks Park Email (never Send).

## 3. Approve / Decline / Sent Manually (the reply gate)

`on_reply: Callable[[str], str]` is a blocking operator gate (`ConfirmDialog`,
cross-thread via `app.py::_blocking_confirm`) shown before *every* real send: both
manual-review replies and every per-job SmartAdvisor reply. It returns one of three
outcomes: `"approve"`, `"decline"`, or `"sent_manually"`.

- **Approve** → `_approve_or_stop` returns normally → `extractor.send_reply(...)`
  runs as usual.
- **Decline** (or the window is closed while the dialog is up) → `_approve_or_stop`
  emits a `"Run stopped: reply declined"` status event, calls `control.cancel()`,
  and raises `RunCancelled` — caught by `run()`'s outer `try/except RunCancelled`,
  which stops the whole run (no more emails, `extractor` and `helper` closed, no
  reply sent for the declined email).
- **Sent Manually** → the operator has already sent the reply themselves in MAX and
  the email is already gone from the queue. `_approve_or_stop` raises `SentManually`
  (`run_control.py`) *without* touching `control` at all — this is decided
  synchronously on the run thread, unlike Park It below, so it needs no cross-thread
  flag. `run()` catches it around each of the three places `_approve_or_stop` is
  called (manual-review classification-error path, manual-review no-jobs path, and
  the per-email SmartAdvisor jobs loop): it increments `summary.sent_manually`,
  emits a status event, and `continue`s straight to the next email — **neither**
  `extractor.send_reply(...)` **nor** `extractor.park_now()` is called; there is
  nothing left to click. If this fires mid-way through a multi-job SmartAdvisor
  email, the remaining jobs for that email are simply abandoned.

### EOR PDF attachment

`smartadvisor_automation`'s workflow already saves an EOR PDF to local disk (via
SmartAdvisor's native "Print EOR" / "Export Report" dialogs) on paid/denied
outcomes and returns its path as `eor_pdf_path` on the `WorkflowResult`. The
orchestrator now collects every non-empty `eor_pdf_path` across all jobs for an
email into a list, and passes that list as `attachments` to the single
`extractor.send_reply(last_reply, eor_paths or None)` call once all jobs for the
email are done. `IncontactExtractor.send_reply` attaches each file by locating the
hidden `<input type="file">` behind MAX's "Add Attachment" label
(`ADD_ATTACHMENT_INPUT_XPATHS`, via the visibility-bypassing
`_find_file_input_any_frame`) and calling `.send_keys(path)` on it directly — this
sets the file programmatically without opening the native OS file-picker a human
sees when clicking the button by hand.

## 4. Park It (abort-and-continue, distinct from Decline/Cancel)

`app.py` also exposes a **Park It** button on the main window (enabled for the
duration of a run, alongside Pause/Resume). It calls `control.request_park()`
(`RunControl`), which is a *narrower* cooperative interrupt than `cancel()` — it does
not stop the run, only the email currently in flight:

- `RunControl.request_park()` sets a park flag (and wakes a paused run);
  `consume_park_request()` reads-and-clears it. This is orthogonal to
  `cancelled`/`RunCancelled`.
- `_run_smartadvisor_job` checks `consume_park_request()` at each retry loop
  checkpoint, and `SmartAdvisorHelperClient.run_job`'s poll loop checks it on every
  iteration while a job is in flight. Either one raises `ParkRequested`
  (`run_control.py`) after sending `{"type": "cancel"}` to the SmartAdvisor helper
  subprocess and waiting for it to actually terminate (avoids racing the next job).
- `run()` catches `ParkRequested` around the per-email SmartAdvisor section only:
  it calls `extractor.park_now()` (clicks Park Email immediately, **no** Reply/paste
  step — a different, shorter path than `send_reply`), increments
  `summary.parked`, emits a status event, and `continue`s — extraction and
  processing carry on into the next email exactly as if this one had finished
  normally.

So: **Decline stops the run; Park It and Sent Manually both abort the current
email and keep looping — Park It clicks Park Email with no reply pasted, Sent
Manually clicks nothing at all because the operator already sent it by hand.**

## Key point

Extraction and reply-sending are decoupled on purpose: `IncontactExtractor.extract`
only produces emails; `PipelineOrchestrator` decides *what* reply text to send and
*when*, based on classification, the operator's Approve/Decline/Park It/Sent
Manually choice, and — for `bill_status` claims — the SmartAdvisor automation
result (including any EOR PDF to attach), not on the extraction step itself.
