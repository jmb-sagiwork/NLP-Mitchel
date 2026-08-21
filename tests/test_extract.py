"""Extraction tests. All fixtures are synthetic; every identifier is invented."""

from __future__ import annotations

import pytest

from email_triage.extract import normalize_value
from email_triage.types import TriageStatus

# One message carrying all seven fields, each explicitly labelled.
FULL = (
    "Bill status please.\n"
    "Claim ID: WC7788991\n"
    "DOS: 05/01/2026\n"
    "DOI: 04/02/2026\n"
    "DOB: 11/30/1979\n"
    "Prov TIN: 98-7654321\n"
    "Patient Account: PA5512399\n"
    "Expected amount: $3,410.55\n"
)


@pytest.mark.parametrize(
    "raw,normalizer,expected",
    [
        ("$1,250.00", "money", "1250.00"),
        ("1250", "money", "1250.00"),
        ("$45", "money", "45.00"),
        ("wc-123 4567", "upper_alnum", "WC1234567"),
        ("98-7654321", "digits", "987654321"),
        ("03/14/2026", "date_iso", "2026-03-14"),
        ("3-4-26", "date_iso", "2026-03-04"),
        ("2026-03-14", "date_iso", "2026-03-14"),
        ("Mar 14, 2026", "date_iso", "2026-03-14"),
        ("garbage", "date_iso", "garbage"),
    ],
)
def test_normalizers(raw, normalizer, expected):
    assert normalize_value(raw, normalizer) == expected


def test_all_seven_fields_extract(rules_engine):
    r = rules_engine.classify(FULL)
    assert r.values == {
        "claim_id": "WC7788991",
        "date_of_service": "2026-05-01",
        "date_of_injury": "2026-04-02",
        "date_of_birth": "1979-11-30",
        "provider_tin": "987654321",
        "patient_account": "PA5512399",
        "expected_amount": "3410.55",
    }


def test_three_date_fields_are_not_confused(rules_engine):
    """DOS, DOI and DOB share one regex. Each must get its own date, not the
    first date in the message."""
    r = rules_engine.classify(FULL)
    assert r.values["date_of_service"] == "2026-05-01"
    assert r.values["date_of_injury"] == "2026-04-02"
    assert r.values["date_of_birth"] == "1979-11-30"


def test_unlabelled_date_is_not_guessed(rules_engine):
    """A bare date cannot be attributed to DOS, DOI or DOB, so report none."""
    r = rules_engine.classify(
        "Bill status for claim ID WC1234567. We sent this on 03/14/2026."
    )
    assert r.values["date_of_service"] is None
    assert r.values["date_of_injury"] is None
    assert r.values["date_of_birth"] is None


def test_label_word_is_not_swallowed_into_the_value(rules_engine):
    """'Claim ID 100234567' must yield 100234567, not ID100234567 - a broad id
    pattern will otherwise eat the label's trailing word."""
    r = rules_engine.classify("Bill status for Claim ID 100234567, DOS 03/14/2026.")
    assert r.values["claim_id"] == "100234567"


def test_longer_alias_wins_over_shorter_one(rules_engine):
    r = rules_engine.classify("Bill status. Claim Number: ABC-00456789. DOS: 02/02/2026.")
    assert r.values["claim_id"] == "ABC00456789"


def test_carrier_marker_claim_id_normalizes_to_check_digit_format(rules_engine):
    r = rules_engine.classify(
        "Bill status. Claim: 4184847CMT1. "
        "Date of service: 05/30/2026. Billed amount: $3,842.00"
    )

    assert r.values["claim_id"] == "4184847-1"


def test_date_of_service_range_uses_earliest_date(rules_engine):
    r = rules_engine.classify(
        "Bill status. Claim: 4184847CMT1. "
        "Date(s) of service as billed: 06/02/2026-05/30/2026. "
        "Billed amount: $3,842.00"
    )

    assert r.values["date_of_service"] == "2026-05-30"
    assert r.fields["date_of_service"].values == ("2026-05-30",)


def test_pasted_claim_status_email_extracts_required_fields(rules_engine):
    body = """From: sender@example.com
Sent: Mon Jul 27 2026 17:21:18 GMT-0400 (Eastern Daylight Time)
To: claims@example.com
Subject: CLAIM STATUS

Hello,

I have a claim that I need to obtain bill status.
Claim: 4184847CMT1
Date of accident: 05/02/2026
Date(s) of service as billed: 05/30/2026-05/30/2026
Billed amount(s): $3,842.00
Please email a copy of the EOB.
"""

    r = rules_engine.classify(body)

    assert r.concern_id == "bill_status"
    assert r.values["claim_id"] == "4184847-1"
    assert r.values["date_of_service"] == "2026-05-30"
    assert r.values["expected_amount"] == "3842.00"
    assert r.missing_fields == ()
    assert r.fields["claim_id"].from_history is False


def test_provider_tin_prefers_hyphenated_form(rules_engine):
    r = rules_engine.classify(FULL)
    assert r.values["provider_tin"] == "987654321"
    assert r.fields["provider_tin"].raw == "98-7654321"


def test_amount_is_found_from_prose_not_only_from_a_label_line(rules_engine):
    """"The charge was $1,250.00" is a label too - "charge" is an alias."""
    r = rules_engine.classify(
        "Bill status for claim ID WC1234567. The charge was $1,250.00."
    )
    assert r.values["expected_amount"] == "1250.00"


def test_unlabelled_amount_is_refused(rules_engine):
    """expected_amount became required in config 0.3.0, so it sets require_label.

    A real email carries several figures - billed, paid, check amount. Grabbing
    an unanchored one would silently satisfy a REQUIRED field with the wrong
    number and stop the email routing for review, which is worse than a blank.
    """
    r = rules_engine.classify(
        "Bill status for claim ID WC1234567, DOS 03/14/2026. See $1,250.00 below."
    )
    assert r.values["expected_amount"] is None
    assert "expected_amount" in r.missing_fields
    assert r.needs_review is True
    assert r.line_items == ()


def test_amount_is_not_taken_from_a_payment_already_issued(rules_engine):
    """"Paid" and "check amount" are guarded by reject_prefix (SP-1.1-60)."""
    r = rules_engine.classify(
        "Bill status for claim ID WC1234567, DOS 03/14/2026.\n"
        "Billed amount: $1,250.00\nPaid amount: $310.45\n"
    )
    assert r.values["expected_amount"] == "1250.00"


def test_missing_required_field_is_reported_not_relabelled(rules_engine):
    """No claim id anywhere. The label must stay, the gap must surface."""
    r = rules_engine.classify("Can you check the status of this bill on file?")
    assert r.concern_id == "bill_status", "label must not change over a missing field"
    assert "claim_id" in r.missing_fields
    assert r.needs_review is True
    assert r.fields["claim_id"].value is None


def test_value_from_quoted_history_is_flagged(rules_engine):
    body = (
        "Following up on the bill status for this one.\n"
        "\n"
        "On Mon, Mar 2, 2026 at 9:02 AM Adjuster wrote:\n"
        "> Opening Claim ID WC7788991 for review.\n"
    )
    r = rules_engine.classify(body)
    assert r.values["claim_id"] == "WC7788991"
    assert r.fields["claim_id"].from_history is True
    assert r.needs_review is True


def test_spans_point_into_the_prepared_text(rules_engine):
    body = "Bill status for Claim ID WC1234567, DOS 01/15/2026."
    r = rules_engine.classify(body)
    span = r.fields["claim_id"].span
    assert span is not None
    assert body[span[0] : span[1]] == "WC1234567"


def test_empty_input_is_unclassified(rules_engine):
    r = rules_engine.classify("   \n  ")
    assert r.status is TriageStatus.UNCLASSIFIED
    assert r.explanation.reason == "empty_input"
