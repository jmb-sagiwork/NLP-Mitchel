"""Field extraction: once the concern is known, pull the fields it requires.

Two strategies run for every field, and their candidates compete:
  label_proximity - find a label alias ("Claim #:"), then the pattern near it
  pattern_only    - every pattern match in the segment

Label proximity wins when available, because "$1,250.00" next to the words
"charge amount" is far stronger evidence than the first dollar figure in the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .config import CompiledConcern, CompiledField, Config
from .textprep import PreparedText
from .types import FieldValue, LineItem, Segment

# How far after a label to look for the value.
_LABEL_WINDOW = 60
# How far back to read when testing a label against reject_prefix.
_PREFIX_LOOKBACK = 12
# A label heading a LIST ("for the following dates of service?") is followed by
# lines that each start with a value. This is how far that run may extend.
_LIST_MAX_LINES = 12
# Exported tables often flatten as DOS / AMOUNT / NOTES followed by one value
# per line. Two non-value lines may therefore sit between successive values.
_LIST_MAX_GAP = 2
# A run of dashes/dots/underscores standing in for a label word, e.g.
# "DOS: 07/10/2026-----------------$1358.00".
_LEADER_RUN = re.compile(r"[-._]{3,}")


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


def _norm_claim_id(raw: str) -> str:
    """Preserve the carrier suffix separator for 7-digit + check-digit IDs."""
    normalized = _norm_upper_alnum(raw)
    carrier_suffix = re.fullmatch(r"(\d{7})[A-Z]+(\d{1,3})", normalized)
    if carrier_suffix:
        return f"{carrier_suffix.group(1)}-{carrier_suffix.group(2)}"
    if re.fullmatch(r"\d{8}", normalized):
        return f"{normalized[:-1]}-{normalized[-1]}"
    return normalized


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
    # Dots are in here to match us_date, which accepts them (SP-1.1-60).
    # Widening the pattern without widening this leaves "03.11.1994" matching
    # and then passing through unnormalized, which is worse than not matching.
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s)
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


_SERVICE_DATE_TOKEN = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)


def _norm_service_date(raw: str) -> str:
    """Normalize one service date or choose the earliest date in a range."""

    normalized_dates = [
        _norm_date_iso(match.group(0)) for match in _SERVICE_DATE_TOKEN.finditer(raw)
    ]
    iso_dates = [date for date in normalized_dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)]
    return min(iso_dates) if iso_dates else _norm_date_iso(raw)


NORMALIZERS = {
    "trim": _norm_trim,
    "upper_alnum": _norm_upper_alnum,
    "claim_id": _norm_claim_id,
    "digits": _norm_digits,
    "money": _norm_money,
    "date_iso": _norm_date_iso,
    "service_date": _norm_service_date,
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


def _label_spans(field: CompiledField, low: str) -> list[tuple[int, int, str]]:
    """Locate label aliases, longest first, without double-claiming a region.

    Aliases arrive sorted longest-first, so "claim id" claims its text before
    the bare "claim" can, and the shorter alias inside it is discarded. Without
    this the anchor lands mid-label and the value search starts too early.

    `reject_prefix` then drops labels that are qualified by the words in front
    of them: "Bill/Claim #" is the provider's own bill number, and "check
    amount" is a payment already issued, not the amount billed.
    """
    spans: list[tuple[int, int, str]] = []
    for alias in field.label_aliases:
        for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
            if any(m.start() < le and m.end() > ls for ls, le, _ in spans):
                continue
            before = low[max(0, m.start() - _PREFIX_LOOKBACK) : m.start()]
            if any(before.endswith(p) for p in field.reject_prefix):
                continue
            spans.append((m.start(), m.end(), alias))
    return spans


def _leader_spans(text: str) -> list[tuple[int, int, str]]:
    """Locate dash/dot/underscore leader runs, for fields opting into them.

    A provider sometimes connects one field's value to the next with a run of
    punctuation instead of a label word ("DOS: 07/10/2026-----------------
    $1358.00"). Treating the run as a label anchor lets the value search reuse
    the same window logic that follows a real label.
    """
    return [(m.start(), m.end(), "leader") for m in _LEADER_RUN.finditer(text)]


def _list_after(field: CompiledField, text: str, start: int):
    """Yield pattern matches from a short list or flattened table.

    Email #12 in the sample set reads "for the following dates of service?"
    and then five lines, each starting with a date and its amount. Another table
    exports DOS / AMOUNT / NOTES as separate rows, so two neighboring columns
    may sit between values. A match after such a gap must occupy the whole line;
    that keeps a note beginning with a call date from becoming another DOS.
    """
    if field.pattern is None:
        return
    blocked = _blocked_spans(field, text)
    pos = text.find("\n", start)
    if pos == -1:
        return
    nonblank = 0
    gap = 0
    while nonblank < _LIST_MAX_LINES:
        nl = text.find("\n", pos + 1)
        line = text[pos + 1 : nl if nl != -1 else len(text)]
        if not line.strip():
            if nl == -1:
                return
            pos = nl
            continue
        nonblank += 1
        stripped = line.lstrip()
        offset = pos + 1 + (len(line) - len(stripped))
        m = field.pattern.regex.match(stripped)
        accepted = False
        if m is not None:
            # Consecutive list rows may carry trailing columns on the same line.
            # Once a gap has occurred, however, only a standalone value is safe:
            # "5/3/26 called for status" is a note timestamp, not another DOS.
            trailing = stripped[m.end() :].strip()
            if gap == 0 or not trailing:
                raw = m.group(field.pattern.capture_group)
                ms, me = m.span(field.pattern.capture_group)
                s, e = offset + ms, offset + me
                if not any(s < be and e > bs for bs, be in blocked):
                    yield raw, (s, e)
                    accepted = True
                    gap = 0
        if not accepted:
            gap += 1
            if gap > _LIST_MAX_GAP:
                return
        if nl == -1:
            return
        pos = nl


def _blocked_spans(field: CompiledField, text: str) -> list[tuple[int, int]]:
    """Character ranges another pattern owns, which this field may not claim."""
    if field.exclude_pattern is None:
        return []
    return [span for _, span in field.exclude_pattern.finditer(text)]


def _standalone_value(field: CompiledField, line: str) -> str | None:
    """Return a value only when the complete trimmed line is that value."""
    if field.pattern is None:
        return None
    stripped = line.strip()
    match = field.pattern.regex.fullmatch(stripped)
    if match is None:
        return None
    start, end = match.span(field.pattern.capture_group)
    if any(start < be and end > bs for bs, be in _blocked_spans(field, stripped)):
        return None
    value = normalize_value(match.group(field.pattern.capture_group), field.normalizer)
    return value or None


def _is_standalone_label(field: CompiledField, line: str) -> bool:
    """Whether a short table header line is exactly one configured alias."""
    label = line.strip().lower().strip(" :-")
    return any(label == alias.strip().lower().strip(" :-") for alias in field.label_aliases)


def _collect(field: CompiledField, prepared: PreparedText, cfg: Config) -> list[Candidate]:
    if field.pattern is None:
        return []
    out: list[Candidate] = []
    for seg in prepared.segments:
        seg_w = _segment_priority(seg.kind)
        labels = _label_spans(field, seg.text.lower())
        if field.leader_prefix:
            labels = labels + _leader_spans(seg.text)
        claimed: list[tuple[int, int]] = []

        # --- label-anchored: search the window AFTER each label -------------
        # Searching the window rather than filtering global matches matters:
        # "Claim ID 100234567" makes a broad id pattern match "ID 100234567",
        # and there is no second, non-overlapping match to fall back to.
        for ls, le, alias in labels:
            window = seg.text[le : le + _LABEL_WINDOW]
            blocked = _blocked_spans(field, window)
            taken = 0
            line_end: int | None = None
            for raw, (ws, we) in field.pattern.finditer(window):
                if any(ws < be and we > bs for bs, be in blocked):
                    continue
                # A multi-value field keeps every figure on the label's own
                # line - "Billed Amount : 246.80 AND 1357.90" is two real
                # amounts - but stops at the newline, because the next line is
                # a different field ("Ref #: ...") and not another amount.
                if line_end is not None and ws > line_end:
                    break
                value = normalize_value(raw, field.normalizer)
                if not value:
                    continue
                s, e = le + ws, le + we
                proximity = 1.0 - (ws / (_LABEL_WINDOW + 1))
                out.append(
                    Candidate(
                        raw=raw,
                        value=value,
                        span=(seg.offset + s, seg.offset + e),
                        segment=seg.kind,
                        strategy=f"label_proximity:{alias}",
                        score=round(seg_w * (0.70 + 0.30 * proximity), 4),
                    )
                )
                claimed.append((s, e))
                taken += 1
                if not field.multi_value:
                    break  # nearest match after the label wins
                if line_end is None:
                    nl = window.find("\n", we)
                    line_end = len(window) if nl == -1 else nl

            # A label can head a LIST rather than point at one value:
            # "...for the following dates of service?" then a date per line.
            if field.multi_value and taken:
                for raw, (s, e) in _list_after(field, seg.text, le):
                    value = normalize_value(raw, field.normalizer)
                    if not value:
                        continue
                    out.append(
                        Candidate(
                            raw=raw,
                            value=value,
                            span=(seg.offset + s, seg.offset + e),
                            segment=seg.kind,
                            strategy=f"label_list:{alias}",
                            score=round(seg_w * 0.68, 4),
                        )
                    )
                    claimed.append((s, e))

        if field.require_label:
            # Shared pattern (DOS/DOI/DOB, claim_id/patient_account/TIN): an
            # unlabelled match cannot be attributed to one field, so drop it.
            # Reporting nothing beats reporting the wrong date.
            continue

        # --- unanchored fallback -------------------------------------------
        seg_blocked = _blocked_spans(field, seg.text)
        for raw, (s, e) in field.pattern.finditer(seg.text):
            if any(s < ce and e > cs for cs, ce in claimed):
                continue
            if any(s < le and e > ls for ls, le, _ in labels):
                continue
            if any(s < be and e > bs for bs, be in seg_blocked):
                continue
            value = normalize_value(raw, field.normalizer)
            if not value:
                continue
            position = 1.0 - min(s / max(len(seg.text), 1), 1.0)
            out.append(
                Candidate(
                    raw=raw,
                    value=value,
                    span=(seg.offset + s, seg.offset + e),
                    segment=seg.kind,
                    strategy="pattern_only",
                    score=round(seg_w * (0.30 + 0.15 * position), 4),
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

        # Document order, de-duplicated by value. Confirmed line-item rows restore
        # multiplicity below; doing it here would mistake a narrative that repeats
        # a DOS for another inquiry.
        ordered = sorted(pool, key=lambda c: c.span[0])
        all_values = tuple(dict.fromkeys(candidate.value for candidate in ordered))

        if f.multi_value:
            # Several dates of service in one email is the NORMAL case here,
            # not a contradiction to flag. Only a single-value field can be
            # made ambiguous by competing values.
            best = ordered[0]
        else:
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
            values=all_values if f.multi_value else (best.value,),
        )

    return fields, tuple(missing), tuple(ambiguous)


def build_line_items(
    concern: CompiledConcern, prepared: PreparedText, cfg: Config
) -> tuple[LineItem, ...]:
    """Pair the fields a concern declares as line items, one row per line.

    Only lines carrying a match for EVERY declared field count. "4/21/26 billed
    amount $527" is a row; a line with just a date is not, because pairing it
    with an amount from somewhere else would be an invention.
    """
    names = concern.line_item_fields
    if len(names) < 2:
        return ()
    by_name = {f.name: f for f in concern.fields if f.name in names}
    if len(by_name) != len(names):
        return ()

    items: list[LineItem] = []
    for seg in prepared.segments:
        if seg.kind == Segment.QUOTED_HISTORY.value and not cfg.search_quoted_history:
            continue
        for line in seg.text.split("\n"):
            if not line.strip():
                continue
            row: dict[str, str] = {}
            for name in names:
                field = by_name[name]
                if field.pattern is None:
                    continue
                blocked = _blocked_spans(field, line)
                for raw, (s, e) in field.pattern.finditer(line):
                    if any(s < be and e > bs for bs, be in blocked):
                        continue
                    value = normalize_value(raw, field.normalizer)
                    if value:
                        row[name] = value
                        break
            if len(row) == len(names):
                items.append(LineItem(fields=row, line=line.strip()[:120]))

        # Some email/Excel tables flatten each cell onto its own line:
        #
        #   DOS                AMOUNT BILLED              NOTES
        #   11/21/2041         $ 246.80                   called for status
        #
        # Pair only adjacent STANDALONE value lines beneath a compact set of
        # headers. Narrative lines reset a partial row, so values are never
        # paired across prose or guessed from their overall list positions.
        lines = seg.text.split("\n")
        header_end: int | None = None
        for start in range(len(lines)):
            found: dict[str, int] = {}
            for index in range(start, min(start + 5, len(lines))):
                for name in names:
                    if name not in found and _is_standalone_label(by_name[name], lines[index]):
                        found[name] = index
            if len(found) == len(names):
                header_end = max(found.values())
                break

        if header_end is not None:
            pending: dict[str, str] = {}
            pending_lines: list[str] = []
            nonblank = 0
            for line in lines[header_end + 1 :]:
                if not line.strip():
                    continue
                nonblank += 1
                if nonblank > _LIST_MAX_LINES:
                    break
                matches = [
                    (name, value)
                    for name in names
                    if (value := _standalone_value(by_name[name], line)) is not None
                ]
                if len(matches) != 1:
                    pending.clear()
                    pending_lines.clear()
                    continue
                name, value = matches[0]
                if name in pending:
                    pending.clear()
                    pending_lines.clear()
                pending[name] = value
                pending_lines.append(line.strip())
                if len(pending) == len(names):
                    items.append(
                        LineItem(
                            fields=dict(pending),
                            line=" | ".join(pending_lines)[:120],
                        )
                    )
                    pending.clear()
                    pending_lines.clear()
    # Two lines can repeat the same pair; keep the first of each.
    seen: set[tuple] = set()
    out: list[LineItem] = []
    for it in items:
        key = tuple(sorted(it.fields.items()))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return tuple(out)


def restore_line_item_multiplicity(
    fields: dict[str, FieldValue], line_items: tuple[LineItem, ...]
) -> dict[str, FieldValue]:
    """Restore equal values repeated on separate, confirmed inquiry rows.

    General field extraction intentionally de-duplicates the same normalized
    value because prose often repeats an identifier or DOS. A line item is
    stronger evidence: every row carries all declared fields, so two rows with
    the same billed amount are two inquiries and both must remain visible.
    """
    if not line_items:
        return fields

    names = {name for item in line_items for name in item.fields}
    for name in names:
        field = fields.get(name)
        if field is None or not field.values:
            continue
        paired = tuple(
            item.fields[name] for item in line_items if name in item.fields
        )
        remaining = list(field.values)
        for value in paired:
            if value in remaining:
                remaining.remove(value)
        combined = paired + tuple(remaining)
        if combined and combined != field.values:
            fields[name] = replace(field, value=combined[0], values=combined)
    return fields


def validate_line_items(
    fields: dict[str, FieldValue], line_items: tuple[LineItem, ...]
) -> tuple[LineItem, ...]:
    """Keep only pairs whose values passed the normal field extraction rules."""
    return tuple(
        item
        for item in line_items
        if all(
            name in fields and value in fields[name].values
            for name, value in item.fields.items()
        )
    )
