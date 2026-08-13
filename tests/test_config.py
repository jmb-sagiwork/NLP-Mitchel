from __future__ import annotations

import json

import pytest

from email_triage.config import check_config, load_config
from email_triage.errors import ConfigError


def test_shipped_config_compiles():
    cfg = load_config()
    assert cfg.concerns
    assert "type_of_bill" in {c.id for c in cfg.concerns}
    assert cfg.patterns


def test_type_of_bill_requires_claim_and_amount():
    cfg = load_config()
    concern = cfg.concern("type_of_bill")
    assert concern is not None
    assert set(concern.required_field_names) == {"claim_number", "charge_amount"}


def test_fusion_weights_sum_to_one():
    cfg = load_config()
    total = sum(cfg.fusion_weights[k] for k in ("embedding", "rules", "structural"))
    assert total == pytest.approx(1.0)


def test_label_aliases_sorted_longest_first():
    """'claim number' must be tried before 'claim', or the shorter alias wins
    and the proximity score is computed from the wrong anchor."""
    cfg = load_config()
    concern = cfg.concern("type_of_bill")
    aliases = concern.fields[0].label_aliases
    assert list(aliases) == sorted(aliases, key=len, reverse=True)


def test_check_config_flags_draft_concerns():
    warnings = check_config()
    assert any("draft" in w for w in warnings)


def test_unknown_pattern_ref_is_rejected(tmp_path):
    cfg_path = tmp_path / "concerns.json"
    cfg_path.write_text(json.dumps({
        "config_version": "test",
        "concerns": [{
            "id": "broken",
            "display_name": "Broken",
            "fields": [{"name": "x", "pattern_ref": "does_not_exist"}],
        }],
    }), encoding="utf-8")
    with pytest.raises(ConfigError, match="does_not_exist"):
        load_config(cfg_path)


def test_duplicate_concern_id_is_rejected(tmp_path):
    cfg_path = tmp_path / "concerns.json"
    cfg_path.write_text(json.dumps({
        "config_version": "test",
        "concerns": [
            {"id": "dup", "display_name": "A"},
            {"id": "dup", "display_name": "B"},
        ],
    }), encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(cfg_path)
