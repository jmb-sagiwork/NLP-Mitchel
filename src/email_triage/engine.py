"""Fusion, decision, and the engine object.

One behaviour here is deliberate and worth not "fixing": a missing required
field never changes the label. It flags the gap and lowers
   confidence. Silently relabelling because a regex missed would be worse.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Mapping

from . import __version__ as ENGINE_VERSION
from .config import Config, load_config
from .extract import (
    build_line_items,
    extract_fields,
    restore_line_item_multiplicity,
    validate_line_items,
)
from .layers import find_pattern_hits, rule_score, structural_score
from .textprep import prepare
from .types import Explanation, LayerScore, TriageResult, TriageStatus

MISSING_FIELD_PENALTY = 0.80


class TriageEngine:
    """Deterministic regex, structural, and phrase-rule triage engine."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        thresholds: Mapping[str, float] | None = None,
        force_review: bool = False,
    ) -> None:
        self.config: Config = load_config(Path(config_path) if config_path else None)
        if thresholds:
            self.config.thresholds.update(thresholds)
        self.force_review = force_review

    # ---- introspection ---------------------------------------------------

    @property
    def concern_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.config.enabled_concerns)

    @property
    def layers_used(self) -> tuple[str, ...]:
        return ("structural", "rules")

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
        w = dict(cfg.fusion_weights)
        total_w = sum(w.get(k, 0.0) for k in ("rules", "structural")) or 1.0

        scores: list[LayerScore] = []
        for concern in cfg.enabled_concerns:
            s_struct, gate_ok = structural_score(concern, hits)
            rs = rule_score(concern, prepared, cfg)

            fused = (
                w.get("rules", 0.0) * rs.score
                + w.get("structural", 0.0) * s_struct
            ) / total_w
            if not gate_ok and concern.gate_penalty:
                fused *= 1.0 - concern.gate_penalty

            scores.append(
                LayerScore(
                    concern_id=concern.id,
                    rules=round(rs.score, 4),
                    structural=round(s_struct, 4),
                    fused=round(fused, 4),
                    decisive_hits=rs.decisive,
                    keyword_hits=rs.hits,
                    gate_satisfied=gate_ok,
                )
            )

        # With no rule evidence, ordinary correspondence competes as the
        # background signal instead of being forced into a tracked concern.
        best_rules = max((s.rules for s in scores), default=0.0)
        bg_fused = (
            max(0.0, 0.35 - best_rules)
            / max(total_w, 1e-9)
            * w.get("rules", 0.75)
        )

        ranked = sorted(scores, key=self._sort_key, reverse=True)

        # A decisive rule must be able to OVERRIDE the fused ranking, not merely
        # boost a concern that was already winning. "Decisive" means explicit
        # configured intent outranks an otherwise close fused score.
        decisive_owners = [s for s in scores if s.decisive_hits and s.gate_satisfied]
        is_decisive = len(decisive_owners) == 1
        if is_decisive:
            winner = decisive_owners[0]
            ranked = [winner] + [s for s in ranked if s.concern_id != winner.concern_id]

        top = ranked[0]
        second_fused = ranked[1].fused if len(ranked) > 1 else 0.0
        competitor = max(second_fused, bg_fused)
        margin = top.fused - competitor

        concern = cfg.concern(top.concern_id)
        assert concern is not None
        confidence = top.fused
        reason = "threshold"

        if is_decisive:
            confidence = max(confidence, 0.90)
            margin = max(margin, cfg.thresholds["margin"])
            reason = "decisive_rule"

        # Sub-classify the reason within the winning concern.
        reason_id, reason_name, reason_conf, reason_alts = self._classify_reason(
            concern, prepared
        )

        # Extraction runs after classification, then feeds back into status.
        fields, missing, ambiguous = extract_fields(concern, prepared, cfg)
        line_items = validate_line_items(
            fields, build_line_items(concern, prepared, cfg)
        )
        fields = restore_line_item_multiplicity(fields, line_items)

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
            reason_id=reason_id if status is not TriageStatus.UNCLASSIFIED else None,
            reason_display_name=(
                reason_name if status is not TriageStatus.UNCLASSIFIED else None
            ),
            reason_confidence=reason_conf,
            reason_alternatives=reason_alts,
            fields=fields,
            line_items=line_items,
            missing_fields=missing,
            ambiguous_fields=ambiguous,
            alternatives=tuple(
                (s.concern_id, round(s.fused, 4)) for s in ranked[:3]
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

    def _classify_reason(
        self, concern, prepared
    ) -> tuple[str | None, str | None, float, tuple[tuple[str, float], ...]]:
        """Pick the reason within an already-decided concern.

        Same fusion shape as the concern level, minus the structural layer -
        reasons are distinguished by wording, not by which identifiers appear.
        Returns (None, None, 0.0, alts) when nothing clears the threshold, so a
        weak reason is reported as absent rather than guessed.
        """
        if not concern.reasons:
            return None, None, 0.0, ()

        cfg = self.config
        scored: list[tuple[str, float]] = []
        rule_scores: dict[str, float] = {}
        for reason in concern.reasons:
            rs = rule_score(reason, prepared, cfg)
            rule_scores[reason.id] = rs.score
            fused = rs.score
            if rs.decisive:
                fused = max(fused, 0.85)
            scored.append((reason.id, fused))

        scored.sort(key=lambda x: (-x[1], x[0]))
        alts = tuple(scored[:3])
        best_id, best_score = scored[0]

        # Softmax always hands its mass to something. An inbound question states
        # no disposition at all, so without this an ordinary "what is the status
        # of this bill?" gets labelled "not a bill on file". No supporting
        # wording means no reason.
        if rule_scores.get(best_id, 0.0) <= 0.0:
            return None, None, 0.0, alts

        if best_score < cfg.thresholds.get("reason_accept", 0.45):
            return None, None, round(best_score, 4), alts
        reason = concern.reason(best_id)
        return best_id, (reason.display_name if reason else best_id), round(best_score, 4), alts

    def _sort_key(self, s: LayerScore):
        concern = self.config.concern(s.concern_id)
        # Deterministic tie-break chain; no RNG anywhere in the engine.
        return (
            s.fused,
            len(s.decisive_hits),
            s.structural,
            s.rules,
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
