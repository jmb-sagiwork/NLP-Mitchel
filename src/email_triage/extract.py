"""Field extraction: once the concern is known, pull the fields it requires.

Two strategies run for every field, and their candidates compete:
  label_proximity - find a label alias ("Claim #:"), then the pattern near it
  pattern_only    - every pattern match in the segment

Label proximity wins when available, because "$1,250.00" next to the words
"charge amount" is far stronger evidence than the first dollar figure in the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import CompiledConcern, CompiledField, Config
from .textprep import PreparedText
from .types import FieldValue, Segment

# How far after a label to look for the value.
_LABEL_WINDOW = 60


# --------------------------------------------------------------------------
# normalizers
# --------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _norm_trim(raw: str) -> str:
    return raw.strip()


def _norm_upper_alnum(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", raw.upper())


def _norm_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _norm_money(raw: str) -> str:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return cleaned


def _norm_date_iso(raw: str) -> str:
    s = raw.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", s)
    if m:
        mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        return f"{yr:04d}-{mo:02d}-{day:02d}"
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        mo = _MONTHS.get(m.group(1).lower())
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}"
    return s


NORMALIZERS = {
    "trim": _norm_trim,
    "upper_alnum": _norm_upper_alnum,
    "digits": _norm_digits,
    "money": _norm_money,
    "date_iso": _norm_date_iso,
}


def normalize_value(raw: str, normalizer: str) -> str:
    return NORMALIZERS.get(normalizer, _norm_trim)(raw)


# --------------------------------------------------------------------------
# candidates
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    raw: str
    value: str
    span: tuple[int, int]
    segment: str
    strategy: str
    score: float


def _segment_priority(kind: str) -> float:
    return {
        Segment.NEWEST_BODY.value: 1.0,
        Segment.SUBJECT.value: 0.9,
        Segment.QUOTED_HISTORY.value: 0.5,
        Segment.SIGNATURE.value: 0.2,
    }.get(kind, 0.4)


def _collect(field: CompiledField, prepared: PreparedText, cfg: Config) -> list[Candidate]:
    if field.pattern is None:
        return []
    out: list[Candidate] = []
    for seg in prepared.segments:
        seg_w = _segment_priority(seg.kind)
        low = seg.text.lower()

        # Where does each label alias appear?
        label_spans: list[tuple[int, int, str]] = []
        for alias in field.label_aliases:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                label_spans.append((m.start(), m.end(), alias))

        for raw, (s, e) in field.pattern.finditer(seg.text):
            value = normalize_value(raw, field.normalizer)
            if not value:
                continue
            best_label: tuple[int, str] | None = None
            for ls, le, alias in label_spans:
                # Value should follow the label within the window.
                if le <= s <= le + _LABEL_WINDOW:
                    dist = s - le
                    if best_label is None or dist < best_label[0]:
                        best_label = (dist, alias)
            if best_label is not None:
                dist, alias = best_label
                proximity = 1.0 - (dist / (_LABEL_WINDOW + 1))
                score = seg_w * (0.70 + 0.30 * proximity)
                strategy = f"label_proximity:{alias}"
            else:
                # Earlier in the segment is mildly better than later.
                position = 1.0 - min(s / max(len(seg.text), 1), 1.0)
                score = seg_w * (0.30 + 0.15 * position)
                strategy = "pattern_only"
            out.append(
                Candidate(
                    raw=raw,
                    value=value,
                    span=(seg.offset + s, seg.offset + e),
                    segment=seg.kind,
                    strategy=strategy,
                    score=round(score, 4),
                )
            )
    return out


def extract_fields(
    concern: CompiledConcern, prepared: PreparedText, cfg: Config
) -> tuple[dict[str, FieldValue], tuple[str, ...], tuple[str, ...]]:
    """Returns (fields, missing_required, ambiguous)."""
    fields: dict[str, FieldValue] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    delta = cfg.thresholds.get("field_ambiguity_delta", 0.10)

    for f in concern.fields:
        cands = _collect(f, prepared, cfg)

        if not cfg.search_quoted_history:
            cands = [c for c in cands if c.segment != Segment.QUOTED_HISTORY.value]

        # Prefer the newest message; only fall back to history if nothing else
        # produced a candidate.
        fresh = [c for c in cands if c.segment != Segment.QUOTED_HISTORY.value]
        pool = fresh or cands
        from_history = not fresh and bool(cands)

        if not pool:
            fields[f.name] = FieldValue(
                name=f.name,
                display_name=f.display_name,
                value=None,
                required=f.required,
                confidence=0.0,
            )
            if f.required:
                missing.append(f.name)
            continue

        pool.sort(key=lambda c: (-c.score, c.span[0]))
        best = pool[0]

        # Distinct competing values within delta of the winner => ambiguous.
        distinct = [c for c in pool if c.value != best.value]
        if distinct and (best.score - distinct[0].score) < delta:
            ambiguous.append(f.name)

        fields[f.name] = FieldValue(
            name=f.name,
            display_name=f.display_name,
            value=best.value,
            raw=best.raw,
            span=best.span,
            segment=best.segment,
            strategy=best.strategy,
            confidence=min(best.score, 1.0),
            required=f.required,
            from_history=from_history,
            candidates=tuple(dict.fromkeys(c.value for c in pool))[:5],
        )

    return fields, tuple(missing), tuple(ambiguous)
