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
BILL_SEARCH_PROV_TIN_AUTOMATION_ID = "txtProvTIN"
BILL_SEARCH_PATIENT_ACCOUNT_AUTOMATION_ID = "txtPatientAccount"
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
# The warning is usually absent, and looking for something that is not there
# is the expensive case. It sits directly on its own dialog window, so a
# shallow walk finds it and a miss costs seconds rather than tens of seconds.
BILL_PENDED_WARNING_SEARCH_DEPTH = 3
SCOPE_SEARCH_DEPTH = 2

# The opened bill. Its Name embeds the bill number and DCN, so it is never
# matched on Name. It is non-modal, which is why Ctrl+O can start the next
# candidate while it is still on screen.
BILL_ENTRY_WINDOW_AUTOMATION_ID = "frmBillEntry"

# The bill's tab control. Two things about it drive the design:
#
#   * It publishes only the *selected* page in the UIA tree, so the Lines
#     controls do not exist at all until Lines is selected.
#   * Its Name is the selected page's text ("  Hea&der", " &Lines(10)"),
#     which makes it a reliable way to confirm the switch actually happened.
#
# Alt+L does not work: the "&L" in the tab text is a rendered underline, not
# an accelerator this control processes. Arrow the selection along instead
# and watch the Name, rather than firing a key and hoping.
# Which mechanism actually switches the page is not settled: the control
# reports no AccessKey, yet the accelerator appears to do something, and
# arrowing requires the strip to hold focus, which it may not after the
# pended-bill dialog. So all three are tried in order and the log records
# which one worked.
BILL_TAB_AUTOMATION_ID = "Tab1"
BILL_TAB_ACCELERATOR = "%l"
BILL_TAB_NEXT_KEY = "{RIGHT}"
# Last resort: inside an MDI parent Ctrl+Tab can switch child windows rather
# than tab pages, so it is only reached if the other two fail.
BILL_TAB_FALLBACK_KEY = "^{TAB}"
BILL_LINES_TAB_NAME_FRAGMENT = "Lines"
BILL_HISTORY_TAB_NAME_FRAGMENT = "History"
BILL_HISTORY_TAB_ACCELERATOR = "%h"
BILL_HEADER_TAB_NAME_FRAGMENT = "Header"
BILL_TAB_MAX_PRESSES = 12
# A tab switch has to repaint before the Name reflects it, and over Citrix
# that is not instant. Reading straight after a keystroke made a working
# keystroke look like a no-op.
BILL_TAB_SETTLE_TIMEOUT = 3.0

HISTORY_PAID_AMOUNT_AUTOMATION_ID = "_txtData_91"
HISTORY_CHECK_TRANSACTION_AUTOMATION_ID = "_txtData_83"
HEADER_PAID_DATE_AUTOMATION_ID = "_txtData_5"
BILL_LINES_GRID_AUTOMATION_ID = "Spread1"

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
        BILL_SEARCH_PROV_TIN_AUTOMATION_ID,
        BILL_SEARCH_PATIENT_ACCOUNT_AUTOMATION_ID,
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
GRID_COPY_ROW = "^c"
GRID_ROW_CLICK_X = 120
GRID_FIRST_ROW_CLICK_Y = 43
GRID_FIRST_ROW_LOWER_CLICK_Y = 64
GRID_ROW_HEIGHT = 21

LINES_ROW_SELECTOR_CLICK_X = 24
LINES_BR_MSG_ROW_COPY_INDEX = 7
LINES_BRADJ_MSG_ROW_COPY_INDEX = 14
LINES_FIRST_ROW_CLICK_Y = 46
LINES_ROW_HEIGHT = 21
LINES_DENIED_CODE_MAX_ROWS = 80

PRINT_EOR_WINDOW_AUTOMATION_ID = "frmBillBatch"
PRINT_EOR_WINDOW_NAME = "Print Explanation of Review"
PRINT_EOR_KEYS = "^p"
PRINT_EOR_LIST_RADIO_AUTOMATION_ID = "_optChooseBy_1"
PRINT_EOR_BILL_NO_RADIO_AUTOMATION_ID = "_optChooseBy_3"
PRINT_EOR_BILL_LIST_AUTOMATION_ID = "txtBillList"
PRINT_EOR_BILL_LIST_COMMIT_KEYS = "{ENTER}"
PRINT_EOR_ADD_BUTTON_AUTOMATION_ID = "cmdAdd"
PRINT_EOR_ADD_BUTTON_NAME = "&Add ->"
PRINT_EOR_ADD_FALLBACK_KEYS = "%a"
PRINT_EOR_OK_BUTTON_NAME = "&OK"
PRINT_EOR_OK_FALLBACK_KEYS = "%o"
PRINT_EOR_DUPLICATE_SELECTION_TEXT = "already in the selection list"
PRINT_EOR_DUPLICATE_NO_KEY = "%n"
PRINT_SETUP_WINDOW_AUTOMATION_ID = "frmPrintSetup"
PRINT_SETUP_WINDOW_NAME = "Print Setup"
PRINT_SETUP_FILE_RADIO_AUTOMATION_ID = "_optSpool_2"
PRINT_SETUP_FILE_RADIO_NAME = "File"
PRINT_SETUP_FILE_FALLBACK_KEYS = "%f"
PRINT_SETUP_OK_BUTTON_NAME = "&OK"
EXPORT_REPORT_WINDOW_NAME = "Export Report"
EXPORT_REPORT_BROWSE_AUTOMATION_ID = "_cmdBrowse_0"
EXPORT_REPORT_BROWSE_BUTTON_NAME = "..."
EXPORT_REPORT_OK_BUTTON_NAME = "&OK"
EXPORT_REPORT_OK_KEYS = "%o"
SAVE_AS_WINDOW_NAME = "Save As"
SAVE_AS_FILENAME_KEYS = "%n"
SAVE_AS_SAVE_KEYS = "%s"
SAVE_AS_REVIEW_DELAY_SECONDS = 1.0
SAVE_AS_OVERWRITE_TEXTS = (
    "already exists",
    "replace it",
    "already present",
)
SAVE_AS_OVERWRITE_YES_KEY = "%y"
EOR_OUTPUT_DIRECTORY_NAME = "EOR's"
EOR_PDF_PATH_DETAIL_KEY = "EOR PDF Path"
RAD_MESSAGEBOX_AUTOMATION_ID = "RadMessageBox"

SMARTADVISOR_UNHANDLED_EXCEPTION_TEXT = "Unhandled exception has occurred"
SMARTADVISOR_EXCEPTION_CONTINUE_BUTTON_NAME = "Continue"
SMARTADVISOR_NO_RECORDS_TEXT = "No records found matching search criteria."

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
        step="5.5",
        automation_id=BILL_SEARCH_PROV_TIN_AUTOMATION_ID,
        label="Prov TIN",
        action="input",
    ),
    ControlSpec(
        step="5.7",
        automation_id=BILL_SEARCH_PATIENT_ACCOUNT_AUTOMATION_ID,
        label="Patient Account",
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
        search_depth=BILL_PENDED_WARNING_SEARCH_DEPTH,
    ),
    ControlSpec(
        step="7.4",
        automation_id=BILL_TAB_AUTOMATION_ID,
        label="Lines tab",
        action="select_tab",
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.6",
        automation_id=HISTORY_PAID_AMOUNT_AUTOMATION_ID,
        label="History paid amount",
        action="extract",
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.10",
        automation_id=HISTORY_CHECK_TRANSACTION_AUTOMATION_ID,
        label="History check/transaction",
        action="extract",
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.12",
        automation_id=HEADER_PAID_DATE_AUTOMATION_ID,
        label="Header paid date",
        action="extract",
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.7",
        automation_id="",
        label="Close the bill window",
        action="close",
        name=BILL_CLOSE_BUTTON_NAME,
        control_type=BILL_CLOSE_BUTTON_CONTROL_TYPE,
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.8",
        automation_id=BILL_LINES_GRID_AUTOMATION_ID,
        label="Lines grid denial messages",
        action="extract",
        scope_automation_id=BILL_ENTRY_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="7.9",
        automation_id=PRINT_EOR_WINDOW_AUTOMATION_ID,
        label="Print Explanation of Review",
        action="focus",
        name=PRINT_EOR_WINDOW_NAME,
        control_type="Window",
        search_depth=SCOPE_SEARCH_DEPTH,
    ),
    ControlSpec(
        step="8.0",
        automation_id=PRINT_EOR_LIST_RADIO_AUTOMATION_ID,
        label="Print EOR List option",
        action="click",
        scope_automation_id=PRINT_EOR_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.1",
        automation_id=PRINT_EOR_BILL_NO_RADIO_AUTOMATION_ID,
        label="Print EOR Bill No option",
        action="click",
        scope_automation_id=PRINT_EOR_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.2",
        automation_id=PRINT_EOR_BILL_LIST_AUTOMATION_ID,
        label="Print EOR bill list",
        action="input",
        scope_automation_id=PRINT_EOR_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.3",
        automation_id=PRINT_EOR_ADD_BUTTON_AUTOMATION_ID,
        label="Print EOR Add",
        action="click",
        name=PRINT_EOR_ADD_BUTTON_NAME,
        control_type="Button",
        scope_automation_id=PRINT_EOR_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.4",
        automation_id="",
        label="Print EOR OK",
        action="click",
        name=PRINT_EOR_OK_BUTTON_NAME,
        control_type="Button",
        scope_automation_id=PRINT_EOR_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.5",
        automation_id=PRINT_SETUP_WINDOW_AUTOMATION_ID,
        label="Print Setup",
        action="focus",
        name=PRINT_SETUP_WINDOW_NAME,
        control_type="Window",
        search_depth=SCOPE_SEARCH_DEPTH,
    ),
    ControlSpec(
        step="8.6",
        automation_id=PRINT_SETUP_FILE_RADIO_AUTOMATION_ID,
        label="Print Setup File option",
        action="click",
        control_type="RadioButton",
        scope_automation_id=PRINT_SETUP_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.7",
        automation_id="",
        label="Print Setup OK",
        action="click",
        name=PRINT_SETUP_OK_BUTTON_NAME,
        control_type="Button",
        scope_automation_id=PRINT_SETUP_WINDOW_AUTOMATION_ID,
    ),
    ControlSpec(
        step="8.8",
        automation_id="",
        label="Export Report",
        action="focus",
        name=EXPORT_REPORT_WINDOW_NAME,
        control_type="Window",
        search_depth=SCOPE_SEARCH_DEPTH,
    ),
    ControlSpec(
        step="8.9",
        automation_id=EXPORT_REPORT_BROWSE_AUTOMATION_ID,
        label="Export Report browse",
        action="click",
        name=EXPORT_REPORT_BROWSE_BUTTON_NAME,
        control_type="Button",
    ),
)

CONTROLS_BY_STEP = {
    control.step: control for control in NO_BILL_ON_FILE_CONTROLS
}
