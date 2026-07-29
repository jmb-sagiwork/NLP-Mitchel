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
BILL_SEARCH_RESULTS_AUTOMATION_ID = "fpSearchResult"

# Two different OK buttons whose AutomationIds differ only by case. Matching
# is exact (see probe.selector_match_strategy), so they cannot collide at
# runtime, but they transpose very easily by hand:
#   cmdOK -> Bill Search dialog; runs the search and populates the grid.
#   cmdOk -> Open Bill window; opens the bill selected in the grid.
BILL_SEARCH_OK_AUTOMATION_ID = "cmdOK"
OPEN_BILL_OK_AUTOMATION_ID = "cmdOk"

# Conditional "this bill is currently pended" warning. radButton1 is a
# generic Telerik name, so the Name is matched as well and the step treats
# absence as the normal case.
BILL_PENDED_WARNING_OK_AUTOMATION_ID = "radButton1"
BILL_PENDED_WARNING_OK_NAME = "&OK"

# The opened bill. Its Name embeds the bill number and DCN, so it is never
# matched on Name. It is non-modal, which is why Ctrl+O can start the next
# candidate while it is still on screen.
BILL_ENTRY_WINDOW_AUTOMATION_ID = "frmBillEntry"

# Charge amount on the Lines tab, reached with the Alt+L accelerator. The tab
# and pane names carry the line count ("Lines(10)"), so they are unusable as
# selectors; this control-array id is stable across bills.
BILL_LINES_AMOUNT_AUTOMATION_ID = "_lblTotals_59"
BILL_LINES_ACCELERATOR = "%l"

# Non-client title bar button: it publishes no AutomationId, so it is found by
# Name plus ControlType, scoped to the bill window. Unscoped it would match
# every window's Close button.
BILL_CLOSE_BUTTON_NAME = "Close"
BILL_CLOSE_BUTTON_CONTROL_TYPE = "Button"

BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS = frozenset(
    {
        BILL_SEARCH_TEXT_AUTOMATION_ID,
        BILL_SEARCH_ADVANCED_AUTOMATION_ID,
        BILL_SEARCH_CLAIM_AUTOMATION_ID,
        BILL_SEARCH_DOS_FROM_AUTOMATION_ID,
        BILL_SEARCH_RESULTS_AUTOMATION_ID,
    }
)

# Main-window AutomationId, confirmed by the control picker. Window
# identity still matches on title and class prefix; this is recorded for
# disambiguation only.
SMARTADVISOR_WINDOW_AUTOMATION_ID = "bilMain"

# Calibration nudge. A freshly populated grid has an indeterminate selection,
# so one Down followed by one Up lands on the topmost row whatever the click
# that focused the grid landed on. This is not part of the row seek.
GRID_CALIBRATE_DOWN = "{DOWN}"
GRID_CALIBRATE_UP = "{UP}"
GRID_SEEK_DOWN = "{DOWN}"
GRID_CONFIRM_ROW = "{ENTER}"

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
        automation_id=BILL_SEARCH_OK_AUTOMATION_ID,
        label="Run search",
        action="click",
    ),
    ControlSpec(
        step="7.0",
        automation_id=BILL_SEARCH_RESULTS_AUTOMATION_ID,
        label="Search results grid",
        action="focus",
    ),
    ControlSpec(
        step="7.1",
        automation_id=BILL_SEARCH_RESULTS_AUTOMATION_ID,
        label="Select candidate row",
        action="keys",
    ),
    ControlSpec(
        step="7.2",
        automation_id=OPEN_BILL_OK_AUTOMATION_ID,
        label="Open the selected bill",
        action="click",
    ),
    ControlSpec(
        step="7.3",
        automation_id=BILL_PENDED_WARNING_OK_AUTOMATION_ID,
        label="Pended bill warning",
        action="click",
        name=BILL_PENDED_WARNING_OK_NAME,
    ),
    ControlSpec(
        step="7.4",
        automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
        label="Bill window",
        action="window_keys",
    ),
    ControlSpec(
        step="7.5",
        automation_id=BILL_LINES_AMOUNT_AUTOMATION_ID,
        label="Lines charge amount",
        action="extract",
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.6",
        automation_id="",
        label="Close the bill window",
        action="close",
        name=BILL_CLOSE_BUTTON_NAME,
        control_type=BILL_CLOSE_BUTTON_CONTROL_TYPE,
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
)

CONTROLS_BY_STEP = {
    control.step: control for control in NO_BILL_ON_FILE_CONTROLS
}
