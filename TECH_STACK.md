# Tech Stack & How to Teach the NLP

How the email triage engine is built, and how you improve it without writing code.

Companion docs: [`README.md`](README.md) for setup, [`pipeline.md`](pipeline.md) for open work.

---

# Part 1 — The tech stack

## Runtime (what ships to end users)

| Layer | Choice | Installed size | Why this |
|---|---|---|---|
| Language | Python 3.11–3.14 | — | Source targets 3.11; end-user version not yet known |
| Inference | **onnxruntime 1.27** (CPU) | 42 MB | Runs a transformer without PyTorch |
| Tokenizer | **tokenizers 0.22** | 7 MB | Rust; loaded via `from_file`, so no HTTP client |
| Math | **numpy 2.5** | 31 MB | Mean pooling + cosine, ~10 lines |
| Model | **all-MiniLM-L6-v2**, int8 AVX2 quantized | **22 MB** | 6-layer encoder, 384-dim output |
| UI (teaching only) | Tkinter + ttk `clam` | 0 | Ships with Python; separate package, not in the engine |

**Total runtime: ~86 MB of packages + 22 MB of model.**

Verify what actually loads at inference:

```bash
py -3.14 -c "
import sys; sys.path.insert(0,'src')
from email_triage import classify_email
classify_email('Bill status for Claim ID WC1234567.')
print([m for m in sorted(sys.modules) if m in
  ('onnxruntime','tokenizers','numpy','torch','transformers','requests','huggingface_hub')])
"
# -> ['numpy', 'onnxruntime', 'tokenizers']
```

### Why not PyTorch / sentence-transformers

They would give the same MiniLM weights with far less code. They are excluded because **PyTorch is ~497 MB installed** for what a 22 MB ONNX file does. End-user machines have 4 GB RAM, no GPU, no internet, and are locked down. The ONNX path fits; the torch path does not.

### Why not `fastembed`

It wraps exactly this stack, but it eagerly imports `requests` + `huggingface_hub` + Pillow, has no `local_files_only` option, and carries a Google Cloud Storage download URL. Unacceptable in a process holding claimant PHI. Using `Tokenizer.from_file()` instead means `huggingface_hub` is **never installed**, which is a structural guarantee rather than a config flag.

### Build and dev only (never shipped)

`PyInstaller 6.21` (the EXE), `pytest` (57 tests), `pandas` (optional extra, lazy-imported).

---

## The pipeline, end to end

```
email body
   │
   ▼
textprep.py ── normalize (NFKC, unwrap, collapse)
   │           split → subject | newest body | signature | quoted history
   │           classification reads the NEWEST message only
   ▼
┌──────────────────────────────────────────────────────────┐
│  L1  structural   regex pattern hits        weight 0.10   │
│  L2  rules        weighted keyword scoring  weight 0.30   │
│  L3  embeddings   MiniLM cosine similarity  weight 0.60   │
└──────────────────────────────────────────────────────────┘
   │  fused → × saturation → thresholds  ⇒  CONCERN
   ▼
reason pass ── same scorers, but 0.25 embedding / 0.75 rules  ⇒  REASON
   ▼
extract.py ── per field: locate label → search 60 chars after it → normalize
   ▼
TriageResult  (concern, reason, 7 fields, per-layer scores, spans)
```

### How Layer 3 works

This is what makes the system teachable without training:

1. On startup, every `prototypes` and `examples` string is embedded to a 384-dim vector.
2. The incoming email is embedded the same way.
3. Cosine similarity against each concern's vectors; max per concern; softmax.

There are **no weights to update**. You program the classifier by writing sentences.

The ONNX export emits `last_hidden_state`, not a sentence embedding — `layers.py` does attention-masked mean pooling and L2 normalization in numpy. That step is the one most commonly got wrong when leaving `sentence-transformers`.

### Graceful degradation

If the model file is missing, the engine drops the embedding weight, renormalizes rules + structural, caps confidence at **0.70**, and records `layers_used`. It degrades; it does not crash.

---

## Tuning constants

Config, in `resources/concerns.json` → `defaults`:

| Setting | Value | Meaning |
|---|---|---|
| `fusion_weights` | `0.60 / 0.30 / 0.10` | embedding / rules / structural |
| `accept` | `0.55` | at or above → CLASSIFIED |
| `review` | `0.35` | below → UNCLASSIFIED |
| `margin` | `0.12` | top-2 gap below this → AMBIGUOUS |
| `reason_accept` | `0.45` | reason threshold |
| `evidence_saturation_k` | `4` | prototypes+examples for full confidence |

Code, in `engine.py`:

| Constant | Value | Meaning |
|---|---|---|
| `NO_MODEL_CONFIDENCE_CAP` | `0.70` | ceiling when Layer 3 is unavailable |
| `MISSING_FIELD_PENALTY` | `0.80` | confidence multiplier when a required field is absent |
| `REASON_EMBEDDING_WEIGHT` | `0.25` | reasons are rules-led, not semantic |

---

## Where the code lives

| File | Job |
|---|---|
| `resources/concerns.json` | **The file you edit.** Taxonomy, fields, keywords |
| `resources/patterns.library.json` | Named regexes, referenced by `pattern_ref` |
| `config.py` | Validates and compiles the above |
| `textprep.py` | Normalization, thread splitting, signature detection |
| `layers.py` | The three scorers + the ONNX encoder |
| `extract.py` | Field extraction, candidate ranking, normalizers |
| `engine.py` | Fusion, decision ladder, `TriageEngine` |
| `api.py` | `classify_email()` — the only stable contract |
| `render.py` | Plain text, JSON, training records |

Everything above lives in `src/email_triage/`, the package a host application
imports. The teaching window is a **separate** top-level package:

| File | Job |
|---|---|
| `email_triage_ui/app.py` | The window and the Teach bar |
| `email_triage_ui/theme.py` | Dark ttk theme |
| `email_triage_ui/selftest.py` | Headless bundle diagnostic (`--selftest`) |

`email_triage_ui` imports `email_triage`; nothing goes the other way, and no
engine module imports tkinter. That is enforced by
`tests/test_engine_is_standalone.py`, not just documented here.

---

# Part 2 — How to teach it

Four levers, differing in effort and in what they fix.

## Lever 1 — Prototypes (semantic understanding)

Plain-English **descriptions of what the sender wants**. This is the ML authoring surface.

```json
"prototypes": [
  "The sender is asking for the current status of a bill submitted on a claim.",
  "A provider wants to know whether a bill finished processing and the outcome."
]
```

**Use when:** the engine misses paraphrases — an email that means Bill Status but never says "bill status".

Write descriptions, not keywords. `"bill status inquiry"` is a weak prototype; a full sentence describing intent is a strong one.

## Lever 2 — Examples (real phrasings)

```json
"examples": ["Can you check the status of the bill for claim WC1234567?"]
```

Examples are embedded like prototypes **and** raise the evidence count:

```
confidence = fused_score × min(1, (prototypes + examples) / 4)
```

Below 4 combined, confidence is capped. One prototype → a hard ceiling of **25%**, so it always routes to review. This is deliberate: it makes a thin concern visibly untrusted rather than confidently wrong. **Four combined texts is the minimum for full confidence.**

## Lever 3 — Keyword rules (deterministic)

```json
"positive": [{ "phrase": "bill status", "weight": 3.5 }],
"negative": [{ "phrase": "no claim on file", "weight": 4.0 }],
"decisive": [{ "all_of": ["bill status"] }]
```

- `positive` / `negative` nudge the score.
- **`decisive` overrides the ranking outright.** If exactly one concern fires a decisive rule and its structural gate passes, it wins regardless of the encoder.

**Use when:** you need a guarantee, not a preference. Repeats score sub-linearly (`1 + log n`) — saying it five times is not five times the evidence.

## Lever 4 — Patterns and label aliases (extraction)

Extraction failures are almost never the model. They are **missing label synonyms**.

```json
{ "name": "date_of_service",
  "pattern_ref": "us_date",
  "require_label": true,
  "label_aliases": ["date of service", "service date", "dos"] }
```

If your emails write `Svc Date:` and it is not listed, the field returns empty.
**Adding a synonym is the highest-return edit available.**

### Why `require_label` matters

DOS, DOI and DOB all resolve to one date regex; Claim ID, Patient Account and Prov TIN are all digit runs. Fields sharing a pattern set `require_label: true` and accept **only** label-anchored values, reporting nothing otherwise.

An unattributable match is worse than a gap — assigning the first date in the body to all three date fields is a silent, confident error. The trade-off: an *unlabelled* identifier is dropped rather than guessed.

---

## Worked example: adding a reason

Adding a **"Duplicate bill"** reason to Bill Status:

```json
{
  "id": "duplicate_bill",
  "display_name": "Duplicate bill",
  "prototypes": [
    "The submitted bill duplicates one already on file for the same claim and date of service.",
    "This charge was already received and processed, so the resubmission is a duplicate."
  ],
  "examples": ["Duplicate bill - already processed under this claim."],
  "keyword_rules": {
    "positive": [
      { "phrase": "duplicate", "weight": 4.0 },
      { "phrase": "already submitted", "weight": 2.5 }
    ],
    "negative": [],
    "decisive": [{ "all_of": ["duplicate bill"] }]
  }
}
```

Then validate:

```bash
py -3.14 -m email_triage check-config
```

**No code, no retraining.** The reason's keywords automatically roll up as weaker evidence for Bill Status itself, so they need not be duplicated at the concern level. `tests/test_add_concern.py` asserts this workflow end to end.

---

## The feedback loop

The UI's **Teach** bar appends one JSONL row per reviewed email to `data/dataset.jsonl`:

```json
{ "record_id": "...", "created_at": "...",
  "input":      { "subject": "...", "body": "..." },
  "label":      { "concern_id": "...", "reason_id": "...",
                  "verified_by_human": true,
                  "was_prediction_correct": false,
                  "was_reason_correct": true },
  "prediction": { "...full result, per-layer scores, character spans..." } }
```

Because it stores **per-layer scores**, a wrong answer tells you *which layer* failed — and that tells you which lever to pull:

| Symptom in the record | Fix |
|---|---|
| `embedding` low **and** `rules` low | Add prototypes (Lever 1) |
| `embedding` high for the **wrong** concern | Add a `negative` keyword (Lever 3) |
| Right concern, field is `null` | Add a `label_alias` (Lever 4) |
| `saturation` below 1.0 | Add examples (Lever 2) |
| Reason invented / absent | Adjust reason `positive` phrases |

Filter on `verified_by_human` for the confirmed subset; `was_prediction_correct: false` is the error set to analyse first.

### Known gap

**Nothing reads `dataset.jsonl` yet.** That is `pipeline.md` **SP-1.1-45** and it is not built. The loop is currently **manual**: read the rows, decide, edit the JSON. The capture format exists so data accumulates from day one instead of being lost, but the analysis script does not.

Related: rows accumulate only as fast as someone pastes and reviews in the UI. Until mail integration lands (**SP-1.1-43**), that is the only intake.

---

## Recommended order of work

1. **Run ~20 real emails through the UI.** Tune nothing yet — just look.
2. **Fix extraction before classification.** Every `null` field is probably a missing `label_alias`. Cheapest and highest-return.
3. **Then classification.** Wrong concern → add a prototype describing what that email *meant*.
4. **Answer SP-1.1-48 first if you can.** If reasons are dispositions recorded after a claims-system lookup, they are not predictable from email text at all, and tuning them is wasted effort. The engine already emits *no* reason for an ordinary inbound status question, which supports that reading.

---

## Privacy constraints on all of the above

- No network call at inference — enforced structurally by not installing `huggingface_hub` or `requests`.
- ONNX Runtime telemetry is disabled explicitly; the CPU provider is pinned.
- `data/dataset.jsonl` holds **real email text**. It is gitignored and must stay local.
- Every identifier in this repo, in all tests, and in the UI samples is invented. Never paste real claim IDs, DOBs, or patient accounts into fixtures or examples.
