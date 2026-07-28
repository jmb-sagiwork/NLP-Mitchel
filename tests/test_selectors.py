import re

from smartadvisor_automation.selectors import (
    CONTROLS_BY_STEP,
    NO_BILL_ON_FILE_CONTROLS,
)


def test_selector_ids_are_unique_and_nonempty() -> None:
    automation_ids = [
        control.automation_id for control in NO_BILL_ON_FILE_CONTROLS
    ]

    assert all(automation_ids)
    assert len(automation_ids) == len(set(automation_ids))


def test_workflow_contains_expected_steps() -> None:
    steps = [control.step for control in NO_BILL_ON_FILE_CONTROLS]

    assert steps == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7.1",
        "7.2",
        "7.3",
        "8",
    ]


def test_amount_step_extracts_then_clicks() -> None:
    amount_control = next(
        control
        for control in NO_BILL_ON_FILE_CONTROLS
        if control.step == "7.3"
    )

    assert amount_control.action == "extract_click"


def test_claim_control_uses_bill_search_edit() -> None:
    claim_control = CONTROLS_BY_STEP["4"]

    assert claim_control.automation_id == "197684"
    assert claim_control.action == "input"


def test_selector_definitions_do_not_contain_sample_values() -> None:
    serialized = repr(NO_BILL_ON_FILE_CONTROLS)

    assert re.search(r"\$\s*\d", serialized) is None
    assert re.search(r"\b\d{2}/\d{2}/\d{4}\b", serialized) is None
    assert re.search(r"\b\d{6,}-\d+\b", serialized) is None
    assert re.search(r"\b[A-Z]\d{8,}\b", serialized) is None
