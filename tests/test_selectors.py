import re

from smartadvisor_automation.selectors import (
    BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS,
    CONTROLS_BY_STEP,
    NO_BILL_ON_FILE_CONTROLS,
    OPEN_BILL_OK_AUTOMATION_ID,
)


def test_every_control_is_addressable_and_steps_are_unique() -> None:
    steps = [control.step for control in NO_BILL_ON_FILE_CONTROLS]

    assert len(steps) == len(set(steps))
    assert all(
        control.automation_id or control.name
        for control in NO_BILL_ON_FILE_CONTROLS
    )


def test_workflow_contains_expected_steps() -> None:
    steps = [control.step for control in NO_BILL_ON_FILE_CONTROLS]

    assert steps == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7.0",
        "7.1",
        "7.2",
        "7.3",
        "7.4",
        "7.5",
        "7.6",
    ]


def test_search_and_open_use_differently_cased_ok_buttons() -> None:
    """cmdOK runs the search; cmdOk opens the selected bill.

    They differ only by case and matching is exact, so a transposition
    would silently target the wrong dialog. This is the guard.
    """

    search_ok = CONTROLS_BY_STEP["6"]
    open_ok = CONTROLS_BY_STEP["7.2"]

    assert search_ok.automation_id == "cmdOK"
    assert open_ok.automation_id == "cmdOk"
    assert search_ok.automation_id != open_ok.automation_id
    assert OPEN_BILL_OK_AUTOMATION_ID == "cmdOk"


def test_lines_tab_is_selected_rather_than_accelerated() -> None:
    """Alt+L is not an accelerator this tab control processes.

    The "&L" in the tab text is only a rendered underline, so the page has
    to be selected by moving the strip and checking the control's Name.
    """

    tab = CONTROLS_BY_STEP["7.4"]

    assert tab.automation_id == "Tab1"
    assert tab.action == "select_tab"
    assert tab.scope_automation_id == "frmBillEntry"


def test_amount_step_reads_the_lines_total() -> None:
    amount_control = CONTROLS_BY_STEP["7.5"]

    assert amount_control.automation_id == "_lblTotals_59"
    assert amount_control.action == "extract"
    assert amount_control.scope_automation_id == "frmBillEntry"


def test_close_button_is_matched_by_name_and_scoped() -> None:
    """The title bar Close button publishes no AutomationId at all."""

    close_control = CONTROLS_BY_STEP["7.6"]

    assert close_control.automation_id == ""
    assert close_control.name == "Close"
    assert close_control.control_type == "Button"
    assert close_control.scope_automation_id == "frmBillEntry"


def test_pended_warning_matches_name_as_well_as_generic_id() -> None:
    warning = CONTROLS_BY_STEP["7.3"]

    assert warning.automation_id == "radButton1"
    assert warning.name == "&OK"


def test_results_grid_is_scoped_to_the_bill_records_frame() -> None:
    assert (
        "fpSearchResult" in BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS
    )
    assert CONTROLS_BY_STEP["7.0"].automation_id == "fpSearchResult"
    assert CONTROLS_BY_STEP["7.1"].automation_id == "fpSearchResult"


def test_claim_control_uses_bill_search_edit() -> None:
    claim_control = CONTROLS_BY_STEP["4"]

    assert claim_control.automation_id == "txtClaimID"
    assert claim_control.action == "input"


def test_dos_control_uses_bill_search_edit() -> None:
    dos_control = CONTROLS_BY_STEP["5"]

    assert dos_control.automation_id == "txtDOSFrom"
    assert dos_control.action == "input"


def test_client_control_uses_stable_automation_id() -> None:
    client_control = CONTROLS_BY_STEP["2"]

    assert client_control.automation_id == "txtClient"
    assert client_control.action == "clear"


def test_selector_definitions_do_not_contain_sample_values() -> None:
    serialized = repr(NO_BILL_ON_FILE_CONTROLS)

    assert re.search(r"\$\s*\d", serialized) is None
    assert re.search(r"\b\d{2}/\d{2}/\d{4}\b", serialized) is None
    assert re.search(r"\b\d{6,}-\d+\b", serialized) is None
    assert re.search(r"\b[A-Z]\d{8,}\b", serialized) is None
