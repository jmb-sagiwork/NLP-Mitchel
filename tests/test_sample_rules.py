"""Rules derived from the 15 real inbound emails (SP-1.1-60).

Every case here is a SHAPE that appeared in samples.xlsx, re-keyed with
invented identifiers - every claim number, account number, date and amount
below is made up. samples.xlsx itself holds real PHI and is gitignored; nothing
copied out of it may carry a real value into this repo.

The narrative for each is in SAMPLE_RULES.md; this is the executable half, so
a later config edit that undoes one of them fails loudly.
"""

from __future__ import annotations

import pytest

from email_triage.types import TriageStatus


# --------------------------------------------------------------------------
# required fields - the user's ruling, config 0.3.0
# --------------------------------------------------------------------------


def test_bill_status_requires_claim_dos_and_amount(rules_engine):
    concern = rules_engine.config.concern("bill_status")
    required = {f.name for f in concern.fields if f.required}
    assert required == {"claim_id", "date_of_service", "expected_amount"}
    amount = next(f for f in concern.fields if f.name == "expected_amount")
    assert amount.display_name == "Expected Amount"


def test_claim_information_requires_nothing(rules_engine):
    """That concern IS the sender asking to be given the claim number.

    Requiring claim_id here would flag every such email by definition.
    """
    concern = rules_engine.config.concern("claim_information")
    assert [f.name for f in concern.fields if f.required] == []


def test_missing_amount_routes_to_review_without_relabelling(rules_engine):
    r = rules_engine.classify(
        "Please provide bill status.\nClaim #: 4477881-2\nDOS: 03/14/2026\n"
    )
    assert r.concern_id == "bill_status", "the label must not move over a gap"
    assert "expected_amount" in r.missing_fields
    assert r.needs_review is True


# --------------------------------------------------------------------------
# claim id shape - 6 of 14 samples were silently truncated before this
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Bill status. Claim #: 4477881-1\nDOS: 03/14/2026\nBilled amount: $10.00", "44778811"),
        ("Bill status. Claim number: 35700021\nDOS: 03/14/2026\nBilled: $10.00", "35700021"),
        ("Bill status. Your Claim #: A0091447\nDOS: 03/14/2026\nBilled: $10.00", "A0091447"),
        ("Bill status. Clm: 5512206-1\nDOS: 03/14/2026\nBilled: $10.00", "55122061"),
    ],
)
def test_claim_id_suffix_is_not_dropped(rules_engine, text, expected):
    """AmTrust-style ids carry a -N suffix. The stem alone is a different claim."""
    assert rules_engine.classify(text).values["claim_id"] == expected


def test_provider_own_bill_number_is_not_read_as_the_claim_id(rules_engine):
    """"Bill/Claim #" and "Ref #" sit beside the real claim number."""
    r = rules_engine.classify(
        "Bill status please.\n"
        "Claim number: 35700021\n"
        "DOS: 03/14/2026\n"
        "Charged amount: $2,288.60\n"
        "Ref #: 9900771-4\n"
        "Bill/Claim #: S990088100201\n"
    )
    assert r.values["claim_id"] == "35700021"


# --------------------------------------------------------------------------
# patient account - the pattern used to match any word
# --------------------------------------------------------------------------


def test_patient_account_information_is_below_extracts_nothing(rules_engine):
    """The literal word INFORMATION was being returned as an account number."""
    r = rules_engine.classify(
        "Bill status. Claim # 5514902\nDOS: 09/14/2026\nBilled: $812.75\n"
        "Patient account information is below.\n"
    )
    assert r.values["patient_account"] is None


def test_patient_account_with_a_letter_prefix_is_kept(rules_engine):
    r = rules_engine.classify(
        "Bill status. Claim # 5514902\nDOS: 09/14/2026\nBilled: $812.75\n"
        "Account ref# E00009911402\n"
    )
    assert r.values["patient_account"] == "E00009911402"


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------


def test_dotted_dates_are_read(rules_engine):
    """Providers write 03.11.1994 as often as 03/11/1994."""
    r = rules_engine.classify(
        "Please provide a claim number for the following:\nDOI: 02.04.2026\n"
    )
    assert r.values["date_of_injury"] == "2026-02-04"


def test_a_date_typed_into_the_amount_line_is_refused(rules_engine):
    """One sample literally reads "Amount: $08/19/2026". It is not an amount."""
    r = rules_engine.classify(
        "bill status\nYour Claim #: A0091447\nAmount: $08/19/2026\nDOS: 08/19/2026\n"
    )
    assert r.values["expected_amount"] is None
    assert "expected_amount" in r.missing_fields


def test_unlabelled_date_is_never_claimed(rules_engine):
    """DOS, DOI and DOB share one pattern, so an unlabelled date is unattributable."""
    r = rules_engine.classify(
        "Please provide a claim number for the following:\nPatient 03.11.1994\n"
    )
    assert r.values["date_of_birth"] is None


# --------------------------------------------------------------------------
# concern routing - "claim status" means the bill, not the claim number
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject, body",
    [
        ("Claim Status", "Would you please provide claim status for claim# 5510087-1?"),
        ("Status of Bill", "Please provide status of the following bill listed below."),
        ("Bill Payment Inquiry", "Seeking bill payment status updates for the claimant."),
        ("Receipt-Bill status", "Please provide the date of receipt and status update."),
        ("CLAIM INQUIRY", "Can you provide status of the attached appeal that was mailed?"),
        ("Number- 5511340-1", "Can you provide us with a copy of the EOB for the date of service below?"),
    ],
)
def test_status_questions_route_to_bill_status(rules_engine, subject, body):
    r = rules_engine.classify(body, subject=subject)
    assert r.concern_id == "bill_status"


def test_asking_to_be_given_a_claim_number_routes_to_claim_information(rules_engine):
    r = rules_engine.classify(
        "If able, please provide a claim number for the following:\nDOI: 02.04.2026\n",
        subject="Claim number request",
    )
    assert r.concern_id == "claim_information"
    assert r.status is not TriageStatus.UNCLASSIFIED


def test_a_quoted_claim_number_label_is_not_a_claim_information_signal(rules_engine):
    """Nearly every email quotes "Claim Number:". It is a field label, not intent."""
    r = rules_engine.classify(
        "Can you please provide us with a copy of the EOB for the date of "
        "service below?\nClaim Number - 5511340-1\nDate Of Injury: 09/13/2025\n",
        subject="Number- 5511340-1",
    )
    assert r.concern_id == "bill_status"


def test_eob_copy_request_overrides_embedding_similarity(engine):
    """An explicit EOB request is bill disposition work, even when the field
    dump resembles the claim-information prototypes to MiniLM."""
    r = engine.classify(
        "Can you provide us with a copy of the EOB for the date of service below?\n"
        "Claim Number - ZX8042719-6\nDOS: 12/19/2042\nBilled Amt: $7,654.32",
        subject="Number - ZX8042719-6",
    )
    assert r.concern_id == "bill_status"
    assert r.explanation.reason == "decisive_rule"


# --------------------------------------------------------------------------
# repeated DOS / billed-amount tables - config 0.4.0
# --------------------------------------------------------------------------


def test_vertical_bill_table_keeps_all_values_and_their_pairs(rules_engine):
    """Flattened tables put DOS, amount and notes on separate lines. A date at
    the start of a narrative note must not become an extra date of service."""
    r = rules_engine.classify(
        "Bill status for Claim # ZX8042719-6.\n"
        "DOS\n\nAMOUNT BILLED\n\nNOTES\n\n"
        "11/21/2041\n\n$                     246.80\n\n"
        "11/22/41 called for status; DOS 11/21/2041 remains under review.\n\n"
        "11/24/2041\n\n$                     1,357.90\n\n"
        "11/25/41 follow-up note without another billed line."
    )
    assert r.fields["date_of_service"].values == ("2041-11-21", "2041-11-24")
    assert r.fields["expected_amount"].values == ("246.80", "1357.90")
    assert [item.fields for item in r.line_items] == [
        {"date_of_service": "2041-11-21", "expected_amount": "246.80"},
        {"date_of_service": "2041-11-24", "expected_amount": "1357.90"},
    ]


def test_same_line_bill_rows_keep_all_values_and_their_pairs(rules_engine):
    r = rules_engine.classify(
        "Bill status for Claim # ZX8042719-6.\n"
        "DOS 11/21/2041 billed amount $246.80\n"
        "DOS 11/24/2041 billed amount $1,357.90\n"
    )
    assert r.fields["date_of_service"].values == ("2041-11-21", "2041-11-24")
    assert r.fields["expected_amount"].values == ("246.80", "1357.90")
    assert len(r.line_items) == 2


def test_multiple_claim_status_inquiries_keep_five_pairs(engine):
    """A single message may ask about several bills on the same claim."""
    r = engine.classify(
        "Would you please provide claim status for Claim # ZX8042719-6; "
        "DOB 12/30/1988; DOI 10/13/2043 for the following dates of service?\n\n"
        "11/21/2043 billed amount $246\n"
        "11/24/2043 billed amount $357\n"
        "11/27/2043 billed amount $357\n"
        "12/01/2043 billed amount $579\n"
        "12/04/2043 billed amount $680\n\n"
        "Please email a copy of the EOB."
    )
    assert r.concern_id == "bill_status"
    assert r.explanation.reason == "decisive_rule"
    assert r.fields["date_of_service"].values == (
        "2043-11-21", "2043-11-24", "2043-11-27", "2043-12-01", "2043-12-04"
    )
    assert r.fields["expected_amount"].values == (
        "246.00", "357.00", "357.00", "579.00", "680.00"
    )
    assert len(r.line_items) == 5
