from __future__ import annotations

from email_triage import classify_email, to_json, to_plain_text
from email_triage.types import TriageStatus


def test_type_of_bill_is_recognised(rules_engine):
    r = rules_engine.classify(
        "Can you confirm the type of bill for claim WC1234567? Charge amount $1,250.00.",
        subject="Type of bill question",
    )
    assert r.status is TriageStatus.CLASSIFIED
    assert r.concern_id == "type_of_bill"
    assert r.values["claim_number"] == "WC1234567"
    assert r.values["charge_amount"] == "1250.00"
    assert r.is_complete


def test_chit_chat_is_not_forced_into_a_concern(rules_engine):
    r = rules_engine.classify("Thanks, received. I'll follow up next week.")
    assert r.status is TriageStatus.UNCLASSIFIED
    assert r.concern_id is None
    assert r.needs_review is True


def test_confidence_capped_without_embedding_layer(rules_engine):
    assert rules_engine.embeddings_active is False
    r = rules_engine.classify(
        "Type of bill for claim WC1234567, charge amount $1,250.00."
    )
    assert r.confidence <= 0.70
    assert "embeddings" not in r.explanation.layers_used


def test_force_review_leaves_scores_intact():
    from email_triage.engine import TriageEngine

    eng = TriageEngine(enable_embeddings=False, force_review=True)
    r = eng.classify("Type of bill for claim WC1234567, charge amount $1,250.00.")
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
                "name": "claim_number",
                "required": True,
                "pattern_ref": "claim_number_generic",
                "label_aliases": ["claim"],
            }],
        }],
    }
    p = tmp_path / "concerns.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    eng = TriageEngine(config_path=p, enable_embeddings=False)
    r = eng.classify("Please process the widget adjustment for claim WC1234567.")
    # 1 evidence text / k=4 => saturation 0.25
    assert r.explanation.scores[0].saturation == 0.25
    assert r.confidence <= 0.25
    assert r.needs_review is True


def test_determinism(rules_engine):
    body = "Type of bill for claim WC1234567, charge amount $1,250.00."
    a = rules_engine.classify(body).to_dict()
    b = rules_engine.classify(body).to_dict()
    for d in (a, b):
        d.pop("elapsed_ms")
    assert a == b


def test_module_level_function_works():
    """The plug-and-play path a host system uses."""
    r = classify_email(
        "Type of bill for claim WC1234567, charge amount $1,250.00.",
        subject="TOB",
    )
    assert r.concern_id == "type_of_bill"


def test_outputs_render(rules_engine):
    r = rules_engine.classify("Type of bill for claim WC1234567, charge amount $1,250.00.")
    text = to_plain_text(r)
    assert "TYPE OF CONCERN" not in text  # header wording lives in the UI
    assert "Type of concern" in text
    assert "Claim Number" in text

    import json

    payload = json.loads(to_json(r))
    assert payload["concern_id"] == "type_of_bill"
    assert payload["values"]["claim_number"] == "WC1234567"
    assert "explanation" in payload and "scores" in payload["explanation"]
