from smartadvisor_automation.models import ControlSpec

WORKFLOW_NAME = "No Bill on File"
SMARTADVISOR_WINDOW_TITLE = "SmartAdvisor Main System"
SMARTADVISOR_WINDOW_CLASS_PREFIX = "WindowsForms10.Window."
OPEN_BILL_WINDOW_TITLE = "Open Bill"
OPEN_BILL_WINDOW_AUTOMATION_ID = "frmBillOpen"
OPEN_BILL_FRAME_AUTOMATION_ID = "Frame1"
OPEN_BILL_FRAME_NAME = "Enter Bill To Edit"
OPEN_BILL_CLIENT_AUTOMATION_ID = "cboClient"

NO_BILL_ON_FILE_CONTROLS: tuple[ControlSpec, ...] = (
    ControlSpec(
        step="1",
        automation_id="cboClient",
        label="Open bill/client selection",
        action="click",
        common_to_all_cases=True,
    ),
    ControlSpec(
        step="2",
        automation_id="_cmdSearch_1",
        label="Additional search options",
        action="click",
    ),
    ControlSpec(
        step="3",
        automation_id="263892",
        label="Search/input box",
        action="clear",
    ),
    ControlSpec(
        step="4",
        automation_id="btnAdvacedSearch",
        label="Advanced Search",
        action="click",
    ),
    ControlSpec(
        step="5",
        automation_id="67390",
        label="Claim ID",
        action="input",
    ),
    ControlSpec(
        step="6",
        automation_id="67512",
        label="DOS From",
        action="input",
    ),
    ControlSpec(
        step="7",
        automation_id="cmdOK",
        label="Confirm search",
        action="click",
    ),
    ControlSpec(
        step="8.1",
        automation_id="263910",
        label="Verify/select claim details",
        action="click",
    ),
    ControlSpec(
        step="8.2",
        automation_id="198916",
        label="Patient Account",
        action="extract",
    ),
    ControlSpec(
        step="8.3",
        automation_id="329468",
        label="Amount",
        action="extract_click",
    ),
    ControlSpec(
        step="9",
        automation_id="1901400",
        label="Close result/message window",
        action="close",
    ),
)

CONTROLS_BY_STEP = {
    control.step: control for control in NO_BILL_ON_FILE_CONTROLS
}
