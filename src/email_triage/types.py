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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["span"] = list(self.span) if self.span else None
        d["candidates"] = list(self.candidates)
        return d


@dataclass(frozen=True)
class LayerScore:
    """Per-layer contribution for one concern. This is the teaching signal."""

    concern_id: str
    embedding: float = 0.0
    rules: float = 0.0
    structural: float = 0.0
    fused: float = 0.0
    saturation: float = 1.0
    decisive_hits: tuple[str, ...] = ()
    keyword_hits: tuple[str, ...] = ()
    gate_satisfied: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decisive_hits"] = list(self.decisive_hits)
        d["keyword_hits"] = list(self.keyword_hits)
        return d


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
    fields: dict[str, FieldValue] = field(default_factory=dict)
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
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "values": self.values,
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
