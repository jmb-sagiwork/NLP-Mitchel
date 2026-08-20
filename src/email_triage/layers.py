"""The two deterministic scoring layers: structure and phrase rules."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import CompiledConcern, CompiledPattern, CompiledReason, Config
from .textprep import PreparedText


# --------------------------------------------------------------------------
# Layer 1: structural
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternHit:
    pattern: str
    text: str
    span: tuple[int, int]
    segment: str

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "text": self.text,
            "span": [self.span[0], self.span[1]],
            "segment": self.segment,
        }


def find_pattern_hits(
    prepared: PreparedText, patterns: dict[str, CompiledPattern]
) -> tuple[PatternHit, ...]:
    """Run every library pattern over every segment. Offsets are absolute
    against prepared.full so the UI can highlight them."""
    hits: list[PatternHit] = []
    for seg in prepared.segments:
        for name, pat in patterns.items():
            for raw, (s, e) in pat.finditer(seg.text):
                hits.append(
                    PatternHit(
                        pattern=name,
                        text=raw,
                        span=(seg.offset + s, seg.offset + e),
                        segment=seg.kind,
                    )
                )
    return tuple(hits)


def structural_score(
    concern: CompiledConcern, hits: tuple[PatternHit, ...]
) -> tuple[float, bool]:
    """Fraction of the concern's field patterns that appear anywhere, plus
    whether the structural gate is satisfied."""
    present = {h.pattern for h in hits}
    wanted = {f.pattern.name for f in concern.fields if f.pattern is not None}
    score = len(wanted & present) / len(wanted) if wanted else 0.0
    gate_ok = True
    if concern.gate_patterns:
        gate_ok = any(p in present for p in concern.gate_patterns)
    return score, gate_ok


# --------------------------------------------------------------------------
# Layer 2: keyword and phrase rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleScore:
    score: float
    hits: tuple[str, ...]
    decisive: tuple[str, ...]


def rule_score(
    concern: CompiledConcern | CompiledReason, prepared: PreparedText, cfg: Config
) -> RuleScore:
    """Weighted keyword scoring over the newest message, squashed to 0..1.

    Segment weights mean a hit in the subject counts nearly as much as the body,
    while a hit in quoted history counts far less. Accepts a concern or a reason
    - both expose positive/negative/decisive, so one scorer serves both levels.
    """
    total = 0.0
    hits: list[str] = []
    for seg in prepared.segments:
        weight = cfg.segment_weights.get(seg.kind, 0.5)
        low = seg.text.lower()
        for rule in concern.positive:
            n = len(rule.matcher.findall(low)) if rule.matcher else low.count(rule.phrase)
            if n:
                # Repeats add sub-linearly; saying "type of bill" five times is
                # not five times the evidence.
                total += rule.weight * weight * (1.0 + math.log(n))
                hits.append(rule.phrase)
        for rule in concern.negative:
            n = len(rule.matcher.findall(low)) if rule.matcher else low.count(rule.phrase)
            if n:
                total -= rule.weight * weight * (1.0 + math.log(n))

    decisive: list[str] = []
    classify_low = prepared.classify_text.lower()
    for terms in concern.decisive:
        if all(t in classify_low for t in terms):
            decisive.append(" + ".join(terms))

    # tanh squash: saturating, monotonic, and never negative.
    score = math.tanh(max(total, 0.0) / 4.0)
    return RuleScore(score=score, hits=tuple(dict.fromkeys(hits)), decisive=tuple(decisive))
