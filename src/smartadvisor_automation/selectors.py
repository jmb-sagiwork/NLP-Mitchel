from smartadvisor_automation.models import ControlSpec

WORKFLOW_NAME = "No Bill on File"
SMARTADVISOR_WINDOW_TITLE = "SmartAdvisor Main System"
SMARTADVISOR_WINDOW_CLASS_PREFIX = "WindowsForms10.Window."
OPEN_BILL_WINDOW_TITLE = "Open Bill"
OPEN_BILL_WINDOW_AUTOMATION_ID = "frmBillOpen"
OPEN_BILL_FRAME_AUTOMATION_ID = "Frame1"
OPEN_BILL_FRAME_NAME = "Enter Bill To Edit"
OPEN_BILL_ACTION_AUTOMATION_ID = "_cmdSearch_1"
BILL_SEARCH_WINDOW_TITLE = "Bill Search"
BILL_SEARCH_WINDOW_AUTOMATION_ID = "frmBillSearch"
BILL_SEARCH_FRAME_AUTOMATION_ID = "Frame1"
BILL_SEARCH_FRAME_NAME = "Bill Records"
BILL_SEARCH_TEXT_AUTOMATION_ID = "txtClient"
BILL_SEARCH_ADVANCED_AUTOMATION_ID = "btnAdvacedSearch"
BILL_SEARCH_CLAIM_AUTOMATION_ID = "txtClaimID"
BILL_SEARCH_DOS_FROM_AUTOMATION_ID = "txtDOSFrom"
BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS = frozenset(
    {
        BILL_SEARCH_TEXT_AUTOMATION_ID,
        BILL_SEARCH_ADVANCED_AUTOMATION_ID,
        BILL_SEARCH_CLAIM_AUTOMATION_ID,
        BILL_SEARCH_DOS_FROM_AUTOMATION_ID,
    }
)

# Main-window AutomationId, confirmed by the control picker. Window
# identity still matches on title and class prefix; this is recorded for
# disambiguation only.
SMARTADVISOR_WINDOW_AUTOMATION_ID = "bilMain"

NO_BILL_ON_FILE_CONTROLS: tuple[ControlSpec, ...] = (
    ControlSpec(
        step="1",
        automation_id=OPEN_BILL_ACTION_AUTOMATION_ID,
        label="Additional search options",
        action="click_input_then_invoke",
        common_to_all_cases=True,
    ),
    ControlSpec(
        step="2",
        automation_id=BILL_SEARCH_TEXT_AUTOMATION_ID,
        label="Bill Search client text",
        action="clear",
    ),
    ControlSpec(
        step="3",
        automation_id=BILL_SEARCH_ADVANCED_AUTOMATION_ID,
        label="Advanced Search",
        action="click",
    ),
    ControlSpec(
        step="4",
        automation_id=BILL_SEARCH_CLAIM_AUTOMATION_ID,
        label="Claim ID",
        action="input",
    ),
    ControlSpec(
        step="5",
        automation_id=BILL_SEARCH_DOS_FROM_AUTOMATION_ID,
        label="DOS From",
        action="input",
    ),
    ControlSpec(
        step="6",
        automation_id="cmdOK",
        label="Confirm search",
        action="click",
    ),
    ControlSpec(
        step="7.1",
        automation_id="263910",
        label="Verify/select claim details",
        action="click",
    ),
    ControlSpec(
        step="7.2",
        automation_id="198916",
        label="Patient Account",
        action="extract",
    ),
    ControlSpec(
        step="7.3",
        automation_id="329468",
        label="Amount",
        action="extract_click",
    ),
    ControlSpec(
        step="8",
        automation_id="1901400",
        label="Close result/message window",
        action="close",
    ),
)

CONTROLS_BY_STEP = {
    control.step: control for control in NO_BILL_ON_FILE_CONTROLS
}
