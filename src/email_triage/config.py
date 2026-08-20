"""Config loading, validation, and compilation.

Everything a non-programmer edits lives in resources/concerns.json. This module
turns it into compiled, validated objects once, and caches them.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError, PatternError

def _resources_dir() -> Path:
    """Locate bundled resources whether running from source or frozen.

    PyInstaller unpacks --add-data into sys._MEIPASS; from source they sit
    beside this module.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "email_triage" / "resources"
        if bundled.is_dir():
            return bundled
    return Path(__file__).resolve().parent / "resources"


RESOURCES = _resources_dir()
CONCERNS_PATH = RESOURCES / "concerns.json"
PATTERNS_PATH = RESOURCES / "patterns.library.json"

_FLAGS = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "VERBOSE": re.VERBOSE,
}


# --------------------------------------------------------------------------
# compiled shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledPattern:
    name: str
    regex: re.Pattern[str]
    capture_group: int = 0
    description: str = ""

    def finditer(self, text: str):
        """Yield (matched_text, (start, end)) for the configured capture group."""
        group = self.capture_group
        for m in self.regex.finditer(text):
            raw = m.group(group)
            if raw is None:
                continue
            yield raw, m.span(group)


@dataclass(frozen=True)
class CompiledField:
    name: str
    display_name: str
    required: bool
    pattern: CompiledPattern | None
    label_aliases: tuple[str, ...]
    normalizer: str
    # When several fields share one pattern - DOS, DOI and DOB are all dates -
    # a bare pattern match cannot be attributed to any of them. Such a field
    # accepts label-anchored candidates only, and reports nothing otherwise.
    require_label: bool = False
    # Lowercase strings that disqualify a label when they sit immediately in
    # front of it. "Bill/Claim #" and "Ref #" are the provider's own numbering,
    # not the carrier claim id, and both turn up beside a real "Claim number"
    # in the same email (SP-1.1-60).
    reject_prefix: tuple[str, ...] = ()
    # Collect every distinct value instead of only the best one. Set on the
    # fields that legitimately repeat within one email (SP-1.1-61).
    multi_value: bool = False
    # Name of another library pattern whose matches this field must not claim.
    # Dates and money overlap once us_date accepts dots: "03.11.1994" offers
    # "03.11" to currency_amount. The date wins and the money match is dropped.
    exclude_pattern: CompiledPattern | None = None


@dataclass(frozen=True)
class KeywordRule:
    phrase: str
    weight: float
    whole_word: bool = False
    matcher: re.Pattern[str] | None = None


@dataclass(frozen=True)
class CompiledReason:
    """A sub-classification within a concern.

    Deliberately shares the attribute names rule_score() reads, so the same
    scorer works on concerns and reasons without a second implementation.
    """

    id: str
    display_name: str
    positive: tuple[KeywordRule, ...]
    negative: tuple[KeywordRule, ...]
    decisive: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class CompiledConcern:
    id: str
    display_name: str
    enabled: bool
    draft: bool
    priority: int
    description_internal: str
    positive: tuple[KeywordRule, ...]
    negative: tuple[KeywordRule, ...]
    decisive: tuple[tuple[str, ...], ...]
    gate_patterns: tuple[str, ...]
    gate_penalty: float
    fields: tuple[CompiledField, ...]
    reasons: tuple[CompiledReason, ...] = ()
    # Field names that repeat together on one line ("4/21/26 billed $527").
    # Declaring them lets extraction keep the pairing instead of flattening it
    # into two independent lists (SP-1.1-61).
    line_item_fields: tuple[str, ...] = ()

    @property
    def required_field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.required)

    def reason(self, reason_id: str) -> CompiledReason | None:
        for r in self.reasons:
            if r.id == reason_id:
                return r
        return None


@dataclass(frozen=True)
class Config:
    config_version: str
    schema_version: str
    thresholds: dict[str, float]
    fusion_weights: dict[str, float]
    search_quoted_history: bool
    history_decay: float
    segment_weights: dict[str, float]
    concerns: tuple[CompiledConcern, ...]
    patterns: dict[str, CompiledPattern] = field(default_factory=dict)

    def concern(self, concern_id: str) -> CompiledConcern | None:
        for c in self.concerns:
            if c.id == concern_id:
                return c
        return None

    @property
    def enabled_concerns(self) -> tuple[CompiledConcern, ...]:
        return tuple(c for c in self.concerns if c.enabled)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _compile_regex(name: str, spec: dict[str, Any]) -> CompiledPattern:
    raw = spec.get("regex")
    if not isinstance(raw, str) or not raw:
        raise PatternError(f"pattern '{name}': missing or empty 'regex'")
    flags = 0
    for f in spec.get("flags", []):
        if f not in _FLAGS:
            raise PatternError(f"pattern '{name}': unknown flag '{f}'")
        flags |= _FLAGS[f]
    try:
        compiled = re.compile(raw, flags)
    except re.error as exc:
        raise PatternError(f"pattern '{name}': invalid regex ({exc})") from exc
    group = int(spec.get("capture_group", 0))
    if group > compiled.groups:
        raise PatternError(
            f"pattern '{name}': capture_group {group} but regex has {compiled.groups} group(s)"
        )
    return CompiledPattern(
        name=name,
        regex=compiled,
        capture_group=group,
        description=spec.get("description", ""),
    )


def load_patterns(path: Path | None = None) -> dict[str, CompiledPattern]:
    path = path or PATTERNS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"pattern library not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"pattern library is not valid JSON: {exc}") from exc
    out: dict[str, CompiledPattern] = {}
    for name, spec in (data.get("patterns") or {}).items():
        out[name] = _compile_regex(name, spec)
    if not out:
        raise ConfigError("pattern library contains no patterns")
    return out


def _compile_keyword(spec: dict[str, Any], concern_id: str) -> KeywordRule:
    phrase = spec.get("phrase")
    if not isinstance(phrase, str) or not phrase.strip():
        raise ConfigError(f"concern '{concern_id}': keyword rule missing 'phrase'")
    phrase = phrase.strip().lower()
    whole = bool(spec.get("whole_word", False))
    body = re.escape(phrase)
    matcher = re.compile(rf"\b{body}\b" if whole else body, re.IGNORECASE)
    return KeywordRule(
        phrase=phrase,
        weight=float(spec.get("weight", 1.0)),
        whole_word=whole,
        matcher=matcher,
    )


def _compile_field(
    spec: dict[str, Any], concern_id: str, patterns: dict[str, CompiledPattern]
) -> CompiledField:
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"concern '{concern_id}': a field is missing 'name'")
    ref = spec.get("pattern_ref")
    pattern: CompiledPattern | None = None
    if ref is not None:
        if ref not in patterns:
            raise ConfigError(
                f"concern '{concern_id}', field '{name}': pattern_ref '{ref}' "
                f"is not in patterns.library.json"
            )
        pattern = patterns[ref]
    elif "pattern" in spec:
        # Allowed but discouraged: config authors should reference the library.
        pattern = _compile_regex(f"{concern_id}.{name}.inline", spec)
    aliases = tuple(
        str(a).strip().lower() for a in spec.get("label_aliases", []) if str(a).strip()
    )
    # Longest alias first so "claim number" wins over "claim".
    aliases = tuple(sorted(aliases, key=len, reverse=True))
    reject_prefix = tuple(
        str(r).strip().lower() for r in spec.get("reject_prefix", []) if str(r).strip()
    )
    exclude_ref = spec.get("exclude_pattern_ref")
    exclude_pattern: CompiledPattern | None = None
    if exclude_ref is not None:
        if exclude_ref not in patterns:
            raise ConfigError(
                f"concern '{concern_id}', field '{name}': exclude_pattern_ref "
                f"'{exclude_ref}' is not in patterns.library.json"
            )
        exclude_pattern = patterns[exclude_ref]
    multi_value = bool(spec.get("multi_value", False))
    require_label = bool(spec.get("require_label", False))
    if require_label and not aliases:
        raise ConfigError(
            f"concern '{concern_id}', field '{name}': require_label is true but "
            f"no label_aliases are declared, so the field can never match"
        )
    return CompiledField(
        name=name,
        display_name=spec.get("display_name", name.replace("_", " ").title()),
        required=bool(spec.get("required", False)),
        pattern=pattern,
        label_aliases=aliases,
        normalizer=spec.get("normalizer", "trim"),
        require_label=require_label,
        reject_prefix=reject_prefix,
        exclude_pattern=exclude_pattern,
        multi_value=multi_value,
    )


def _compile_decisive(rules: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    out: list[tuple[str, ...]] = []
    for d in rules.get("decisive", []):
        terms = tuple(str(t).strip().lower() for t in d.get("all_of", []) if str(t).strip())
        if terms:
            out.append(terms)
    return tuple(out)


def _compile_reason(spec: dict[str, Any], concern_id: str) -> CompiledReason:
    rid = spec.get("id")
    if not isinstance(rid, str) or not rid:
        raise ConfigError(f"concern '{concern_id}': a reason is missing 'id'")
    rules = spec.get("keyword_rules") or {}
    return CompiledReason(
        id=rid,
        display_name=spec.get("display_name", rid),
        positive=tuple(_compile_keyword(r, f"{concern_id}.{rid}")
                       for r in rules.get("positive", [])),
        negative=tuple(_compile_keyword(r, f"{concern_id}.{rid}")
                       for r in rules.get("negative", [])),
        decisive=_compile_decisive(rules),
    )


def _compile_concern(spec: dict[str, Any], patterns: dict[str, CompiledPattern]) -> CompiledConcern:
    cid = spec.get("id")
    if not isinstance(cid, str) or not cid:
        raise ConfigError("a concern is missing 'id'")
    rules = spec.get("keyword_rules") or {}
    decisive = list(_compile_decisive(rules))

    reasons = tuple(_compile_reason(r, cid) for r in spec.get("reasons", []))
    seen_r: set[str] = set()
    for r in reasons:
        if r.id in seen_r:
            raise ConfigError(f"concern '{cid}': duplicate reason id '{r.id}'")
        seen_r.add(r.id)

    # Roll a reason's keywords up as weaker evidence for its parent concern.
    # "Not a bill on file" is a Bill Status reason, so those words are also
    # evidence the item IS a Bill Status - without this the concern level sees
    # nothing and the message falls through to UNCLASSIFIED. Rolling up in code
    # keeps "adding a reason" a pure JSON edit with no duplicated phrases.
    rollup = float(spec.get("reason_rollup_weight", 0.5))
    own_positive = tuple(_compile_keyword(r, cid) for r in rules.get("positive", []))
    rolled = tuple(
        KeywordRule(
            phrase=kw.phrase,
            weight=kw.weight * rollup,
            whole_word=kw.whole_word,
            matcher=kw.matcher,
        )
        for reason in reasons
        for kw in reason.positive
    )
    gate = spec.get("structural_gate") or {}
    gate_patterns = tuple(str(p) for p in gate.get("require_any_pattern", []))
    for p in gate_patterns:
        if p not in patterns:
            raise ConfigError(
                f"concern '{cid}': structural_gate references unknown pattern '{p}'"
            )
    return CompiledConcern(
        id=cid,
        display_name=spec.get("display_name", cid),
        enabled=bool(spec.get("enabled", True)),
        draft=bool(spec.get("draft", False)),
        priority=int(spec.get("priority", 100)),
        description_internal=spec.get("description_internal", ""),
        positive=own_positive + rolled,
        negative=tuple(_compile_keyword(r, cid) for r in rules.get("negative", [])),
        decisive=tuple(decisive),
        gate_patterns=gate_patterns,
        gate_penalty=float(gate.get("penalty_if_absent", 0.0)),
        fields=tuple(_compile_field(f, cid, patterns) for f in spec.get("fields", [])),
        line_item_fields=tuple(str(f) for f in spec.get("line_item_fields", [])),
        reasons=reasons,
    )


def load_config(
    concerns_path: Path | None = None, patterns_path: Path | None = None
) -> Config:
    """Read, validate, and compile the config. Raises ConfigError with a
    human-readable location on any problem."""
    concerns_path = concerns_path or CONCERNS_PATH
    patterns = load_patterns(patterns_path)
    try:
        data = json.loads(concerns_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"concerns config not found: {concerns_path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"concerns config is not valid JSON: {exc}") from exc

    defaults = data.get("defaults") or {}
    concerns = tuple(_compile_concern(c, patterns) for c in data.get("concerns", []))
    if not concerns:
        raise ConfigError("concerns config declares no concerns")

    seen: set[str] = set()
    for c in concerns:
        if c.id in seen:
            raise ConfigError(f"duplicate concern id '{c.id}'")
        seen.add(c.id)

    weights = dict(defaults.get("fusion_weights") or {})
    for key in ("rules", "structural"):
        weights.setdefault(key, 0.0)

    return Config(
        config_version=str(data.get("config_version", "0")),
        schema_version=str(data.get("schema_version", "0")),
        thresholds={
            "accept": 0.55,
            "margin": 0.12,
            "review": 0.35,
            "field_ambiguity_delta": 0.10,
            **(defaults.get("thresholds") or {}),
        },
        fusion_weights=weights,
        search_quoted_history=bool(defaults.get("search_quoted_history", True)),
        history_decay=float(defaults.get("history_decay", 0.9)),
        segment_weights={
            "subject": 0.9,
            "newest_body": 1.0,
            "signature": 0.3,
            "quoted_history": 0.55,
            **(defaults.get("segment_weights") or {}),
        },
        concerns=concerns,
        patterns=patterns,
    )


def check_config() -> list[str]:
    """Lint the shipped config. Returns a list of human-readable warnings."""
    warnings: list[str] = []
    cfg = load_config()
    for c in cfg.concerns:
        if c.draft:
            warnings.append(f"{c.id}: marked draft=true; replace with the real taxonomy")
        if not c.fields:
            warnings.append(f"{c.id}: declares no fields, so nothing will be extracted")
        if not c.required_field_names:
            warnings.append(f"{c.id}: has no required fields; completeness cannot be checked")
    total = sum(cfg.fusion_weights.get(k, 0.0) for k in ("rules", "structural"))
    if abs(total - 1.0) > 1e-6:
        warnings.append(f"fusion_weights sum to {total:.3f}, expected 1.0")
    return warnings
