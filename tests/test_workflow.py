import threading

import pytest

from smartadvisor_automation.errors import WorkflowCancelled
from smartadvisor_automation.workflow import (
    NoBillOnFileWorkflow,
    extract_amount,
    extract_patient_account,
    normalize_dos,
    validate_claim_id,
)


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def attach(self, landmark) -> str:
        self.calls.append(("attach", landmark.step))
        return "uia"

    def invoke(self, spec) -> None:
        self.calls.append(("invoke", spec.step))

    def click(self, spec) -> None:
        self.calls.append(("click", spec.step))

    def clear(self, spec) -> None:
        self.calls.append(("clear", spec.step))

    def input_text(self, spec, value: str) -> None:
        self.calls.append(("input", spec.step, value))

    def read_text(self, spec) -> str:
        self.calls.append(("read", spec.step))
        if spec.step == "7.2":
            return "Patient Account - ACCOUNT-TEST"
        return "Amount - $10.00"


def test_workflow_executes_supplied_steps_in_order() -> None:
    driver = FakeDriver()
    workflow = NoBillOnFileWorkflow(driver)

    result = workflow.run("CASE-1", "01/02/2025")

    assert driver.calls == [
        ("attach", "1"),
        ("invoke", "1"),
        ("clear", "2"),
        ("click", "3"),
        ("input", "4", "CASE-1"),
        ("input", "5", "01/02/2025"),
        ("click", "6"),
        ("click", "7.1"),
        ("read", "7.2"),
        ("read", "7.3"),
        ("click", "7.3"),
        ("click", "8"),
    ]
    assert result.patient_account == "ACCOUNT-TEST"
    assert result.amount == "$10.00"
    assert "not a bill on file" in result.outcome.lower()


def test_workflow_honors_cancellation_before_first_action() -> None:
    driver = FakeDriver()
    cancelled = threading.Event()
    cancelled.set()
    workflow = NoBillOnFileWorkflow(driver, cancel_event=cancelled)

    with pytest.raises(WorkflowCancelled):
        workflow.run("CASE-1", "01/02/2025")

    assert driver.calls == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("case-1", "case-1"),
        (" CLAIM_2 ", "CLAIM_2"),
        ("A/B.3", "A/B.3"),
    ],
)
def test_claim_id_validation(raw: str, expected: str) -> None:
    assert validate_claim_id(raw) == expected


@pytest.mark.parametrize("value", ["", "bad value", "case+1", "line\nbreak"])
def test_claim_id_rejects_unsafe_characters(value: str) -> None:
    with pytest.raises(ValueError):
        validate_claim_id(value)


def test_dos_is_validated_and_normalized() -> None:
    assert normalize_dos(" 03/05/2026 ") == "03/05/2026"

    with pytest.raises(ValueError):
        normalize_dos("02/30/2026")


def test_result_value_extraction() -> None:
    assert (
        extract_patient_account("Patient Account - ACCOUNT-TEST")
        == "ACCOUNT-TEST"
    )
    assert extract_amount("Billed Amount: $1,234.56") == "$1,234.56"
