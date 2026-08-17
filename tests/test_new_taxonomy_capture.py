"""Naming a concern the taxonomy does not have yet.

The Teach bar's dropdown can only offer what `concerns.json` already contains,
so before SP-1.1-56 a reviewer meeting a genuinely new category could say only
`__other__` - which records that the answer was wrong without recording what
the answer was. These tests cover the capture path that replaced it.
"""

from __future__ import annotations

from email_triage.render import (
    append_training_record,
    build_training_record,
    slugify_label,
)
from email_triage_ui.proposals import collect, format_report

BODY = "Bill status for Claim ID WC1234567, DOS 03/14/2026."


def test_slugify_turns_a_typed_name_into_a_config_id():
    assert slugify_label("Refund Request") == "refund_request"
    assert slugify_label("  Appeal / Reconsideration  ") == "appeal_reconsideration"
    assert slugify_label("EOB (paper)") == "eob_paper"
    assert slugify_label("!!!") == ""


def test_proposed_concern_becomes_the_label_and_is_flagged(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, proposed_concern="Refund Request")
    label = rec["label"]
    assert label["concern_id"] == "refund_request"
    assert label["proposed_concern"] == {
        "id": "refund_request",
        "display_name": "Refund Request",
    }
    assert label["is_new_taxonomy"] is True
    assert label["verified_by_human"] is True
    assert label["was_prediction_correct"] is False
    # The engine's own answer survives for error analysis.
    assert rec["prediction"]["concern_id"] == "bill_status"


def test_proposed_reason_is_independent_of_the_concern(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, proposed_reason="Awaiting medical records")
    label = rec["label"]
    assert label["concern_id"] == r.concern_id  # concern was right
    assert label["reason_id"] == "awaiting_medical_records"
    assert label["proposed_concern"] is None
    assert label["is_new_taxonomy"] is True


def test_an_ordinary_correction_is_not_flagged_as_new_taxonomy(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, corrected_concern_id="claim_information")
    assert rec["label"]["is_new_taxonomy"] is False
    assert rec["label"]["proposed_concern"] is None


def test_proposals_report_counts_and_hides_email_text(rules_engine, tmp_path):
    r = rules_engine.classify(BODY)
    path = tmp_path / "dataset.jsonl"
    for _ in range(2):
        append_training_record(
            build_training_record(
                BODY, "", r, proposed_concern="Refund Request",
                reviewer_note="third time this week",
            ),
            path,
        )
    append_training_record(
        build_training_record(BODY, "", r, proposed_reason="Awaiting records"), path
    )

    data = collect(path)
    assert data["rows"] == 3
    assert data["concerns"]["refund_request"]["count"] == 2
    assert data["reasons"]["awaiting_records"]["count"] == 1
    assert data["concerns"]["refund_request"]["predicted_instead"]["bill_status"] == 2

    text = format_report(data)
    assert "refund_request" in text
    assert "third time this week" in text
    # The point of the report is that it can leave the machine. The body cannot.
    assert BODY not in text
    assert "WC1234567" not in text


def test_report_survives_a_half_written_row(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text('{"label": {}}\n{"label": {"proposed_conc\n', encoding="utf-8")
    data = collect(path)
    assert data["rows"] == 1


def test_report_on_a_missing_dataset_is_not_an_error(tmp_path):
    data = collect(tmp_path / "nope.jsonl")
    assert data["rows"] == 0
    assert "(none yet)" in format_report(data)
