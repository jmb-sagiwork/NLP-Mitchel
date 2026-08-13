from __future__ import annotations

import json

import pytest

from email_triage.config import check_config, load_config
from email_triage.errors import ConfigError

SHARED_DATE_FIELDS = ("date_of_service", "date_of_injury", "date_of_birth")


def test_shipped_config_compiles():
    cfg = load_config()
    assert {c.id for c in cfg.concerns} == {"bill_status", "claim_information"}
    assert cfg.patterns


def test_bill_status_declares_all_seven_extraction_fields():
    cfg = load_config()
    concern = cfg.concern("bill_status")
    assert concern is not None
    assert {f.name for f in concern.fields} == {
        "claim_id",
        "date_of_service",
        "patient_account",
        "provider_tin",
        "expected_amount",
        "date_of_injury",
        "date_of_birth",
    }


def test_every_field_sharing_a_pattern_requires_a_label():
    """DOS, DOI and DOB all resolve to us_date. Without require_label the first
    date in the body would be assigned to all three."""
    cfg = load_config()
    for concern in cfg.concerns:
        by_pattern: dict[str, list[str]] = {}
        for f in concern.fields:
            if f.pattern is not None:
                by_pattern.setdefault(f.pattern.name, []).append(f.name)
        for pattern_name, names in by_pattern.items():
            if len(names) > 1:
                for f in concern.fields:
                    if f.name in names:
                        assert f.require_label, (
                            f"{concern.id}.{f.name} shares pattern "
                            f"'{pattern_name}' with {names} but does not "
                            f"require a label"
                        )


def test_date_fields_specifically_require_labels():
    cfg = load_config()
    concern = cfg.concern("bill_status")
    for name in SHARED_DATE_FIELDS:
        f = next(f for f in concern.fields if f.name == name)
        assert f.require_label is True
        assert f.label_aliases


def test_bill_status_has_the_four_reasons():
    cfg = load_config()
    concern = cfg.concern("bill_status")
    assert {r.id for r in concern.reasons} == {
        "completed_processing",
        "completed_processing_denied",
        "not_a_bill_on_file",
        "no_claim_on_file_missing_information",
    }


def test_claim_information_has_its_reason():
    cfg = load_config()
    concern = cfg.concern("claim_information")
    assert {r.id for r in concern.reasons} == {"claim_number_request"}


def test_fusion_weights_sum_to_one():
    cfg = load_config()
    total = sum(cfg.fusion_weights[k] for k in ("embedding", "rules", "structural"))
    assert total == pytest.approx(1.0)


def test_label_aliases_sorted_longest_first():
    """'claim id' must be tried before 'claim', or the anchor lands mid-label."""
    cfg = load_config()
    concern = cfg.concern("bill_status")
    for f in concern.fields:
        aliases = list(f.label_aliases)
        assert aliases == sorted(aliases, key=len, reverse=True)


def test_no_draft_concerns_remain():
    """The placeholder taxonomy has been replaced with the real one."""
    cfg = load_config()
    assert not [c.id for c in cfg.concerns if c.draft]


def test_require_label_without_aliases_is_rejected(tmp_path):
    cfg_path = tmp_path / "concerns.json"
    cfg_path.write_text(json.dumps({
        "config_version": "test",
        "concerns": [{
            "id": "broken",
            "display_name": "Broken",
            "fields": [{
                "name": "x", "pattern_ref": "us_date", "require_label": True,
            }],
        }],
    }), encoding="utf-8")
    with pytest.raises(ConfigError, match="require_label"):
        load_config(cfg_path)


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


def test_duplicate_reason_id_is_rejected(tmp_path):
    cfg_path = tmp_path / "concerns.json"
    cfg_path.write_text(json.dumps({
        "config_version": "test",
        "concerns": [{
            "id": "c", "display_name": "C",
            "reasons": [{"id": "r", "display_name": "A"},
                        {"id": "r", "display_name": "B"}],
        }],
    }), encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate reason"):
        load_config(cfg_path)


def test_check_config_runs_clean_enough():
    """Warnings are allowed, but nothing may raise."""
    assert isinstance(check_config(), list)
