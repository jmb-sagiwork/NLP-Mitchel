"""Public result types. Kept dependency-free so any host can consume them."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class TriageStatus(str, Enum):
    """Outcome of a classification. Never a silent guess."""

    CLASSIFIED = "CLASSIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    UNCLASSIFIED = "UNCLASSIFIED"
    ERROR = "ERROR"


class Segment(str, Enum):
    SUBJECT = "subject"
    NEWEST_BODY = "newest_body"
    SIGNATURE = "signature"
    QUOTED_HISTORY = "quoted_history"


@dataclass(frozen=True)
class FieldValue:
    """One extracted field, with enough provenance to audit or retrain on."""

    name: str
    display_name: str
    value: str | None
    raw: str | None = None
    span: tuple[int, int] | None = None
    segment: str = Segment.NEWEST_BODY.value
    strategy: str = "pattern_only"
    confidence: float = 0.0
    required: bool = False
    from_history: bool = False
    candidates: tuple[str, ...] = ()
    # Every distinct value found for this field, in document order. One email
    # routinely covers several dates of service and several billed amounts, so
    # collapsing to one would discard most of what the sender asked about.
    # `value` stays the first, so single-value callers keep working.
    values: tuple[str, ...] = ()

    @property
    def all_values(self) -> tuple[str, ...]:
        """Every extracted value, with a fallback for older/single-value callers."""
        if self.values:
            return self.values
        return (self.value,) if self.value is not None else ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["span"] = list(self.span) if self.span else None
        d["candidates"] = list(self.candidates)
        d["values"] = list(self.values)
        return d


@dataclass(frozen=True)
class LayerScore:
    """Per-layer contribution for one concern. This is the teaching signal."""

    concern_id: str
    rules: float = 0.0
    structural: float = 0.0
    fused: float = 0.0
    decisive_hits: tuple[str, ...] = ()
    keyword_hits: tuple[str, ...] = ()
    gate_satisfied: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decisive_hits"] = list(self.decisive_hits)
        d["keyword_hits"] = list(self.keyword_hits)
        return d


@dataclass(frozen=True)
class LineItem:
    """One row of a multi-line bill: a date of service and what it was billed.

    Emails here arrive as "4/21/26 billed amount $527" repeated per line, or as
    a DOS / AMOUNT BILLED table. Reporting five dates and five amounts as two
    flat lists loses the pairing, and the pairing is the part an agent needs.
    """

    fields: dict[str, str] = field(default_factory=dict)
    line: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"fields": dict(self.fields), "line": self.line}


@dataclass(frozen=True)
class Explanation:
    layers_used: tuple[str, ...] = ()
    reason: str = ""
    scores: tuple[LayerScore, ...] = ()
    pattern_hits: tuple[dict[str, Any], ...] = ()
    segments_seen: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers_used": list(self.layers_used),
            "reason": self.reason,
            "scores": [s.to_dict() for s in self.scores],
            "pattern_hits": [dict(h) for h in self.pattern_hits],
            "segments_seen": list(self.segments_seen),
        }


@dataclass(frozen=True)
class TriageResult:
    """The single object a host system consumes."""

    status: TriageStatus
    concern_id: str | None
    display_name: str | None
    confidence: float
    margin: float
    needs_review: bool
    # Sub-classification within the concern. None when the concern declares no
    # reasons, or when no reason scored above its threshold.
    reason_id: str | None = None
    reason_display_name: str | None = None
    reason_confidence: float = 0.0
    reason_alternatives: tuple[tuple[str, float], ...] = ()
    fields: dict[str, FieldValue] = field(default_factory=dict)
    # Populated only when the concern declares line_item_fields and the email
    # actually pairs them on one line. Empty is the normal single-bill case.
    line_items: tuple[LineItem, ...] = ()
    missing_fields: tuple[str, ...] = ()
    ambiguous_fields: tuple[str, ...] = ()
    alternatives: tuple[tuple[str, float], ...] = ()
    explanation: Explanation = field(default_factory=Explanation)
    message_key: str | None = None
    engine_version: str = ""
    config_version: str = ""
    elapsed_ms: float = 0.0
    error_code: str | None = None

    # ---- convenience accessors -------------------------------------------

    @property
    def values(self) -> dict[str, str | None]:
        """Flat {field_name: value} mapping for simple callers."""
        return {k: v.value for k, v in self.fields.items()}

    @property
    def is_complete(self) -> bool:
        return self.status is TriageStatus.CLASSIFIED and not self.missing_fields

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "concern_id": self.concern_id,
            "display_name": self.display_name,
            "confidence": round(self.confidence, 4),
            "margin": round(self.margin, 4),
            "needs_review": self.needs_review,
            "reason_id": self.reason_id,
            "reason_display_name": self.reason_display_name,
            "reason_confidence": round(self.reason_confidence, 4),
            "reason_alternatives": [
                [r, round(s, 4)] for r, s in self.reason_alternatives
            ],
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "values": self.values,
            "line_items": [li.to_dict() for li in self.line_items],
            "missing_fields": list(self.missing_fields),
            "ambiguous_fields": list(self.ambiguous_fields),
            "alternatives": [[c, round(s, 4)] for c, s in self.alternatives],
            "explanation": self.explanation.to_dict(),
            "message_key": self.message_key,
            "engine_version": self.engine_version,
            "config_version": self.config_version,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "error_code": self.error_code,
        }
