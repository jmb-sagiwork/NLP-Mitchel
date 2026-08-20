# Email Triage

Reads an email, decides **what type of concern** it expresses, and extracts **the
data that concern requires**. Runs fully offline on CPU.

Example: concern **Bill Status** carries a reason (`not a bill on file`, `completed processing and denied`, ...) and seven fields: Claim ID, DOS, Patient Account, Prov TIN, Expected Amount, DOI, DOB.

```python
from email_triage import classify_email

result = classify_email(body, subject)      # two strings in, one result out

result.concern_id        # "bill_status"
result.reason_id         # "not_a_bill_on_file"  (None if the email states none)
result.values            # {"claim_id": "WC7788991", "date_of_service": "2026-05-01",
                         #  "date_of_injury": "2026-04-02", "date_of_birth": "1979-11-30",
                         #  "provider_tin": "987654321", "patient_account": "PA5512399",
                         #  "expected_amount": "3410.55"}
result.missing_fields    # ()
result.needs_review      # False
result.to_dict()         # fully JSON-serialisable
```

That is the whole integration surface. Everything else is internal.

See [`TECH_STACK.md`](TECH_STACK.md) for the rules-only architecture and tuning
workflow.

## Dropping it into another app

The repo is two packages, and the dependency only points one way:

| Package | What it is | Depends on |
|---|---|---|
| `email_triage` | the engine — classification, extraction, config | Python standard library only |
| `email_triage_ui` | the teaching window | `email_triage` |

Your app takes the first one and never sees the second. Nothing in the engine
imports tkinter, so it runs on a headless host; `tests/test_engine_is_standalone.py`
asserts that rather than trusting it.

```python
from email_triage import TriageEngine, classify_email

engine = TriageEngine()                       # load and compile the rules once
for msg in inbox:                             # your inbox, your loop
    result = classify_email(msg.body, msg.subject, engine=engine)
    if result.needs_review:
        route_to_human(result.to_dict())
```

`classify_email(body, subject)` is the entire input contract — plain text, no
`EmailRecord`, no adapter to implement. **Fetching mail is your side of the
line:** this module never touches a mailbox, and mail ingestion is deliberately
out of scope (see `pipeline.md` SP-1.1-54). Pass HTML through your own
flattener first; the engine expects text.

Reuse one `TriageEngine` across calls. `classify_email` without one falls back
to a lazily-built default, which is fine for a script and wasteful in a server.

## Quick start

```bash
py -3.14 run_ui.py                  # teaching window
py -3.14 -m pytest -q               # test the deterministic engine
```

Once the packages are installed (`pip install -e .`), the same two entry points
are `email-triage` (engine CLI: `check-config`, `classify`) and
`email-triage-ui` (the window), or `python -m email_triage` /
`python -m email_triage_ui`.

There is no model download, optional inference runtime, or network dependency.

## Building the EXE

```bash
py -3.14 scripts/build_exe.py --clean              # one-dir: dist/EmailTriage/
py -3.14 scripts/build_exe.py --onefile --clean    # one-file: dist/EmailTriage.exe
```

One-dir produces `dist/EmailTriage/` with a double-clickable `EmailTriage.exe`
beside its `_internal` folder. One-file folds that folder into one executable.
Either way Python, Tk, and the JSON rule resources are bundled, so the target
machine needs **no Python and no internet**.

Pick one-file for handing someone a single artifact; pick one-dir when startup
latency matters or the endpoint blocks self-extracting exes. The bootloader
unpacks one-file to a temp dir on **every** launch. Both resolve resources through `sys._MEIPASS` and
both write `data/dataset.jsonl` next to the real exe, so on-disk behaviour is
identical.

The build script runs the frozen binary's self-test from a temp directory before
declaring success, because a build that merely produces an `.exe` is not
evidence that its config and extraction resources came along with it.

```bash
dist/EmailTriage/EmailTriage.exe --selftest     # writes selftest.json, exit 0/1
```

That flag is also the field diagnostic for "it won't start on this machine" —
it reports the interpreter, whether resources resolved, the active layers, and
a full traceback on failure.

**Scope:** this freezes `email_triage_ui`, the teaching harness. The library a
host system imports stays a wheel — a frozen exe cannot be imported by another
interpreter's `main.py`. Two different deliverables; see `pipeline.md`
SP-1.1-31 and SP-1.1-55.

Notes:
- Close the app before rebuilding; Windows locks the bundled DLLs. The script
  detects this and says so.
- `data/dataset.jsonl` is written **next to the .exe**, not in the working
  directory. It holds real email text.

## How it works

Two deterministic layers vote, weighted, over one JSON config:

| Layer | Weight | What it does | Cost |
|---|---|---|---|
| Structural | 0.25 | Regex detectors: claim numbers, amounts, dates, NPIs | ~0 |
| Rules | 0.75 | Weighted keywords; `decisive` phrases override ranking | ~0 |

Adding a concern type still needs no Python change or training job, but it does
require explicit phrase rules. See `tests/test_add_concern.py`: it adds a concern
through JSON and asserts that the configured rules classify it.

### Two levels: concern, then reason

**Concern** is what the item is about (Bill Status, Claim Information). **Reason**
is the sub-classification within it, scored by the same rule engine. Reasons are
stock phrases stated near-verbatim, not paraphrases.

A reason is emitted **only when an explicit rule supports it**. An ordinary
"what is the status of this bill?" therefore does not get a disposition invented
for it. No supporting wording, no reason.

### Fields that share a regex must require a label

DOS, DOI and DOB all resolve to one date pattern; Claim ID, Patient Account and
Prov TIN are all digit runs. Those fields set `require_label: true`, so they
accept only label-anchored values and report nothing otherwise. An unattributable
match is worse than a gap -- assigning the first date in the body to all three
date fields is a silent, confident error.

**A missing required field never changes the label.** It sets `needs_review`,
lowers confidence, and lists the gap in `missing_fields`. Silently relabelling
because a regex missed would be worse than reporting the gap.

## Teaching it something new

Two different actions, often confused:

| You want to... | Do this | Effect |
|---|---|---|
| Fix a wrong label on one email | Teach bar → pick the right concern/reason → **Save to dataset** | One labelled row. Does not change behaviour by itself. |
| Name a category the taxonomy lacks | Teach bar → **`+ new concern...`** → type the name | Row is flagged `is_new_taxonomy`. Still cannot be predicted. |
| Make the engine actually predict it | `--scaffold`, then write phrase rules into `concerns.json` | The engine can now classify matching wording. |

The dropdown can only offer what `concerns.json` contains — that is why
`__other__` used to be the only escape hatch. Picking **`+ new concern...`** (or
**`+ new reason...`**) unfolds a second row where you type the name; the window
shows you the id it becomes (`Refund Request` → `refund_request`) so there is no
guessing when you write the config entry.

To see what people have been proposing:

```bash
py -3.14 -m email_triage_ui --proposals
```

It prints each proposed concern and reason with a count, the dates, what the
engine guessed instead, and reviewer notes — **no email text**, so the report
can leave the machine.

When you accept one, get the config block for it:

```bash
py -3.14 -m email_triage_ui --scaffold refund_request
```

JSON goes to stdout (so `--scaffold refund_request > block.json` gives a clean
file), instructions go to stderr. It **does not** write `concerns.json` — see
below for why.

## Adding a concern type

This is the step that changes behaviour. Nothing in the UI can substitute for
it: a concern becomes predictable only when it has explicit positive rules and,
where necessary, negative and decisive rules.

`--scaffold` gives you everything except the judgment: id, display name,
`draft: true`, and empty rule collections. They stay empty because a label alone
cannot establish which wording is safe, decisive, or likely to collide with
another concern. Do not copy real text from `dataset.jsonl` into committed JSON;
derive generalized rules and test them with synthetic identifiers.

`draft: true` makes `check-config` warn until you take it out, so an unfinished
concern is visible rather than silently inert.

Edit `src/email_triage/resources/concerns.json`, paste the block (or copy an
existing one), then:

```bash
PYTHONPATH=src py -3.14 -m email_triage check-config    # from a bare checkout
py -3.14 -m email_triage check-config                   # after pip install -e .
```

Write strong positive phrases, collision-preventing negative phrases, and use
decisive phrases sparingly. Reference regexes from `patterns.library.json` by
`pattern_ref`; do not write regex in `concerns.json`.

## The UI is for teaching, not for shipping

`run_ui.py` opens a window that takes a pasted subject and body and shows the
concern, the extracted fields, the per-layer scores, and the JSON. **Its only
job is reviewing and improving the rules.** It is not the integration path and it is not meant
to sit in anyone's daily workflow — your app calls `classify_email` directly.

The part that matters is the **Teach** bar at the bottom. Correcting a
prediction and saving appends a row to `data/dataset.jsonl` containing the exact
input, the full prediction with per-layer scores, and the human's label. Those
rows are the labelled dataset that tunes or trains the next version.

```json
{
  "record_id": "…", "created_at": "…",
  "input":      { "subject": "…", "body": "…" },
  "label":      { "concern_id": "…", "reason_id": "…", "fields": {…},
                  "verified_by_human": true, "was_prediction_correct": false,
                  "is_new_taxonomy": true,
                  "proposed_concern": { "id": "refund_request",
                                        "display_name": "Refund Request" },
                  "proposed_reason":  null },
  "prediction": { …full result, including per-layer scores and spans… }
}
```

Filter on `verified_by_human` to get the human-confirmed subset;
`was_prediction_correct: false` gives you the error set to analyse first; and
`is_new_taxonomy: true` separates "the engine got this wrong" from "we have
never modelled this at all", which are different problems with different fixes.

## Privacy

Real emails carry claimant PII/PHI.

- No network call or model runtime exists in the inference path.
- The engine package uses only the Python standard library.
- `data/` and all `*.jsonl` are gitignored. **`data/dataset.jsonl` contains real
  email text — it must stay on the local machine.**
- All test fixtures are synthetic and all identifiers in this repo are invented.

## Repo layout

```
src/email_triage/          THE ENGINE - this is what a host app imports
  api.py           classify_email / classify_emails   <- the stable contract
  engine.py        fusion, decision ladder, TriageEngine
  layers.py        structural and rule scoring
  extract.py       field extraction + normalizers
  textprep.py      normalization, thread split, signature detection
  config.py        loads + compiles concerns.json
  render.py        plain text, JSON, training records
  resources/       concerns.json, patterns.library.json
  __main__.py      CLI: check-config, classify   (no tkinter in this package)

src/email_triage_ui/       THE TEACHING WINDOW - optional, never shipped to a host
  app.py           the window, the Teach bar
  theme.py         dark ttk theme
  proposals.py     what reviewers asked for that the taxonomy lacks (--proposals)
  selftest.py      headless bundle diagnostic (--selftest)

tests/
pipeline.md        active work items
```

The arrow only points one way: `email_triage_ui` imports `email_triage`, never
the reverse.

## Interpreter

Development commands use `py -3.14` on this Windows checkout for consistency.

Source targets 3.11+ (`ruff target-version = py311`) because end-user machines
are locked down and their interpreter version is not yet known.
