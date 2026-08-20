# Project Mitchel Integration Plan

## Objective

Combine the four source branches into one attended desktop workflow:

`Incontact -> Mitchel NLP -> SmartAdvisor`

The source branches remain intact. Development occurs on
`integration/combined-main`; remote `main` is updated only after automated tests
and a successful live acceptance run.

## User experience

- Compact, movable Tkinter window (approximately 420 x 180 pixels).
- Status text, percentage, progress bar, and a short run summary.
- MiniLM enabled by default and selectable before a run.
- Start and Pause/Resume controls.
- Pause is cooperative and takes effect after the current browser/UIA action.
- Closing the window cancels the run, closes Chrome, and stops the helper.

## Pipeline

1. Open the three fixed CXone player URLs after manual login confirmation.
2. Extract the original email from each thread and save it under
   `Downloads/Email_extraction`.
3. Classify each email with the shared `email_triage` API. NLP errors are
   recorded and skipped.
4. Accept only `bill_status` results with a claim ID and paired DOS/expected
   amount line items.
5. Deduplicate identical `(claim_id, DOS, amount)` SmartAdvisor jobs.
6. Send each job to the x86 SmartAdvisor helper. SmartAdvisor errors pause the
   run for review; Resume retries the current job.
7. Leave the final matched SmartAdvisor bill open.

Progress allocation: startup/login 0-10%, extraction 10-35%, NLP 35-50%, and
SmartAdvisor 50-100%.

## Runtime boundaries

- `email_triage`: offline NLP with an explicit MiniLM on/off engine option.
- `incontact_automation`: Selenium extraction service; no application UI.
- `smartadvisor_automation`: proven UI Automation workflow and diagnostics.
- `mitchel_pipeline`: shared models, cooperative run control, orchestration,
  helper client/protocol, and compact UI.
- Main executable: x64. SmartAdvisor helper: x86, bundled and launched without
  a visible console. IPC uses one JSON object per line.

Logs contain identifiers needed for operations, but never full email bodies or
PHI-bearing CXone URLs.

## Acceptance gates

1. NLP unit tests pass with MiniLM enabled and disabled.
2. Pipeline tests cover pairing, deduplication, skip/continue, pause/resume,
   retry, cancellation, and event/progress ordering.
3. Frozen x64 application self-test passes.
4. x86 SmartAdvisor helper builds and passes CI tests on an x86 Python runner.
5. A live attended run completes in CXone and SmartAdvisor.
6. Only after sign-off is the integration branch merged or pushed to `main`.
