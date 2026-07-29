import threading
from decimal import Decimal

import pytest

from smartadvisor_automation.errors import AutomationError, WorkflowCancelled
from smartadvisor_automation.workflow import (
    NoBillOnFileWorkflow,
    extract_amount,
    extract_patient_account,
    mask_amount_shape,
    normalize_amount,
    normalize_dos,
    validate_claim_id,
    validate_expected_amount,
)

SEARCH_CALLS = [
    ("attach", "1"),
    ("click_with_invoke_fallback", "1", "2"),
    ("clear", "2"),
    ("click", "3"),
    ("input", "4", "CASE-1"),
    ("input", "5", "01/02/2025"),
    ("click", "6"),
]


class FakeDriver:
    """Records the exact call order for one or more candidate rows.

    `amounts` supplies the totals label text each opened bill reports, in
    row order. Reading past the end repeats the final entry, which is what
    the real grid does once the seek clamps at the last row.
    """

    def __init__(
        self,
        amounts: list[str] | None = None,
        *,
        warning_present: bool = False,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.amounts = amounts or ["1,952.43 (312.57)"]
        self.warning_present = warning_present
        self.reads = 0

    def attach(self, landmark) -> str:
        self.calls.append(("attach", landmark.step))
        return "uia"

    def click_with_invoke_fallback(self, spec, confirmation_spec) -> None:
        self.calls.append(
            ("click_with_invoke_fallback", spec.step, confirmation_spec.step)
        )

    def click(self, spec) -> None:
        self.calls.append(("click", spec.step))

    def clear(self, spec) -> None:
        self.calls.append(("clear", spec.step))

    def input_text(self, spec, value: str) -> None:
        self.calls.append(("input", spec.step, value))

    def focus_grid(self, spec) -> None:
        self.calls.append(("focus_grid", spec.step))

    def send_keys(self, spec, keys: str) -> None:
        self.calls.append(("send_keys", spec.step, keys))

    def select_tab(
        self,
        spec,
        *,
        expected_fragment: str,
        accelerator: str,
        next_key: str,
        fallback_key: str,
        max_presses: int,
        settle_timeout: float,
    ) -> None:
        self.calls.append(
            ("select_tab", spec.step, next_key, expected_fragment)
        )

    def invalidate_scopes(self) -> None:
        self.calls.append(("invalidate_scopes",))

    def is_present(self, spec) -> bool:
        self.calls.append(("is_present", spec.step))
        return self.warning_present

    def read_text(self, spec) -> str:
        self.calls.append(("read", spec.step))
        index = min(self.reads, len(self.amounts) - 1)
        self.reads += 1
        return self.amounts[index]


def candidate_calls(row_index: int) -> list[tuple[str, ...]]:
    """The calls one candidate iteration makes, including the seek."""

    calls = [
        ("invalidate_scopes",),
        *SEARCH_CALLS,
        ("focus_grid", "7.0"),
        ("send_keys", "7.1", "{DOWN}"),
        ("send_keys", "7.1", "{UP}"),
    ]
    if row_index:
        calls.append(("send_keys", "7.1", "{DOWN}" * row_index))
    calls.extend(
        [
            ("send_keys", "7.1", "{ENTER}"),
            ("click", "7.2"),
            ("is_present", "7.3"),
            ("select_tab", "7.4", "{RIGHT}", "Lines"),
            ("read", "7.5"),
        ]
    )
    return calls


def test_first_row_matches_without_any_seek_presses() -> None:
    driver = FakeDriver(["1,952.43 (312.57)"])
    workflow = NoBillOnFileWorkflow(driver)

    result = workflow.run("CASE-1", "01/02/2025", "1,952.43")

    assert driver.calls == candidate_calls(0)
    assert result.amount == "1,952.43"
    assert result.row_index == 0
    assert result.rows_examined == 1
    assert result.patient_account is None
    assert "not a bill on file" in result.outcome.lower()


def test_calibration_runs_every_iteration_and_seek_increments() -> None:
    driver = FakeDriver(
        [
            "500.00 (10.00)",
            "742.10 (11.00)",
            "1,180.00 (12.00)",
        ]
    )
    workflow = NoBillOnFileWorkflow(driver)

    result = workflow.run("CASE-1", "01/02/2025", "1,180.00")

    assert driver.calls == [
        *candidate_calls(0),
        ("click", "7.6"),
        *candidate_calls(1),
        ("click", "7.6"),
        *candidate_calls(2),
    ]
    assert result.row_index == 2
    assert result.rows_examined == 3

    # Calibration is one Down plus one Up per iteration, never folded into
    # the seek count.
    calibrations = [
        call
        for call in driver.calls
        if call == ("send_keys", "7.1", "{UP}")
    ]
    assert len(calibrations) == 3


def test_repeated_amount_stops_the_loop_and_closes_the_bill() -> None:
    driver = FakeDriver(["500.00 (1.00)", "742.10 (2.00)"])
    workflow = NoBillOnFileWorkflow(driver)

    with pytest.raises(AutomationError) as captured:
        workflow.run("CASE-1", "01/02/2025", "9,999.99")

    assert captured.value.code == "no_matching_candidate_row"
    # Row 2 re-read row 1's amount, so the seek had clamped at the last row.
    assert driver.calls[-1] == ("click", "7.6")
    assert driver.reads == 3


def test_pended_warning_is_acknowledged_when_present() -> None:
    driver = FakeDriver(["1,952.43 (312.57)"], warning_present=True)
    workflow = NoBillOnFileWorkflow(driver)

    workflow.run("CASE-1", "01/02/2025", "1952.43")

    assert ("is_present", "7.3") in driver.calls
    assert ("click", "7.3") in driver.calls


def test_unreadable_amount_stops_with_a_clear_code() -> None:
    driver = FakeDriver(["(312.57)"])
    workflow = NoBillOnFileWorkflow(driver)

    with pytest.raises(AutomationError) as captured:
        workflow.run("CASE-1", "01/02/2025", "1,952.43")

    assert captured.value.code == "amount_not_readable"
    assert captured.value.step == "7.5"


def test_workflow_honors_cancellation_before_first_action() -> None:
    driver = FakeDriver()
    cancelled = threading.Event()
    cancelled.set()
    workflow = NoBillOnFileWorkflow(driver, cancel_event=cancelled)

    with pytest.raises(WorkflowCancelled):
        workflow.run("CASE-1", "01/02/2025", "1,952.43")

    assert driver.calls == []


def test_workflow_honors_cancellation_between_candidates() -> None:
    cancelled = threading.Event()
    driver = FakeDriver(["500.00 (1.00)", "742.10 (2.00)"])
    workflow = NoBillOnFileWorkflow(driver, cancel_event=cancelled)

    original_read = driver.read_text

    def read_then_cancel(spec):
        cancelled.set()
        return original_read(spec)

    driver.read_text = read_then_cancel

    with pytest.raises(WorkflowCancelled):
        workflow.run("CASE-1", "01/02/2025", "9,999.99")

    assert driver.reads == 1


def test_log_messages_never_carry_amount_values() -> None:
    driver = FakeDriver(["1,952.43 (312.57)"])
    lines: list[str] = []
    workflow = NoBillOnFileWorkflow(driver, log=lines.append)

    workflow.run("CASE-1", "01/02/2025", "1,952.43")

    joined = "\n".join(lines)
    assert lines
    assert "1,952.43" not in joined
    assert "312.57" not in joined
    assert "#,###.##" in joined


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


@pytest.mark.parametrize(
    "value", ["1,952.43", "$1952.43", " 1952 ", "0.05"]
)
def test_expected_amount_accepts_normal_formats(value: str) -> None:
    assert validate_expected_amount(value) == value.strip()


@pytest.mark.parametrize("value", ["", "abc", "1.234", "(312.57)", "1-2"])
def test_expected_amount_rejects_unusable_input(value: str) -> None:
    with pytest.raises(ValueError):
        validate_expected_amount(value)


def test_result_value_extraction() -> None:
    assert (
        extract_patient_account("Patient Account - ACCOUNT-TEST")
        == "ACCOUNT-TEST"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The Lines totals label: plain charge amount, then a parenthesised
        # adjustment. driver.read_text has already collapsed the newline.
        ("1,952.43 (312.57)", "1,952.43"),
        ("1,952.43\n(312.57)", "1,952.43"),
        ("Billed Amount: $1,234.56", "$1,234.56"),
        ("742.10", "742.10"),
        ("(312.57)", ""),
        ("no digits here", ""),
    ],
)
def test_amount_extraction_takes_the_plain_value(
    raw: str, expected: str
) -> None:
    assert extract_amount(raw) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("1,952.43", "1952.4300"),
        ("$1,952.43", "1952.43"),
        (" 1952 ", "1952.00"),
    ],
)
def test_amounts_compare_by_value(left: str, right: str) -> None:
    assert normalize_amount(left) == normalize_amount(right)


def test_normalize_amount_rejects_unparseable_text() -> None:
    assert normalize_amount("1,180.00") == Decimal("1180.00")

    with pytest.raises(ValueError):
        normalize_amount("not an amount")


def test_amount_shape_masks_every_digit() -> None:
    assert mask_amount_shape("1,952.43") == "#,###.##"
    assert mask_amount_shape("$742.10") == "$###.##"
