"""Extraction tests. All fixtures are synthetic; identifiers are invented."""

from __future__ import annotations

import pytest

from email_triage.extract import normalize_value
from email_triage.types import TriageStatus


@pytest.mark.parametrize(
    "raw,normalizer,expected",
    [
        ("$1,250.00", "money", "1250.00"),
        ("1250", "money", "1250.00"),
        ("$45", "money", "45.00"),
        ("wc-123 4567", "upper_alnum", "WC1234567"),
        ("INV-889231", "digits", "889231"),
        ("03/14/2026", "date_iso", "2026-03-14"),
        ("3-4-26", "date_iso", "2026-03-04"),
        ("2026-03-14", "date_iso", "2026-03-14"),
        ("Mar 14, 2026", "date_iso", "2026-03-14"),
        ("garbage", "date_iso", "garbage"),
    ],
)
def test_normalizers(raw, normalizer, expected):
    assert normalize_value(raw, normalizer) == expected


def test_label_proximity_beats_first_match(rules_engine):
    """Two dollar figures present; the one next to 'charge amount' must win."""
    body = (
        "Deductible is $50.00 on this file.\n"
        "Type of bill question for claim WC1234567.\n"
        "Charge amount: $1,250.00\n"
    )
    r = rules_engine.classify(body)
    assert r.concern_id == "type_of_bill"
    assert r.fields["charge_amount"].value == "1250.00"
    assert r.fields["charge_amount"].strategy.startswith("label_proximity")


def test_missing_required_field_is_reported_not_relabelled(rules_engine):
    """No claim number anywhere. The label must stay, the gap must surface."""
    body = "Can you tell me the type of bill for this charge? The amount is $612.75."
    r = rules_engine.classify(body)
    assert r.concern_id == "type_of_bill", "label must not change because a field is missing"
    assert "claim_number" in r.missing_fields
    assert r.needs_review is True
    assert r.fields["claim_number"].value is None


def test_bill_type_code_does_not_match_inside_currency(rules_engine):
    """Regression: '250' was being extracted out of '$1,250.00'."""
    body = "Type of bill for claim WC1234567, charge amount $1,250.00."
    r = rules_engine.classify(body)
    assert r.fields["bill_type_code"].value is None


def test_bill_type_code_still_matches_a_real_code(rules_engine):
    body = "Type of bill 0111 for claim WC1234567, charge amount $1,250.00."
    r = rules_engine.classify(body)
    assert r.fields["bill_type_code"].value == "0111"


def test_value_from_quoted_history_is_flagged(rules_engine):
    """Claim number only exists in the quoted reply chain."""
    body = (
        "Following up on the type of bill for this one, charge amount $980.50.\n"
        "\n"
        "On Mon, Mar 2, 2026 at 9:02 AM Adjuster wrote:\n"
        "> Opening claim WC7788991 for review.\n"
    )
    r = rules_engine.classify(body)
    assert r.fields["claim_number"].value == "WC7788991"
    assert r.fields["claim_number"].from_history is True
    assert r.needs_review is True


def test_spans_point_into_the_prepared_text(rules_engine):
    body = "Type of bill for claim WC1234567, charge amount $1,250.00."
    r = rules_engine.classify(body)
    span = r.fields["claim_number"].span
    assert span is not None
    assert body[span[0] : span[1]] == "WC1234567"


def test_empty_input_is_unclassified(rules_engine):
    r = rules_engine.classify("   \n  ")
    assert r.status is TriageStatus.UNCLASSIFIED
    assert r.explanation.reason == "empty_input"
