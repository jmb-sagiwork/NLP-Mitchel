# Mitchel NLP

Mitchel is an attended Windows workflow that extracts configured emails from
NICE CXone, classifies them locally, and sends eligible bill-status jobs to
SmartAdvisor. The NLP inference path runs fully offline on CPU.

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

See [`TECH_STACK.md`](TECH_STACK.md) for the full stack walkthrough and the four
levers for teaching the engine without writing code.

## Dropping it into another app

The repo is two packages, and the dependency only points one way:

| Package | What it is | Depends on |
|---|---|---|
| `email_triage` | the engine — classification, extraction, config | nothing but stdlib (plus the optional `embeddings` extra) |
| `email_triage_ui` | the teaching window | `email_triage` |

Your app takes the first one and never sees the second. Nothing in the engine
imports tkinter, so it runs on a headless host; `tests/test_engine_is_standalone.py`
asserts that rather than trusting it.

```python
from email_triage import TriageEngine, classify_email

engine = TriageEngine()                       # load the model once, at startup
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

## Download Mitchel NLP (Windows, no install)

**[MitchelNLP-v0.2.3-windows-x64.exe](https://github.com/jmb-sagiwork/NLP-Mitchel/releases/download/v0.2.3/MitchelNLP-v0.2.3-windows-x64.exe)** — the complete attended application in one executable. Download and double-click to run.

The executable contains Python, the MiniLM encoder, Selenium, and the x86
SmartAdvisor helper. The target machine still needs Google Chrome and an
authenticated SmartAdvisor session, but it does not need Python or a separate
model download. ([all releases](https://github.com/jmb-sagiwork/NLP-Mitchel/releases))

Run the packaged diagnostic first on a new machine:

```powershell
.\MitchelNLP-v0.2.3-windows-x64.exe --selftest
```

It writes `mitchel-selftest.json` beside the executable and verifies MiniLM,
the NLP-to-job mapping, Selenium, and the embedded helper handshake without
opening CXone or changing SmartAdvisor.

## Quick start

```bash
py -3.14 scripts/fetch_model.py     # one time, needs internet (23 MB)
py -3.14 -m mitchel_pipeline        # combined attended workflow
py -3.14 run_ui.py                  # optional NLP teaching window
py -3.14 -m pytest -q               # 111 tests
```

Once the packages are installed (`pip install -e .`), the same two entry points
are `email-triage` (engine CLI: `check-config`, `classify`) and
`email-triage-ui` (the window), or `python -m email_triage` /
`python -m email_triage_ui`.

Without the model the engine still runs on regex + rules and caps confidence at
70%. It degrades; it does not crash.

## Building the combined EXE

```powershell
py -3.14 scripts/build_mitchel.py --clean
```

The build creates `dist/MitchelNLP.exe`. It verifies the MiniLM hashes, compiles
the SmartAdvisor helper with x86 Python, verifies both PE architectures, embeds
the helper into the x64 main application, and runs the frozen self-test before
declaring success. See [`PACKAGING.md`](PACKAGING.md) for prerequisites and the
full build/run notes.

## How it works

Three layers vote, weighted, over one JSON config:

| Layer | Weight | What it does | Cost |
|---|---|---|---|
| Structural | 0.10 | Regex detectors: claim numbers, amounts, dates, NPIs | ~0 |
| Rules | 0.30 | Weighted keywords; `decisive` phrases short-circuit | ~0 |
| Embeddings | 0.60 | MiniLM int8 ONNX, cosine vs per-concern prototypes | 23 MB, ~20 ms |

Layer 3 is why **adding a concern type needs no training**. You describe the
concern in plain English in `concerns.json`; classification is cosine similarity
against that description. See `tests/test_add_concern.py` — it adds a whole new
concern type with zero code and asserts it classifies.

### Two levels: concern, then reason

**Concern** is what the item is about (Bill Status, Claim Information). **Reason**
is the sub-classification within it, scored by the same engine but rules-led --
reasons are stock phrases stated near-verbatim, not paraphrases.

A reason is emitted **only when wording supports it**. Softmax always hands its
mass to something, so without that guard an ordinary "what is the status of this
bill?" gets labelled "not a bill on file". No supporting wording, no reason.

### Fields that share a regex must require a label

DOS, DOI and DOB all resolve to one date pattern; Claim ID, Patient Account and
Prov TIN are all digit runs. Those fields set `require_label: true`, so they
accept only label-anchored values and report nothing otherwise. An unattributable
match is worse than a gap -- assigning the first date in the body to all three
date fields is a silent, confident error.

### Two behaviours that look like bugs but are not

**Evidence shrinkage.** `confidence = fused × min(1, (prototypes + examples) / 4)`.
A concern authored with one prototype caps at 25% confidence and always routes to
human review until you flesh it out. A data-starved classifier that guesses
confidently is the worst failure mode available; this makes thinness visible.

**A missing required field never changes the label.** It sets `needs_review`,
lowers confidence, and lists the gap in `missing_fields`. Silently relabelling
because a regex missed would be worse than reporting the gap.

## Teaching it something new

Two different actions, often confused:

| You want to... | Do this | Effect |
|---|---|---|
| Fix a wrong label on one email | Teach bar → pick the right concern/reason → **Save to dataset** | One labelled row. Does not change behaviour by itself. |
| Name a category the taxonomy lacks | Teach bar → **`+ new concern...`** → type the name | Row is flagged `is_new_taxonomy`. Still cannot be predicted. |
| Make the engine actually predict it | `--scaffold`, then write prototypes into `concerns.json` | The engine can now classify it. |

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
it: a concern becomes predictable when it has **prototypes**, because Layer 3
classifies by cosine similarity against those descriptions.

`--scaffold` gives you everything except the thinking — id, display name,
`draft: true`, and empty `prototypes` / `examples` arrays. Those two stay empty
on purpose:

- **Prototypes cannot be derived from a label.** They are the descriptions the
  encoder embeds. A block auto-filled with none would classify nothing while
  looking finished.
- **Examples must not come from the dataset.** `dataset.jsonl` holds real email
  text; `concerns.json` is committed to git. Write realistic phrasings with
  fake identifiers instead.

`draft: true` makes `check-config` warn until you take it out, so an unfinished
concern is visible rather than silently inert.

Edit `src/email_triage/resources/concerns.json`, paste the block (or copy an
existing one), then:

```bash
PYTHONPATH=src py -3.14 -m email_triage check-config    # from a bare checkout
py -3.14 -m email_triage check-config                   # after pip install -e .
```

Write **prototypes** as descriptions of what the sender wants, not as keywords —
they are embedded and compared semantically. Reference regexes from
`patterns.library.json` by `pattern_ref`; do not write regex in `concerns.json`.

## The UI is for teaching, not for shipping

`run_ui.py` opens a window that takes a pasted subject and body and shows the
concern, the extracted fields, the per-layer scores, and the JSON. **Its only
job is teaching the model.** It is not the integration path and it is not meant
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
`is_new_taxonomy: true` separates "the model got this wrong" from "we have
never modelled this at all", which are different problems with different fixes.

## Privacy

Real emails carry claimant PII/PHI.

- No network call at inference. `tokenizers` is loaded via `Tokenizer.from_file`,
  so `huggingface_hub` and `requests` are never imported.
- ONNX Runtime telemetry is disabled explicitly; the CPU provider is pinned.
- `data/` and all `*.jsonl` are gitignored. **`data/dataset.jsonl` contains real
  email text — it must stay on the local machine.**
- All test fixtures are synthetic and all identifiers in this repo are invented.

## Repo layout

```
src/email_triage/          THE ENGINE - this is what a host app imports
  api.py           classify_email / classify_emails   <- the stable contract
  engine.py        fusion, decision ladder, TriageEngine
  layers.py        the three scoring layers
  extract.py       field extraction + normalizers
  textprep.py      normalization, thread split, signature detection
  config.py        loads + compiles concerns.json
  render.py        plain text, JSON, training records
  resources/       concerns.json, patterns.library.json, model/
  __main__.py      CLI: check-config, classify   (no tkinter in this package)

src/email_triage_ui/       THE TEACHING WINDOW - optional, never shipped to a host
  app.py           the window, the Teach bar
  theme.py         dark ttk theme
  proposals.py     what reviewers asked for that the taxonomy lacks (--proposals)
  selftest.py      headless bundle diagnostic (--selftest)

scripts/fetch_model.py
tests/
pipeline.md        active work items
```

The arrow only points one way: `email_triage_ui` imports `email_triage`, never
the reverse.

## Interpreter

This machine has **two** Python 3.14 installs. `C:\Python314\python.exe` is on
PATH but lacks onnxruntime; `py -3.14` resolves to the pythoncore install that
has it. **Always use `py -3.14`**, never bare `python`.

Source targets 3.11+ (`ruff target-version = py311`) because end-user machines
are locked down and their interpreter version is not yet known.
