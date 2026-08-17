"""Output rendering: plain text for humans, JSON for machines and for training.

The training record is the point of the JSON shape. Every inference writes
enough to (a) reproduce the decision and (b) be turned into a labelled example
later: the exact input, the per-layer scores that produced the answer, the
character spans of every extracted value, and empty slots for a human's
correction. Those corrections are the dataset that trains or tunes the next
version - see pipeline SP-1.1-17 and SP-1.1-36.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import TriageResult, TriageStatus

# 1.1.0 added label.proposed_concern / label.proposed_reason: a reviewer can
# now name a concern the taxonomy does not contain yet (SP-1.1-56).
DATASET_SCHEMA_VERSION = "1.1.0"

_STATUS_GLYPH = {
    TriageStatus.CLASSIFIED: "[OK]",
    TriageStatus.AMBIGUOUS: "[??]",
    TriageStatus.UNCLASSIFIED: "[--]",
    TriageStatus.ERROR: "[!!]",
}


# --------------------------------------------------------------------------
# human-readable
# --------------------------------------------------------------------------


def to_plain_text(result: TriageResult) -> str:
    """Flat text report. No PHI beyond what the caller already had in hand."""
    lines: list[str] = []
    add = lines.append

    add("=" * 62)
    add("EMAIL TRIAGE RESULT")
    add("=" * 62)
    add("")
    add(f"Type of concern : {result.display_name or '(none identified)'}")
    add(f"Concern ID      : {result.concern_id or '-'}")
    if result.reason_id:
        add(f"Reason          : {result.reason_display_name}  "
            f"({result.reason_confidence:.0%})")
    else:
        add(f"Reason          : (none stated in this email)")
    add(f"Status          : {_STATUS_GLYPH.get(result.status, '')} {result.status.value}")
    add(f"Confidence      : {result.confidence:.0%}   (margin {result.margin:+.3f})")
    add(f"Needs review    : {'YES' if result.needs_review else 'no'}")
    add(f"Decision reason : {result.explanation.reason}")
    add("")

    add("-" * 62)
    add("DATA NEEDED FOR THIS CONCERN")
    add("-" * 62)
    if not result.fields:
        add("  (this concern declares no fields)")
    for f in result.fields.values():
        tag = "required" if f.required else "optional"
        if f.value is None:
            add(f"  [ ] {f.display_name} ({tag})")
            add(f"        NOT FOUND")
        else:
            mark = "x"
            add(f"  [{mark}] {f.display_name} ({tag})")
            add(f"        value      : {f.value}")
            if f.raw and f.raw.strip() != f.value:
                add(f"        as written : {f.raw}")
            add(f"        found via  : {f.strategy}  in {f.segment}")
            if f.from_history:
                add(f"        NOTE       : taken from quoted history, verify it is current")
            if len(f.candidates) > 1:
                add(f"        others seen: {', '.join(f.candidates[1:])}")
    add("")

    if result.missing_fields:
        add(f"MISSING REQUIRED : {', '.join(result.missing_fields)}")
    if result.ambiguous_fields:
        add(f"AMBIGUOUS        : {', '.join(result.ambiguous_fields)}")
    if result.missing_fields or result.ambiguous_fields:
        add("")

    add("-" * 62)
    add("SCORING")
    add("-" * 62)
    add(f"Layers used: {', '.join(result.explanation.layers_used)}")
    add("")
    add(f"  {'concern':<24} {'emb':>6} {'rule':>6} {'struct':>7} {'fused':>7} {'sat':>5}")
    for s in result.explanation.scores:
        add(
            f"  {s.concern_id:<24} {s.embedding:>6.3f} {s.rules:>6.3f} "
            f"{s.structural:>7.3f} {s.fused:>7.3f} {s.saturation:>5.2f}"
            + ("" if s.gate_satisfied else "  (gate failed)")
        )
    add("")
    add(f"Engine {result.engine_version} / config {result.config_version} "
        f"/ {result.elapsed_ms:.1f} ms")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# machine-readable
# --------------------------------------------------------------------------


def to_json(result: TriageResult, *, indent: int | None = 2) -> str:
    return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)


def text_fingerprint(text: str) -> str:
    """Stable, non-reversible id for an input. Safe to log; the text is not."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def slugify_label(text: str) -> str:
    """Human name -> the id a `concerns.json` entry would use.

    "Refund Request (urgent)" -> "refund_request_urgent". Reviewers type names,
    not identifiers, so this is what turns "Refund Request" typed in the Teach
    bar into something that can be pasted straight into the config later.
    """
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def build_training_record(
    body: str,
    subject: str,
    result: TriageResult,
    *,
    corrected_concern_id: str | None = None,
    corrected_reason_id: str | None = None,
    corrected_fields: dict[str, str] | None = None,
    proposed_concern: str = "",
    proposed_reason: str = "",
    reviewer_note: str = "",
    reviewer: str = "",
) -> dict[str, Any]:
    """One JSONL row: everything needed to retrain, tune, or audit.

    `label` is what the human says is true. When no correction is supplied it
    mirrors the prediction and `verified` stays false, so a later training run
    can filter on human-confirmed rows only.

    `proposed_concern` / `proposed_reason` are free text: the reviewer naming
    something the taxonomy does not contain yet. They become the label so the
    rows group correctly, and are echoed under `label.proposed_*` so a later
    pass can tell "you got bill_status wrong" apart from "this is a category
    we have never modelled". A proposal is not a prediction the engine can
    make - it only becomes one once someone writes prototypes for it in
    concerns.json.
    """
    predicted = result.concern_id
    predicted_reason = result.reason_id

    proposed_concern_id = slugify_label(proposed_concern) if proposed_concern else ""
    proposed_reason_id = slugify_label(proposed_reason) if proposed_reason else ""

    corrected = corrected_concern_id or proposed_concern_id or predicted
    corrected_reason = corrected_reason_id or proposed_reason_id or predicted_reason
    field_labels = {
        name: (corrected_fields or {}).get(name, f.value)
        for name, f in result.fields.items()
    }
    verified = bool(
        corrected_concern_id
        or corrected_reason_id
        or proposed_concern_id
        or proposed_reason_id
        or corrected_fields
        or reviewer_note
    )

    return {
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "record_id": text_fingerprint(f"{subject}\n{body}"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # ---- input, verbatim: the training X ----------------------------
        "input": {
            "subject": subject,
            "body": body,
            "char_len": len(body),
        },
        # ---- label: the training y -------------------------------------
        "label": {
            "concern_id": corrected,
            "reason_id": corrected_reason,
            "fields": field_labels,
            "verified_by_human": verified,
            # Set when the reviewer named something outside the taxonomy. Both
            # are None on an ordinary correction, so `is_new_taxonomy` is the
            # one flag a triage of the dataset needs to sort on.
            "proposed_concern": (
                {"id": proposed_concern_id, "display_name": proposed_concern.strip()}
                if proposed_concern_id
                else None
            ),
            "proposed_reason": (
                {"id": proposed_reason_id, "display_name": proposed_reason.strip()}
                if proposed_reason_id
                else None
            ),
            "is_new_taxonomy": bool(proposed_concern_id or proposed_reason_id),
            "reviewer": reviewer,
            "reviewer_note": reviewer_note,
            "was_prediction_correct": (
                None if not verified else corrected == predicted
            ),
            "was_reason_correct": (
                None if not verified else corrected_reason == predicted_reason
            ),
        },
        # ---- what the model actually said: for error analysis -----------
        "prediction": result.to_dict(),
        # ---- provenance -------------------------------------------------
        "engine_version": result.engine_version,
        "config_version": result.config_version,
        "layers_used": list(result.explanation.layers_used),
    }


def append_training_record(record: dict[str, Any], path: str | Path) -> Path:
    """Append one JSONL row, creating the file and parents if needed.

    The file holds real email text. It is gitignored and must stay local.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return p
