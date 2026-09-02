# Left off: paste-before-dialog reply flow

## Problem

Operator reported: when the Approve / Decline / Sent Manually dialog appears
and they click **Sent Manually**, the MAX compose box is empty — there is no
generated reply sitting there for them to send themselves.

Root cause: the old flow only pasted the reply into MAX *after* the operator
clicked Approve. Picking Sent Manually meant nothing had been pasted yet.

## Change made (implemented, tests passing, NOT yet built/released)

Split the single `send_reply(reply_text, attachments)` call into two steps and
reordered the pipeline so the paste happens before the dialog is shown:

- `open_reply(reply_text)` — opens the Reply box if not already open, pastes
  `reply_text`. Called **before** the Approve/Decline/Sent Manually dialog.
- `finalize_reply(attachments)` — attaches EOR PDFs (if any) and clicks Park
  Email. Called **only after** the operator clicks Approve.

Files touched:
- `src/incontact_automation/extractor.py` — added `open_reply`/`finalize_reply`,
  kept `send_reply` as a thin wrapper (`open_reply` then `finalize_reply`) for
  compatibility. Added `_reply_box_open()` helper so a second/third paste (for
  multi-job SmartAdvisor emails) doesn't re-click Reply if the pane is already
  open.
- `src/mitchel_pipeline/orchestrator.py` — `Extractor` Protocol updated; all
  three call sites (manual-review-no-jobs, classification-error, per-job
  SmartAdvisor loop) now call `open_reply` before `_approve_or_stop` and
  `finalize_reply` after a successful approve / loop completion.
- `tests/test_orchestrator.py` — `FakeExtractor`/`OrderedExtractor` fakes and
  three `order` assertions updated to match the new call sequence.

### Bug fixed along the way

The paste logic (JS `insertInto` in the extractor, plus the two Python
fallback paths using clipboard/`send_keys`) used **append/prepend** semantics.
That was fine when paste happened once per email, but the new design can call
`open_reply` multiple times per email (once per SmartAdvisor job, as each
job's dialog appears), which would have stacked/duplicated text. Fixed all
paste paths to fully replace the compose box's existing content first
(select-all + delete, or `range.selectNodeContents` + `insertText`).

All 143 tests pass.

## Not yet verified (live MAX UI, can't test outside the browser)

1. **Reply-button re-click safety.** `_reply_box_open()` decides whether to
   skip re-clicking Reply by checking if the compose editor is already visible
   via the existing frame-search helper. Unverified: how MAX behaves if this
   check ever false-negatives and Reply gets clicked while a pane is already
   open.
2. **Park-It-during-multi-job edge case.** If job 1's reply is approved and
   pasted, then job 2 triggers a Park Email interrupt (`ParkRequested`,
   separate from the Approve/Decline dialog), `park_now()` clicks Park Email
   directly without clearing the still-open draft from job 1. This situation
   didn't exist in the old design (nothing was ever pasted mid-loop before)
   and hasn't been resolved yet.

## Still pending

- Build and release this change (not done yet — wait for explicit "build and
  push").
- Update `flow.md` sections describing the reply-approval order (currently
  describes the old dialog-first order).
