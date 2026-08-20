# Technical stack: deterministic rules-only triage

This fork classifies and extracts email data with Python's standard library.
There is no neural model, model asset, tokenizer, numerical runtime, network
download, or telemetry path.

## Runtime

| Component | Implementation | Purpose |
|---|---|---|
| Language | Python 3.11+ | Engine and host API |
| Pattern matching | `re` | Identifiers, dates, amounts, labels |
| Configuration | JSON | Concerns, reasons, phrases, fields, thresholds |
| UI | Tkinter | Optional review and teaching harness |
| Tests | pytest | Synthetic regression suite |
| Windows bundle | PyInstaller | Optional standalone UI executable |

The `email_triage` package has no required third-party dependencies. The UI is
a separate package and the engine never imports it.

## Classification flow

```text
subject + body
      |
      v
text normalization and newest-message segmentation
      |
      +--> structural score: configured regex patterns present      weight 0.25
      |
      +--> rule score: positive/negative weighted phrases           weight 0.75
      |
      v
fused concern ranking
      |
      +--> one concern's decisive phrase may override the ranking
      +--> weak/no rule evidence competes with the background heuristic
      |
      v
status thresholds -> optional reason rules -> regex field extraction
```

The same input and config always produce the same output. There is no RNG and
no floating-point model inference.

## Scores and decisions

Rule hits are segment-weighted: newest body `1.0`, subject `0.9`, quoted
history `0.55`, and signature `0.3`. Repeated phrases receive sub-linear credit
and the total is squashed into `0..1` with `tanh`.

Structural score is the fraction of a concern's declared field patterns found
in the message. A concern may declare a structural gate and a penalty when its
expected identifier is absent.

The default fused score is:

```text
0.75 * rule_score + 0.25 * structural_score
```

The default status thresholds are:

| Threshold | Value | Meaning |
|---|---:|---|
| `accept` | 0.55 | Eligible for `CLASSIFIED` |
| `review` | 0.35 | Below this, remain `UNCLASSIFIED` |
| `margin` | 0.12 | Minimum lead over the runner-up/background |
| `reason_accept` | 0.45 | Minimum explicit support for a reason |

A unique decisive-rule owner is promoted and receives at least `0.90`
confidence. Missing required fields never change the selected concern; they
lower confidence and force review.

## Field extraction

`patterns.library.json` owns reusable regexes. `concerns.json` references them
by name and supplies label aliases and normalizers. Shared shapes such as DOS,
DOI, and DOB require a nearby label; an unattributable date is omitted instead
of being assigned to the wrong field.

Multi-value date-of-service and billed-amount fields retain every occurrence,
and line items preserve their pairing when the email contains several bills.

## Improving behavior

There are three primary levers:

1. Add positive phrases for supported alternate wording.
2. Add negative phrases when wording collides with another concern.
3. Add or refine label aliases and regex patterns for extraction.

Use decisive phrases sparingly: they intentionally outrank ordinary fused
scores. New concerns are JSON-only additions, but they require explicit phrase
coverage because this engine does not infer semantic similarity.

Run these gates after every config change:

```powershell
py -3.14 -m email_triage check-config
py -3.14 -m pytest -q
py -3.14 scripts/eval_samples.py
```

The sample evaluator uses a local, gitignored workbook containing real email
data. Do not commit or copy that workbook.

## Privacy and deployment

Inference performs no network calls and uses no model runtime. Real email text
appears only in caller memory and, when a reviewer explicitly saves feedback,
the local gitignored `data/dataset.jsonl` file. The Windows bundle contains
Python/Tk plus the JSON config and pattern library.
