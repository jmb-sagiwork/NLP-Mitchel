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
        add(f"Reason          : {result.reason_display_name}")
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
            values = f.all_values
            if len(values) == 1:
                add(f"        value      : {values[0]}")
            else:
                add(f"        values ({len(values)}):")
                for index, value in enumerate(values, start=1):
                    add(f"          {index}. {value}")
            if len(values) == 1 and f.raw and f.raw.strip() != f.value:
                add(f"        as written : {f.raw}")
            add(f"        found via  : {f.strategy}  in {f.segment}")
            if f.from_history:
                add(f"        NOTE       : taken from quoted history, verify it is current")
            if len(values) == 1 and len(f.candidates) > 1:
                add(f"        others seen: {', '.join(f.candidates[1:])}")

    if result.line_items:
        add("")
        add("PAIRED INQUIRIES")
        for index, item in enumerate(result.line_items, start=1):
            parts = []
            for name, value in item.fields.items():
                field = result.fields.get(name)
                parts.append(f"{field.display_name if field else name}: {value}")
            add(f"  {index}. {' | '.join(parts)}")
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
# narrated explanation
# --------------------------------------------------------------------------

# Plain-English gloss for every value `engine._decide` can put in
# `explanation.reason`. Kept here rather than in the engine so the decision
# codes stay short and machine-comparable.
_DECISION_GLOSS = {
    "decisive_rule": (
        "Exactly one concern matched a phrase its config marks as DECISIVE, so it "
        "was promoted to the top of the ranking outright - the fused scores below "
        "did not get to overrule it."
    ),
    "threshold": (
        "No decisive phrase fired, so the winner is simply the concern with the "
        "highest fused score, and it cleared both the accept bar and the margin bar."
    ),
    "low_margin": (
        "The winner cleared the confidence bar but not the margin bar: the "
        "runner-up scored too close behind to call this settled."
    ),
    "low_confidence": (
        "The winner beat its rivals but its own score sits between the review bar "
        "and the accept bar - enough to name a concern, not enough to act on it."
    ),
    "below_review_threshold": (
        "Nothing scored high enough to name at all, so no concern is reported "
        "rather than a low-confidence guess being passed off as an answer."
    ),
    "background_class": (
        "The background class ('not a tracked concern') outscored every real "
        "concern. This reads as ordinary correspondence, not a tracked request."
    ),
    "missing_required_field": (
        "A concern was identified, but a field it declares as REQUIRED could not "
        "be found, so the result was demoted to AMBIGUOUS for a human to complete."
    ),
    "empty_input": "There was no text left to classify once quoting was stripped.",
}

_LAYER_GLOSS = (
    "  emb    embedding  - MiniLM similarity between this email and the concern's\n"
    "                      prototype sentences\n"
    "  rule   keywords   - weighted phrases from the concern's keyword_rules,\n"
    "                      squashed to 0..1\n"
    "  struct structure  - whether the identifiers the concern expects (claim id,\n"
    "                      and so on) are present\n"
    "  fused             - the three above combined by the configured weights\n"
    "  sat    saturation - evidence shrinkage: a concern with few prototypes is\n"
    "                      capped low on purpose"
)

_DEFAULT_THRESHOLDS = {
    "accept": 0.55,
    "review": 0.35,
    "margin": 0.12,
    "reason_accept": 0.45,
}


def to_explanation_text(
    result: TriageResult,
    *,
    thresholds: dict[str, float] | None = None,
    embeddings_active: bool = True,
) -> str:
    """Narrate the decision: what won, what it beat, and what would flip it.

    Every number here already exists in `result.explanation`; this reads it out
    loud. It is what a reviewer opens before disagreeing with the engine, so it
    names the specific phrase or the missing field that drove each step rather
    than only the score that came out.
    """
    t = dict(_DEFAULT_THRESHOLDS)
    t.update(thresholds or {})
    ex = result.explanation
    lines: list[str] = []
    add = lines.append

    def rule() -> None:
        add("-" * 68)

    add("=" * 68)
    add("WHY THIS RESULT")
    add("=" * 68)

    # ---- 1. the concern ---------------------------------------------------
    add("")
    add(f"1. TYPE OF CONCERN  ->  {result.display_name or '(none identified)'}")
    if result.concern_id:
        add(f"   id: {result.concern_id}")
    rule()
    add(f"Decision code : {ex.reason}")
    for chunk in _wrap(_DECISION_GLOSS.get(ex.reason, "No gloss for this code."), 66):
        add(f"  {chunk}")
    add("")

    top = ex.scores[0] if ex.scores else None
    if top is not None:
        if top.decisive_hits:
            add("Decisive phrase(s) matched in the text:")
            for h in top.decisive_hits:
                add(f'  * "{h}"')
        else:
            add("Decisive phrases: none matched.")
        add("")
        if top.keyword_hits:
            add("Supporting keywords found:")
            for h in top.keyword_hits:
                add(f'  - "{h}"')
        else:
            add("Supporting keywords: none. This concern was carried by the")
            add("  embedding layer alone.")
        add("")
        add(
            "Structural gate: "
            + (
                "satisfied - the identifiers this concern expects are present."
                if top.gate_satisfied
                else "NOT satisfied - the identifiers this concern expects are"
            )
        )
        if not top.gate_satisfied:
            add("  absent, so its fused score was penalised.")
        add("")

    # ---- 2. the scoring table --------------------------------------------
    add("How the concerns scored (ranked, highest first):")
    add("")
    add(f"  {'concern':<30} {'emb':>6} {'rule':>6} {'struct':>7} {'fused':>7} {'sat':>5}")
    for s in ex.scores:
        add(
            f"  {s.concern_id:<30} {s.embedding:>6.3f} {s.rules:>6.3f} "
            f"{s.structural:>7.3f} {s.fused:>7.3f} {s.saturation:>5.2f}"
            + ("" if s.gate_satisfied else "   (gate failed)")
        )
    add("")
    add(_LAYER_GLOSS)
    add("")
    if not embeddings_active:
        add("NOTE: the embedding layer is not loaded, so 'emb' is 0.000 on every")
        add("      row and confidence is capped at 70%. Rules and structure are")
        add("      carrying the whole decision.")
        add("")

    # ---- 3. what it beat, and by how much ---------------------------------
    if len(ex.scores) > 1:
        runner = ex.scores[1]
        add(f"Runner-up      : {runner.concern_id} at fused {runner.fused:.3f}")
    add(f"Margin         : {result.margin:+.3f}   (must be >= {t['margin']:.3f})")
    add(
        f"Confidence     : {result.confidence:.0%}   "
        f"(accept >= {t['accept']:.0%}, review >= {t['review']:.0%})"
    )
    add(f"Status         : {result.status.value}")
    add("Needs review   : " + ("YES" if result.needs_review else "no"))
    add("")

    # ---- 4. the reason (only when the email actually states one) ----------
    if result.reason_id:
        add("=" * 68)
        add("")
        add(f"2. REASON  ->  {result.reason_display_name}")
        add(f"   id: {result.reason_id}")
        rule()
        for chunk in _wrap(
            "The reason is a sub-classification INSIDE the concern above. It is "
            "scored rules-first, with embeddings only breaking ties, because "
            "reasons are stock dispositions stated near-verbatim rather than "
            "paraphrased. Concern-level weights here would let the encoder invent "
            "a disposition the email never mentions.",
            66,
        ):
            add(f"  {chunk}")
        add("")
        add(
            f"It scored {result.reason_confidence:.3f} against a bar of "
            f"{t['reason_accept']:.2f}."
        )
        add("")
        if result.reason_alternatives:
            add("Reasons considered, best first:")
            for rid, score in result.reason_alternatives:
                mark = "   <- chosen" if rid == result.reason_id else ""
                add(f"  {rid:<44} {score:>6.3f}{mark}")
            add("")

    # ---- 5. fields --------------------------------------------------------
    add("=" * 68)
    add("")
    fields_section = 3 if result.reason_id else 2
    add(f"{fields_section}. FIELDS - how each value was found")
    rule()
    if not result.fields:
        add("  (this concern declares no fields)")
    for f in result.fields.values():
        if f.value is None:
            why = (
                "no match, and this field is REQUIRED, so the result was demoted"
                if f.required
                else "no match; optional, so nothing was demoted"
            )
            add(f"  [ ] {f.display_name}: {why}")
        elif f.strategy.startswith("label_proximity"):
            alias = f.strategy.split(":", 1)[1]
            add(
                f'  [x] {f.display_name}: found next to the label "{alias}" '
                f"in {f.segment}"
            )
        else:
            add(
                f"  [x] {f.display_name}: matched this field's pattern in "
                f"{f.segment}, with no label nearby to confirm it"
            )
        if f.from_history:
            add("        ^ taken from QUOTED HISTORY, so it may be stale")
        if len(f.all_values) > 1:
            add(
                f"        ^ {len(f.all_values)} values found for repeated inquiries "
                "(this is not ambiguity)"
            )
            for index, value in enumerate(f.all_values, start=1):
                add(f"          {index}. {value}")
        elif len(f.candidates) > 1:
            add(f"        ^ {len(f.candidates)} competing values were seen for this field")

    if result.line_items:
        add("")
        add(f"  {len(result.line_items)} date/amount inquiry pair(s) preserved:")
        for index, item in enumerate(result.line_items, start=1):
            parts = []
            for name, value in item.fields.items():
                field = result.fields.get(name)
                parts.append(f"{field.display_name if field else name}: {value}")
            add(f"    {index}. {' | '.join(parts)}")
    add("")

    # ---- 6. what would change the answer ----------------------------------
    add("=" * 68)
    add("")
    change_section = 4 if result.reason_id else 3
    add(f"{change_section}. WHAT WOULD CHANGE THIS ANSWER")
    rule()
    for item in _what_would_change(result, t, embeddings_active):
        wrapped = _wrap(item, 64)
        add(f"  * {wrapped[0]}")
        for chunk in wrapped[1:]:
            add(f"    {chunk}")
    add("")
    add(f"Segments read  : {', '.join(ex.segments_seen) or '-'}")
    add(f"Layers used    : {', '.join(ex.layers_used) or '-'}")
    add(
        f"Engine {result.engine_version} / config {result.config_version} "
        f"/ {result.elapsed_ms:.1f} ms"
    )
    return "\n".join(lines)


def _what_would_change(
    result: TriageResult, t: dict[str, float], embeddings_active: bool
) -> list[str]:
    """The actionable half: the specific edit that would move this decision."""
    out: list[str] = []
    ex = result.explanation

    if ex.reason == "decisive_rule":
        out.append(
            "Removing the decisive phrase from this concern's keyword_rules would "
            "hand the decision back to the fused scores above."
        )
    if ex.reason in ("low_margin", "low_confidence", "below_review_threshold"):
        out.append(
            "Adding prototypes or keyword phrases to the intended concern in "
            "concerns.json is the fix here - the gap is evidence, not thresholds."
        )
    if result.missing_fields:
        out.append(
            "Supplying the missing required field(s) - "
            + ", ".join(result.missing_fields)
            + " - would clear the demotion. The label itself never changes because "
            "a field is missing."
        )
    if result.ambiguous_fields:
        out.append(
            ", ".join(result.ambiguous_fields)
            + " had competing values within the ambiguity delta. Labelling the "
            "intended one in the source text disambiguates it."
        )
    if ex.scores and ex.scores[0].saturation < 1.0:
        out.append(
            "This concern is still evidence-shrunk: it has fewer prototypes and "
            "examples than the saturation target, so it cannot reach high "
            "confidence no matter how well it matches. Add examples."
        )
    if ex.scores and not ex.scores[0].gate_satisfied:
        out.append(
            "The structural gate failed. Including the identifier this concern "
            "expects would remove the penalty applied to its score."
        )
    if not embeddings_active:
        out.append(
            "The embedding model is not loaded. Restoring it turns the strongest of "
            "the three layers back on and lifts the 70% confidence cap."
        )
    if not out:
        out.append(
            "Nothing here was marginal - the winner cleared every bar with room to "
            "spare. If it is still wrong, the taxonomy is what needs the edit, not "
            "this email."
        )
    return out


def _wrap(text: str, width: int) -> list[str]:
    """Local word wrap. textwrap would be a second import for four lines."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


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
