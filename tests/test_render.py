"""The training-record shape is a contract: a later training run reads it."""

from __future__ import annotations

import json

from email_triage.render import (
    DATASET_SCHEMA_VERSION,
    append_training_record,
    build_training_record,
    text_fingerprint,
)

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
