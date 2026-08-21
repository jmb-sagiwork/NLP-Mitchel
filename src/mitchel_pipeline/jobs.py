from __future__ import annotations

from datetime import datetime

from email_triage.types import TriageResult, TriageStatus

from .models import SmartAdvisorJob


def _smartadvisor_date(value: str) -> str:
    value = value.strip()
    for format_string in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, format_string).strftime("%m/%d/%Y")
        except ValueError:
            continue
    raise ValueError("unsupported_date_of_service")


def _single_value(result: TriageResult, field_name: str) -> str | None:
    field = result.fields.get(field_name)
    if field is None:
        return None
    values = tuple(value for value in field.all_values if value)
    return values[0] if len(values) == 1 else None


def jobs_from_result(result: TriageResult, message_id: str) -> list[SmartAdvisorJob]:
    """Map only proven DOS/amount pairs; never zip independent value lists."""

    if result.status is not TriageStatus.CLASSIFIED or result.concern_id != "bill_status":
        return []

    claim_id = _single_value(result, "claim_id") or ""
    provider_tin = _single_value(result, "provider_tin") or ""
    patient_account = _single_value(result, "patient_account") or ""
    if not any((claim_id, provider_tin, patient_account)):
        return []

    pairs: list[tuple[str, str]] = []
    if result.line_items:
        for item in result.line_items:
            dos = item.fields.get("date_of_service")
            amount = item.fields.get("expected_amount")
            if dos and amount:
                pairs.append((dos, amount))
    else:
        dos = _single_value(result, "date_of_service")
        amount = _single_value(result, "expected_amount")
        if dos and amount:
            pairs.append((dos, amount))

    jobs: list[SmartAdvisorJob] = []
    for dos, amount in pairs:
        try:
            normalized_dos = _smartadvisor_date(dos)
        except ValueError:
            continue
        jobs.append(
            SmartAdvisorJob(
                claim_id=claim_id,
                dos_from=normalized_dos,
                expected_amount=amount.strip(),
                source_message_id=message_id,
                provider_tin=provider_tin,
                patient_account=patient_account,
            )
        )
    return jobs


def deduplicate_jobs(jobs: list[SmartAdvisorJob]) -> list[SmartAdvisorJob]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[SmartAdvisorJob] = []
    for job in jobs:
        if job.deduplication_key in seen:
            continue
        seen.add(job.deduplication_key)
        unique.append(job)
    return unique
