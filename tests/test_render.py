"""The training-record shape is a contract: a later training run reads it."""

from __future__ import annotations

import json

from email_triage.render import (
    DATASET_SCHEMA_VERSION,
    append_training_record,
    build_training_record,
    text_fingerprint,
    to_explanation_text,
    to_plain_text,
)
from email_triage_ui.app import _field_tree_rows

BODY = "Bill status for Claim ID WC1234567, DOS 03/14/2026."


def test_unverified_record_mirrors_the_prediction(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r)
    assert rec["dataset_schema_version"] == DATASET_SCHEMA_VERSION
    assert rec["label"]["concern_id"] == r.concern_id
    assert rec["label"]["verified_by_human"] is False
    assert rec["label"]["was_prediction_correct"] is None
    assert rec["input"]["body"] == BODY


def test_correction_marks_the_row_verified_and_wrong(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(
        BODY, "", r, corrected_concern_id="claim_information", reviewer_note="mislabelled"
    )
    assert rec["label"]["concern_id"] == "claim_information"
    assert rec["label"]["verified_by_human"] is True
    assert rec["label"]["was_prediction_correct"] is False
    # The original prediction is retained for error analysis.
    assert rec["prediction"]["concern_id"] == "bill_status"


def test_confirmation_marks_the_row_verified_and_right(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, reviewer_note="looks right")
    assert rec["label"]["verified_by_human"] is True
    assert rec["label"]["was_prediction_correct"] is True


def test_record_is_json_serialisable_and_appends(rules_engine, tmp_path):
    r = rules_engine.classify(BODY)
    path = tmp_path / "nested" / "dataset.jsonl"
    for _ in range(3):
        append_training_record(build_training_record(BODY, "", r), path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line)


def test_fingerprint_is_stable_and_not_reversible():
    a = text_fingerprint("hello")
    assert a == text_fingerprint("hello")
    assert a != text_fingerprint("hello ")
    assert "hello" not in a


def test_repeated_inquiries_render_every_value_and_pair(rules_engine):
    r = rules_engine.classify(
        "Bill status for Claim # ZX8042719-6 for the following dates of service.\n"
        "11/21/2041 billed amount $357.00\n"
        "11/24/2041 billed amount $357.00\n"
    )

    plain = to_plain_text(r)
    why = to_explanation_text(r)
    for value in ("2041-11-21", "2041-11-24", "357.00"):
        assert value in plain
        assert value in why
    assert r.fields["expected_amount"].values == ("357.00", "357.00")
    assert "PAIRED INQUIRIES" in plain
    assert "(none stated in this email)" not in plain
    assert "(none stated in this email)" not in why
    assert "\nReason          :" not in plain
    assert "2. REASON" not in why

    rows = _field_tree_rows(r)
    labels = [values[0] for values, _tag in rows]
    assert "DOS (Date of Service) (1/2)" in labels
    assert "DOS (Date of Service) (2/2)" in labels
    assert "Expected Amount (1/2)" in labels
    assert "Expected Amount (2/2)" in labels
    assert all("Input - Expected Amount" not in label for label in labels)
    amounts = [
        values[1]
        for values, _tag in rows
        if values[0].startswith("Expected Amount")
    ]
    assert amounts == ["357.00", "357.00"]


def test_stated_reason_still_appears_in_human_outputs(rules_engine):
    r = rules_engine.classify(
        "This bill completed processing and was denied. Claim ID ZX8042719-6. "
        "DOS 11/21/2041. Billed amount $357.00."
    )
    assert r.reason_id == "completed_processing_denied"
    assert "Reason          : Completed processing and denied" in to_plain_text(r)
    assert "2. REASON  ->  Completed processing and denied" in to_explanation_text(r)
