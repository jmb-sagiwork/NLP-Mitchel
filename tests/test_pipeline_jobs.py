from __future__ import annotations

from email_triage.types import FieldValue, LineItem, TriageResult, TriageStatus

from mitchel_pipeline.jobs import deduplicate_jobs, jobs_from_result
from mitchel_pipeline.models import SmartAdvisorJob


def result(*, line_items=(), dos_values=(), amount_values=()) -> TriageResult:
    return TriageResult(
        status=TriageStatus.CLASSIFIED,
        concern_id="bill_status",
        display_name="Bill Status",
        confidence=0.9,
        margin=0.5,
        needs_review=False,
        fields={
            "claim_id": FieldValue("claim_id", "Claim ID", "WC123"),
            "date_of_service": FieldValue(
                "date_of_service",
                "DOS",
                dos_values[0] if dos_values else None,
                values=tuple(dos_values),
            ),
            "expected_amount": FieldValue(
                "expected_amount",
                "Expected Amount",
                amount_values[0] if amount_values else None,
                values=tuple(amount_values),
            ),
        },
        line_items=tuple(line_items),
    )


def test_line_items_preserve_pairs_and_convert_iso_dates():
    triage = result(
        line_items=(
            LineItem({"date_of_service": "2026-04-21", "expected_amount": "$527.00"}),
            LineItem({"date_of_service": "05/02/2026", "expected_amount": "81.20"}),
        ),
        dos_values=("2026-04-21", "2026-05-02"),
        amount_values=("$527.00", "81.20"),
    )

    jobs = jobs_from_result(triage, "email-1")

    assert [(job.dos_from, job.expected_amount) for job in jobs] == [
        ("04/21/2026", "$527.00"),
        ("05/02/2026", "81.20"),
    ]


def test_unpaired_multiple_values_are_never_zipped():
    triage = result(
        dos_values=("2026-04-21", "2026-05-02"),
        amount_values=("527.00", "81.20"),
    )

    assert jobs_from_result(triage, "email-1") == []


def test_single_values_form_one_job_and_duplicates_are_removed():
    triage = result(dos_values=("2026-04-21",), amount_values=("$1,000.00",))
    job = jobs_from_result(triage, "email-1")[0]
    duplicate = type(job)("wc123", "04/21/2026", "1000.00", "email-2")

    assert deduplicate_jobs([job, duplicate]) == [job]


def test_non_bill_status_is_skipped():
    triage = result(dos_values=("2026-04-21",), amount_values=("10.00",))
    triage = TriageResult(
        status=triage.status,
        concern_id="claim_information",
        display_name="Claim Information",
        confidence=triage.confidence,
        margin=triage.margin,
        needs_review=False,
        fields=triage.fields,
    )

    assert jobs_from_result(triage, "email-1") == []


def test_numeric_claim_check_digit_is_hyphenated_for_smartadvisor():
    job = SmartAdvisorJob(
        claim_id="42114901",
        dos_from="04/21/2026",
        expected_amount="527.00",
        source_message_id="email-1",
    )

    assert job.claim_id == "4211490-1"
    assert job.to_dict()["claim_id"] == "4211490-1"
