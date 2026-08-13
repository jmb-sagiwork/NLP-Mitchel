"""Fusion, decision, and the engine object.

Two behaviours here are deliberate and worth not "fixing":

1. Evidence shrinkage. A concern authored with one prototype cannot reach high
   confidence no matter how well it matches, so a thin taxonomy routes to human
   review instead of guessing confidently. Adding examples is what earns trust.

2. A missing required field never changes the label. It flags the gap and lowers
   confidence. Silently relabelling because a regex missed would be worse.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Mapping

from . import __version__ as ENGINE_VERSION
from .config import Config, load_config
from .extract import extract_fields
from .layers import (
    EmbeddingLayer,
    find_pattern_hits,
    rule_score,
    structural_score,
    try_load_embeddings,
)
from .textprep import prepare
from .types import Explanation, LayerScore, TriageResult, TriageStatus

# Cap applied when Layer 3 is unavailable: rules alone should not look certain.
NO_MODEL_CONFIDENCE_CAP = 0.70
MISSING_FIELD_PENALTY = 0.80


class TriageEngine:
    """Holds the compiled config and (if present) the embedding model.

    Construct once and reuse. Building an InferenceSession per call is expensive.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        model_dir: str | Path | None = None,
        *,
        thresholds: Mapping[str, float] | None = None,
        enable_embeddings: bool = True,
        force_review: bool = False,
    ) -> None:
        self.config: Config = load_config(Path(config_path) if config_path else None)
        if thresholds:
            self.config.thresholds.update(thresholds)
        self.force_review = force_review
        self._embeddings: EmbeddingLayer | None = (
            try_load_embeddings(self.config, model_dir) if enable_embeddings else None
        )

    # ---- introspection ---------------------------------------------------

    @property
    def embeddings_active(self) -> bool:
        return self._embeddings is not None

    @property
    def concern_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.config.enabled_concerns)

    @property
    def layers_used(self) -> tuple[str, ...]:
        base = ("structural", "rules")
        return ("embeddings", *base) if self.embeddings_active else base

    # ---- main path -------------------------------------------------------

    def classify(
        self, body: str, *, subject: str = "", message_key: str | None = None
    ) -> TriageResult:
        started = time.perf_counter()
        cfg = self.config
        prepared = prepare(body, subject)

        if not prepared.classify_text.strip():
            return TriageResult(
                status=TriageStatus.UNCLASSIFIED,
                concern_id=None,
                display_name=None,
                confidence=0.0,
                margin=0.0,
                needs_review=True,
                explanation=Explanation(
                    layers_used=self.layers_used, reason="empty_input"
                ),
                message_key=message_key,
                engine_version=ENGINE_VERSION,
                config_version=cfg.config_version,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )

        hits = find_pattern_hits(prepared, cfg.patterns)
        probs = (
            self._embeddings.probabilities(prepared.classify_text)
            if self._embeddings
            else {}
        )

        # Weights, renormalized if Layer 3 is missing.
        w = dict(cfg.fusion_weights)
        if not probs:
            w["embedding"] = 0.0
        total_w = sum(w.get(k, 0.0) for k in ("embedding", "rules", "structural")) or 1.0

        scores: list[LayerScore] = []
        for concern in cfg.enabled_concerns:
            s_struct, gate_ok = structural_score(concern, hits)
            rs = rule_score(concern, prepared, cfg)
            p_emb = probs.get(concern.id, 0.0)

            fused = (
                w.get("embedding", 0.0) * p_emb
                + w.get("rules", 0.0) * rs.score
                + w.get("structural", 0.0) * s_struct
            ) / total_w
            if not gate_ok and concern.gate_penalty:
                fused *= 1.0 - concern.gate_penalty

            sat = min(1.0, concern.evidence_count / max(cfg.evidence_saturation_k, 1))
            scores.append(
                LayerScore(
                    concern_id=concern.id,
                    embedding=round(p_emb, 4),
                    rules=round(rs.score, 4),
                    structural=round(s_struct, 4),
                    fused=round(fused, 4),
                    saturation=round(sat, 4),
                    decisive_hits=rs.decisive,
                    keyword_hits=rs.hits,
                    gate_satisfied=gate_ok,
                )
            )

        # The background class competes as a real option.
        bg_fused = (
            (w.get("embedding", 0.0) * probs.get(cfg.background_id, 0.0)) / total_w
            if probs
            else 0.0
        )
        if not probs:
            # With no embeddings, "nothing matched" is the background signal.
            best_rules = max((s.rules for s in scores), default=0.0)
            bg_fused = max(0.0, 0.35 - best_rules) / max(total_w, 1e-9) * w.get("rules", 0.3)

        ranked = sorted(scores, key=self._sort_key, reverse=True)
        top = ranked[0]
        second_fused = ranked[1].fused if len(ranked) > 1 else 0.0
        competitor = max(second_fused, bg_fused)
        margin = top.fused - competitor

        concern = cfg.concern(top.concern_id)
        assert concern is not None
        confidence = top.fused * top.saturation
        reason = "threshold"

        # A single decisive rule with a satisfied gate is trusted.
        decisive_owners = [s for s in scores if s.decisive_hits and s.gate_satisfied]
        if len(decisive_owners) == 1 and decisive_owners[0].concern_id == top.concern_id:
            confidence = max(confidence, 0.90 * top.saturation)
            reason = "decisive_rule"

        if not self.embeddings_active:
            confidence = min(confidence, NO_MODEL_CONFIDENCE_CAP)

        # Extraction runs after classification, then feeds back into status.
        fields, missing, ambiguous = extract_fields(concern, prepared, cfg)

        status, needs_review, reason = self._decide(
            confidence=confidence,
            margin=margin,
            bg_wins=bg_fused > top.fused,
            reason=reason,
        )

        if missing:
            confidence *= MISSING_FIELD_PENALTY
            needs_review = True
            if status is TriageStatus.CLASSIFIED and confidence < cfg.thresholds["accept"]:
                status = TriageStatus.AMBIGUOUS
                reason = "missing_required_field"
        if any(f.from_history for f in fields.values()):
            needs_review = True
        if ambiguous:
            needs_review = True

        if self.force_review:
            needs_review = True

        return TriageResult(
            status=status,
            concern_id=concern.id if status is not TriageStatus.UNCLASSIFIED else None,
            display_name=concern.display_name if status is not TriageStatus.UNCLASSIFIED else None,
            confidence=max(0.0, min(confidence, 1.0)),
            margin=margin,
            needs_review=needs_review,
            fields=fields,
            missing_fields=missing,
            ambiguous_fields=ambiguous,
            alternatives=tuple(
                (s.concern_id, round(s.fused * s.saturation, 4)) for s in ranked[:3]
            ),
            explanation=Explanation(
                layers_used=self.layers_used,
                reason=reason,
                scores=tuple(ranked),
                pattern_hits=tuple(h.to_dict() for h in hits),
                segments_seen=tuple(s.kind for s in prepared.segments),
            ),
            message_key=message_key,
            engine_version=ENGINE_VERSION,
            config_version=cfg.config_version,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def classify_many(self, items: Iterable[tuple[str, str]]) -> list[TriageResult]:
        return [self.classify(body, subject=subject) for body, subject in items]

    # ---- helpers ---------------------------------------------------------

    def _sort_key(self, s: LayerScore):
        concern = self.config.concern(s.concern_id)
        # Deterministic tie-break chain; no RNG anywhere in the engine.
        return (
            s.fused,
            len(s.decisive_hits),
            s.structural,
            s.rules,
            s.embedding,
            -(concern.priority if concern else 999),
            s.concern_id,
        )

    def _decide(
        self, *, confidence: float, margin: float, bg_wins: bool, reason: str
    ) -> tuple[TriageStatus, bool, str]:
        t = self.config.thresholds
        if reason == "decisive_rule" and confidence >= t["review"]:
            return TriageStatus.CLASSIFIED, False, reason
        if bg_wins:
            return TriageStatus.UNCLASSIFIED, True, "background_class"
        if confidence >= t["accept"] and margin >= t["margin"]:
            return TriageStatus.CLASSIFIED, False, "threshold"
        if confidence >= t["review"] and margin < t["margin"]:
            return TriageStatus.AMBIGUOUS, True, "low_margin"
        if confidence >= t["review"]:
            return TriageStatus.AMBIGUOUS, True, "low_confidence"
        return TriageStatus.UNCLASSIFIED, True, "below_review_threshold"


# --------------------------------------------------------------------------
# process-wide default
# --------------------------------------------------------------------------

_default: TriageEngine | None = None


def get_default_engine() -> TriageEngine:
    global _default
    if _default is None:
        _default = TriageEngine()
    return _default
