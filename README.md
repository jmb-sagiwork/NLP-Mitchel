# Email Triage

Reads an email, decides **what type of concern** it expresses, and extracts **the
data that concern requires**. Runs fully offline on CPU.

Example: concern `Type of Bill` requires `claim_number` and `charge_amount`.

```python
from email_triage import classify_email

result = classify_email(body, subject=subject)

result.concern_id        # "type_of_bill"
result.values            # {"claim_number": "WC1234567", "charge_amount": "1250.00"}
result.missing_fields    # ()
result.needs_review      # False
result.to_dict()         # fully JSON-serialisable
```

That is the whole integration surface. Everything else is internal.

## Quick start

```bash
py -3.14 scripts/fetch_model.py     # one time, needs internet (23 MB)
py -3.14 run_ui.py                  # demo window
py -3.14 -m pytest -q               # 39 tests
```

Without the model the engine still runs on regex + rules and caps confidence at
70%. It degrades; it does not crash.

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

### Two behaviours that look like bugs but are not

**Evidence shrinkage.** `confidence = fused × min(1, (prototypes + examples) / 4)`.
A concern authored with one prototype caps at 25% confidence and always routes to
human review until you flesh it out. A data-starved classifier that guesses
confidently is the worst failure mode available; this makes thinness visible.

**A missing required field never changes the label.** It sets `needs_review`,
lowers confidence, and lists the gap in `missing_fields`. Silently relabelling
because a regex missed would be worse than reporting the gap.

## Adding a concern type

Edit `src/email_triage/resources/concerns.json`, copy any block, then:

```bash
py -3.14 -m email_triage check-config
```

Write **prototypes** as descriptions of what the sender wants, not as keywords —
they are embedded and compared semantically. Reference regexes from
`patterns.library.json` by `pattern_ref`; do not write regex in `concerns.json`.

## The UI is a harness, not the product

`run_ui.py` opens a window that takes a pasted email body and shows the concern,
the extracted fields, the per-layer scores, and the JSON. It stands in for the
mail integration, which is not settled yet (the client uses a web-based mail
system, so Outlook COM may be replaced — see `pipeline.md`).

The part that matters long term is the **Teach** bar at the bottom. Correcting a
prediction and saving appends a row to `data/dataset.jsonl` containing the exact
input, the full prediction with per-layer scores, and the human's label. Those
rows are the labelled dataset that tunes or trains the next version.

```json
{
  "record_id": "…", "created_at": "…",
  "input":      { "subject": "…", "body": "…" },
  "label":      { "concern_id": "…", "fields": {…},
                  "verified_by_human": true, "was_prediction_correct": false },
  "prediction": { …full result, including per-layer scores and spans… }
}
```

Filter on `verified_by_human` to get the human-confirmed subset;
`was_prediction_correct: false` gives you the error set to analyse first.

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
src/email_triage/
  api.py           classify_email / classify_emails   <- the stable contract
  engine.py        fusion, decision ladder, TriageEngine
  layers.py        the three scoring layers
  extract.py       field extraction + normalizers
  textprep.py      normalization, thread split, signature detection
  config.py        loads + compiles concerns.json
  render.py        plain text, JSON, training records
  resources/       concerns.json, patterns.library.json, model/
  ui/              Tk demo (optional; engine does not depend on it)
scripts/fetch_model.py
tests/
pipeline.md        active work items
```

## Interpreter

This machine has **two** Python 3.14 installs. `C:\Python314\python.exe` is on
PATH but lacks onnxruntime; `py -3.14` resolves to the pythoncore install that
has it. **Always use `py -3.14`**, never bare `python`.

Source targets 3.11+ (`ruff target-version = py311`) because end-user machines
are locked down and their interpreter version is not yet known.
