from __future__ import annotations

import pytest

from email_triage import classify_email, to_json, to_plain_text
from email_triage.types import TriageStatus


def test_bill_status_is_recognised(rules_engine):
    r = rules_engine.classify(
        "Can you check the status of the bill for Claim ID WC1234567, DOS 03/14/2026?",
        subject="Bill status follow up",
    )
    assert r.status is TriageStatus.CLASSIFIED
    assert r.concern_id == "bill_status"
    assert r.values["claim_id"] == "WC1234567"


def test_claim_information_is_recognised(rules_engine):
    r = rules_engine.classify(
        "Claim number request - we need the claim number before we can bill. "
        "Patient account ACCT-99213, DOI 01/09/2026."
    )
    assert r.concern_id == "claim_information"


def test_chit_chat_is_not_forced_into_a_concern(rules_engine):
    r = rules_engine.classify("Thanks, received. I'll follow up next week.")
    assert r.status is TriageStatus.UNCLASSIFIED
    assert r.concern_id is None
    assert r.reason_id is None
    assert r.needs_review is True


@pytest.mark.parametrize(
    "body,expected_reason",
    [
        ("This bill completed processing and was denied. Claim ID WC1234567.",
         "completed_processing_denied"),
        ("Not a bill on file for Claim ID WC1234567, DOS 01/15/2026.",
         "not_a_bill_on_file"),
        ("No claim on file; missing information. Claim ID WC5551234.",
         "no_claim_on_file_missing_information"),
    ],
)
def test_reason_sub_classification(rules_engine, body, expected_reason):
    r = rules_engine.classify(body)
    assert r.concern_id == "bill_status"
    assert r.reason_id == expected_reason
    assert r.reason_display_name


def test_reason_is_absent_when_the_email_states_none(rules_engine):
    """An inbound question carries no disposition. Reporting no reason is
    correct; guessing one would be worse."""
    r = rules_engine.classify(
        "Checking the status of the bill for Claim ID 100234567, DOS 03/14/2026."
    )
    assert r.concern_id == "bill_status"
    assert r.reason_id is None


def test_decisive_rule_overrides_the_fused_ranking(rules_engine):
    """A field dump reads semantically like claim_information, but an explicit
    'bill status' is decisive and must win outright."""
    r = rules_engine.classify(
        "Bill status please. Claim ID: WC7788991. DOS: 05/01/2026. "
        "DOI: 04/02/2026. DOB: 11/30/1979. Patient Account: PA5512399."
    )
    assert r.concern_id == "bill_status"
    assert r.explanation.reason == "decisive_rule"


def test_confidence_capped_without_embedding_layer(rules_engine):
    assert rules_engine.embeddings_active is False
    r = rules_engine.classify("Bill status for Claim ID WC1234567.")
    assert r.confidence <= 0.70
    assert "embeddings" not in r.explanation.layers_used


def test_force_review_leaves_scores_intact():
    from email_triage.engine import TriageEngine

    eng = TriageEngine(enable_embeddings=False, force_review=True)
    r = eng.classify("Bill status for Claim ID WC1234567, DOS 03/14/2026.")
    assert r.needs_review is True
    assert r.status is TriageStatus.CLASSIFIED, "force_review must not change the label"
    assert r.confidence > 0


def test_evidence_shrinkage_caps_a_thin_concern(tmp_path):
    """A concern with one prototype and no examples must not look confident."""
    import json
    import shutil

    from email_triage.config import PATTERNS_PATH
    from email_triage.engine import TriageEngine

    shutil.copy(PATTERNS_PATH, tmp_path / "patterns.library.json")
    cfg = {
        "config_version": "thin-test",
        "defaults": {
            "fusion_weights": {"embedding": 0.0, "rules": 0.8, "structural": 0.2},
            "evidence_saturation_k": 4,
        },
        "concerns": [{
            "id": "thin",
            "display_name": "Thin Concern",
            "prototypes": ["A single prototype and nothing else."],
            "keyword_rules": {"positive": [{"phrase": "widget adjustment", "weight": 5.0}]},
            "fields": [{
                "name": "claim_id",
                "required": True,
                "pattern_ref": "claim_id",
                "label_aliases": ["claim"],
            }],
        }],
    }
    p = tmp_path / "concerns.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    eng = TriageEngine(config_path=p, enable_embeddings=False)
    r = eng.classify("Please process the widget adjustment for claim WC1234567.")
    assert r.explanation.scores[0].saturation == 0.25
    assert r.confidence <= 0.25
    assert r.needs_review is True


def test_determinism(rules_engine):
    body = "Bill status for Claim ID WC1234567, DOS 03/14/2026."
    a = rules_engine.classify(body).to_dict()
    b = rules_engine.classify(body).to_dict()
    for d in (a, b):
        d.pop("elapsed_ms")
    assert a == b


def test_module_level_function_works():
    """The plug-and-play path a host system uses."""
    r = classify_email(
        "Bill status for Claim ID WC1234567, DOS 03/14/2026.",
        subject="Bill status",
    )
    assert r.concern_id == "bill_status"


def test_outputs_render(rules_engine):
    r = rules_engine.classify("Bill status for Claim ID WC1234567, DOS 03/14/2026.")
    text = to_plain_text(r)
    assert "Type of concern" in text
    assert "Claim ID" in text

    import json

    payload = json.loads(to_json(r))
    assert payload["concern_id"] == "bill_status"
    assert payload["values"]["claim_id"] == "WC1234567"
    assert "reason_id" in payload
    assert "explanation" in payload and "scores" in payload["explanation"]


def test_reason_is_not_invented_without_supporting_wording(engine):
    """Softmax always hands its mass to something. An inbound question states no
    disposition, so no reason may be emitted - with embeddings ON, which is the
    configuration where this failure actually appeared."""
    r = engine.classify(
        "Bill status for claim ID WC1234567. We sent this over on 03/14/2026."
    )
    assert r.concern_id == "bill_status"
    assert r.reason_id is None
