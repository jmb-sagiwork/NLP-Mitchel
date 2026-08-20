"""SmartAdvisor "No Bill on File" automation - single-file edition.

WHAT THIS PROGRAM DOES
======================
It drives the SmartAdvisor desktop application (running inside Citrix) to
answer one question: for a given Claim ID and date of service, which bill has
a particular charge amount?

It is an ATTENDED tool. A human opens SmartAdvisor, signs in, and then runs
this. It never handles credentials and never logs in.

The hard part is that SmartAdvisor's search-results grid is an owner-drawn
control that exposes no accessibility information whatsoever, so its rows
cannot be read. The workaround is the whole design of this program and is
explained fully in SECTION 7.


HOW TO RUN IT
=============
    pip install pywinauto==0.6.9
    python smartadvisor_automation_all_in_one.py

Open and sign in to SmartAdvisor FIRST. Then fill in Claim ID, DOS From and
Expected Amount, and press "Run workflow".

Python 3.11 or newer.


IMPORTANT: 32-BIT vs 64-BIT
===========================
SmartAdvisor is a 32-bit application. The shipped executable is built as x86
for that reason. If you run this from a 64-bit Python it may not attach.
Prefer a 32-bit Python interpreter for local testing.


HOW TO READ THIS FILE
=====================
It is nine modules concatenated in dependency order. Each section starts with a
banner explaining what it does and why. Suggested reading order:

    SECTION 7 (the workflow)     the algorithm - start here
    SECTION 4 (selectors)        every control, and every trap
    SECTION 6 (the driver)       how a control is clicked or read
    SECTION 8 (the UI)           threading and the log
    SECTION 5 (finding windows)  skip unless attaching fails

Table of contents:

    SECTION 1 - Errors
    SECTION 2 - The attach diagnostic trace
    SECTION 3 - Data models (ControlSpec - read this early)
    SECTION 4 - Selectors: every control, and every trap
    SECTION 5 - Finding windows (the messy part)
    SECTION 6 - The driver: doing things to controls
    SECTION 7 - The workflow: the algorithm itself
    SECTION 8 - The user interface (Tkinter)
    SECTION 9 - Entry point


THINGS THAT WILL BITE YOU
=========================
Collected from real debugging on this project. Each one cost hours.

 1. `cmdOK` and `cmdOk` are DIFFERENT BUTTONS. Case matters and matching is
    exact. cmdOK runs the search; cmdOk opens the bill.

 2. Any Name containing a bill number, a DCN or a line count CHANGES between
    bills. Never match a selector on those.

 3. Reading one UIA property over Citrix costs ~440ms. A "small" tree walk of
    64 elements took 28 SECONDS. Cache containers; cap search depth.

 4. Searching for a control that is ABSENT is the expensive case, because
    every poll re-walks the tree.

 5. The bill's tab control publishes only the SELECTED tab's children. Controls
    on other tabs do not exist until you switch. So a tab switch must be
    VERIFIED, not assumed.

 6. `{DOWN}` then `{UP}` is calibration onto the top row. It is not part of
    counting rows.

 7. The charge amount has no "$" and shares its label with a second,
    parenthesised figure.

 8. Amounts ARE written to the run log, on purpose. Treat saved logs as
    sensitive.


WHERE THIS FILE CAME FROM
=========================
This is a FLATTENED COPY, generated from the real project, which is a normal
Python package:

    src/smartadvisor_automation/
        errors.py  diagnostics.py  models.py  selectors.py
        probe.py   driver.py       workflow.py  app.py

The package is what ships, what the 139 unit tests run against, and what the
x86 build uses. Changes made in THIS file do not flow back there. If you change
something here and want to keep it, port it to the matching module and run:

    python -m pytest

Diagnostic utilities that are NOT included here, because they are separate
programs rather than part of the workflow: the control picker, the action
recorder, the object extractor and the Bill Search control printer.
"""

from __future__ import annotations


import json
import os
import queue
import re
import threading
import time
import tkinter as tk

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Iterable, Literal, Protocol


# ==========================================================================
# SECTION 1 - ERRORS
# ==================
#
# Two exception types, and the reason there are exactly two.
#
# `AutomationError` carries a short machine-readable `code` (for example
# "selector_not_found") instead of a sentence. Two reasons:
#
#   1. The code is shown in the UI and written to a diagnostics file, so it must
#      never contain a claim number, a date or a patient name.
#   2. Codes are stable enough to grep for in a log. Prose is not.
#
# `WorkflowCancelled` is separate because it is NOT a failure. The user pressed
# Cancel. The UI reports it differently, and no error dialog appears.
#
# Original file: src/smartadvisor_automation/errors.py
# ==========================================================================

class AutomationError(RuntimeError):
    """A sanitized automation failure safe to show in the UI."""

    def __init__(
        self,
        code: str,
        *,
        step: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.step = step
        self.diagnostics = diagnostics


class WorkflowCancelled(RuntimeError):
    """Raised when the user cancels between workflow steps."""


# ==========================================================================
# SECTION 2 - THE ATTACH DIAGNOSTIC TRACE
# =======================================
#
# When the automation cannot find the SmartAdvisor window it needs to explain
# why, but it must not dump window titles (those contain bill numbers).
#
# `DiagnosticTrace` records one line per attempt: which stage, which backend,
# what happened, plus counts. Never any text read from the screen. The result is
# written to
# %LOCALAPPDATA%\SmartAdvisorAutomation\diagnostics\latest-attach-trace.json
#
# Note this is a different thing from the run Log panel in the UI. The trace is
# value-free; the Log panel deliberately does contain charge amounts. See
# SECTION 8.
#
# Original file: src/smartadvisor_automation/diagnostics.py
# ==========================================================================

@dataclass
class DiagnosticTrace:
    """Redacted step-by-step record of one attach handshake attempt.

    Records counts and outcomes only: no window titles, control text,
    claim data, or field values.
    """

    steps: list[dict[str, object]] = field(default_factory=list)

    def record(
        self,
        stage: str,
        backend: str,
        outcome: str,
        **details: object,
    ) -> None:
        self.steps.append(
            {
                "stage": stage,
                "backend": backend,
                "outcome": outcome,
                **details,
            }
        )

    def to_report(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "privacy": {
                "includes_window_titles": False,
                "includes_field_values": False,
            },
            "steps": self.steps,
        }


# ==========================================================================
# SECTION 3 - DATA MODELS
# =======================
#
# `ControlSpec` is the heart of the design: one object describing how to find one
# control on screen. Everything the automation clicks or reads goes through one
# of these. The fields exist for reasons that were each learned the hard way:
#
#   automation_id       Normally how a control is found. Matching is EXACT and
#                       case-sensitive - see the cmdOK / cmdOk note in SECTION 4.
#
#   name, control_type  For controls with NO AutomationId at all. The bill
#                       window's title bar Close button is one: it is a
#                       non-client element and publishes only a Name and a
#                       ControlType.
#
#   scope_automation_id Restrict the search to inside one container. Required
#                       when a selector is not unique - EVERY window in the app
#                       owns a "Close" button, so an unscoped search for it
#                       would match several and fail as ambiguous.
#
#   search_depth        Cap how deep an unscoped search walks. Reading one UIA
#                       property over Citrix costs roughly 440 MILLISECONDS, so
#                       an unbounded walk is genuinely expensive: an optional
#                       control with a 1.5 second timeout once burned 21 seconds.
#
# `WorkflowResult` is what the UI displays after a successful run.
# `patient_account` is Optional and currently always None - see the note at the
# end of the file.
#
# Original file: src/smartadvisor_automation/models.py
# ==========================================================================

Action = Literal[
    "click",
    "click_input_then_invoke",
    "clear",
    "input",
    "extract",
    "extract_click",
    "close",
    "focus",
    "keys",
    "select_tab",
]


@dataclass(frozen=True, slots=True)
class ControlSpec:
    """A selector definition for one SmartAdvisor workflow control.

    Most controls are found by AutomationId. Non-client title bar buttons
    publish no AutomationId at all, so `name`/`control_type` express those.
    `scope_automation_id` restricts the search to the descendants of one
    container, which is required whenever a selector is not unique across
    the whole process (every window owns a "Close" button, for example).

    `search_depth` caps how deep an unscoped search walks. Reading one UIA
    property over Citrix costs hundreds of milliseconds, so an unbounded walk
    is expensive: an optional control with a 1.5s timeout burned 21s in a
    live run. Set it for controls known to sit near a top-level window.
    """

    step: str
    automation_id: str
    label: str
    action: Action
    common_to_all_cases: bool = False
    name: str | None = None
    control_type: str | None = None
    scope_automation_id: str | None = None
    search_depth: int | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Sanitized outcome of locating one control with one backend."""

    backend: str
    step: str
    automation_id: str
    label: str
    intended_action: Action
    status: str
    match_strategy: str | None = None
    match_count: int = 0
    control_type: str | None = None
    class_name: str | None = None
    visible: bool | None = None
    enabled: bool | None = None
    rectangle: dict[str, int] | None = None
    error_code: str | None = None
    selector_name: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return selector metadata without control text or field values."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Values returned to the UI after a successful workflow."""

    patient_account: str | None
    amount: str
    outcome: str
    row_index: int = 0
    rows_examined: int = 1


# ==========================================================================
# SECTION 4 - SELECTORS: EVERY CONTROL, AND EVERY TRAP
# ====================================================
#
# This is the section to read first if something breaks. It is a list of
# constants plus `NO_BILL_ON_FILE_CONTROLS`, the ordered steps of the workflow.
#
# Read the comments in here carefully. Each one records something that cost real
# debugging time:
#
#   * cmdOK vs cmdOk        Two DIFFERENT buttons in two different windows whose
#                           AutomationIds differ only by the case of one letter.
#                           cmdOK (Bill Search) runs the search. cmdOk (Open
#                           Bill) opens the selected bill. Matching is exact so
#                           they cannot collide at runtime, but they are trivial
#                           to transpose while typing. There is a test guarding
#                           this specific mistake.
#
#   * frmBillEntry's Name   Contains the bill number and DCN, so it changes for
#                           every bill. NEVER match on it - match on
#                           AutomationId plus class name prefix.
#
#   * "Lines(10)"           The tab and pane names embed the line COUNT, so they
#                           change per bill too. Same rule: do not match on them.
#
#   * _lblTotals_59         The charge amount. The "_59" is a control-array
#                           index. This was once wrongly believed to drift with
#                           the line count; an Inspect capture proved it does
#                           not. It is correct.
#
#   * Calibration keys      GRID_CALIBRATE_DOWN then GRID_CALIBRATE_UP is a
#                           nudge to land on the TOP row, NOT part of counting
#                           down to a row. Do not fold it into the row count or
#                           every candidate shifts by one.
#
# Original file: src/smartadvisor_automation/selectors.py
# ==========================================================================

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
# The warning is usually absent, and looking for something that is not there
# is the expensive case. It sits directly on its own dialog window, so a
# shallow walk finds it and a miss costs seconds rather than tens of seconds.
BILL_PENDED_WARNING_SEARCH_DEPTH = 3

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
BILL_TAB_MAX_PRESSES = 12
# A tab switch has to repaint before the Name reflects it, and over Citrix
# that is not instant. Reading straight after a keystroke made a working
# keystroke look like a no-op.
BILL_TAB_SETTLE_TIMEOUT = 3.0

# Charge amount on the Lines tab. The tab and pane names carry the line count
# ("Lines(10)") so they are unusable as selectors; this control-array id is
# stable across bills.
BILL_LINES_AMOUNT_AUTOMATION_ID = "_lblTotals_59"
# The "_59" suffix is a control-array position. A live run read a four-digit
# total from a bill with 10+ lines and a two-digit one from a bill with
# fewer, so the position does not track the bill total. The diagnostic scan
# walks this prefix to find which index actually holds it.
BILL_LINES_AMOUNT_PREFIX = "_lblTotals_"

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


# ==========================================================================
# SECTION 5 - FINDING WINDOWS (the messy part)
# ============================================
#
# This is the longest section and the least pleasant. You will rarely need to
# change it. Its job: given a running SmartAdvisor, hand back a usable
# pywinauto wrapper for the window or control we want.
#
# Why it is so long: SmartAdvisor runs inside Citrix, and the accessibility tree
# it exposes is inconsistent. Specifically,
#
#   * A modal child window is not guaranteed to report the same process ID as
#     its logical parent, so "find children of the main window's process" is not
#     reliable. Windows are matched by their own identity instead.
#
#   * pywinauto's UIA tree sometimes exposes a window and sometimes does not,
#     so there are win32gui (native HWND) fallbacks - the functions using
#     `win32gui.EnumWindows` and `EnumChildWindows`.
#
#   * A modal dialog DISABLES its parent, so waiting for the parent to be
#     "enabled" times out forever. An early version of a sibling tool made
#     exactly this mistake.
#
# The three functions the rest of the file actually calls:
#
#   find_smartadvisor_window()  the main application window
#   find_open_bill_frame()      Open Bill -> Frame1 ("Enter Bill To Edit")
#   find_bill_search_frame()    Bill Search -> Frame1 ("Bill Records")
#
# And the matching helpers, which decide whether one element satisfies one
# ControlSpec:
#
#   selector_match_strategy()   by AutomationId (exact, case-sensitive)
#   name_match_strategy()       by Name + ControlType, for the no-id case
#   spec_match_strategy()       picks between them; if a spec has BOTH an id and
#                               a Name, BOTH must agree. That is how the generic
#                               Telerik id "radButton1" gets pinned to one
#                               specific OK button.
#
# `scan_controls()` at the bottom powers the UI's "Validate controls" button: it
# checks every selector without clicking anything.
#
# Original file: src/smartadvisor_automation/probe.py
# ==========================================================================

SUPPORTED_BACKENDS = ("uia", "win32")


def selector_match_strategy(element_info: Any, automation_id: str) -> str | None:
    """Return the stable selector strategy matching an element, if any."""

    actual_automation_id = str(
        getattr(element_info, "automation_id", "") or ""
    )
    if actual_automation_id == automation_id:
        return "automation_id"

    if automation_id.isdecimal():
        control_id = getattr(element_info, "control_id", None)
        if control_id is not None and str(control_id) == automation_id:
            return "control_id"

    return None


def name_match_strategy(
    element_info: Any,
    name: str | None,
    control_type: str | None,
) -> str | None:
    """Match a control that publishes no AutomationId at all.

    Non-client title bar buttons expose only a Name and a ControlType, so
    those are the whole selector. Always use this scoped to one container:
    every window in the process owns a "Close" button.
    """

    if not name:
        return None

    actual_name = str(getattr(element_info, "name", "") or "").strip()
    if actual_name != name:
        return None

    if control_type:
        actual_control_type = str(
            getattr(element_info, "control_type", "") or ""
        )
        if actual_control_type != control_type:
            return None

    return "name_and_control_type"


def spec_match_strategy(element_info: Any, spec: ControlSpec) -> str | None:
    """Match one element against a spec.

    AutomationId identifies the control when there is one. A spec may also
    carry a Name alongside it, in which case both must agree — that is how
    a generic framework id such as `radButton1` is pinned down to one
    button. With no AutomationId, Name plus ControlType is the whole
    selector.
    """

    if not spec.automation_id:
        return name_match_strategy(element_info, spec.name, spec.control_type)

    strategy = selector_match_strategy(element_info, spec.automation_id)
    if strategy is None:
        return None

    if spec.name and (
        name_match_strategy(element_info, spec.name, spec.control_type)
        is None
    ):
        return None

    return strategy


def _safe_rectangle(element_info: Any) -> dict[str, int] | None:
    rectangle = getattr(element_info, "rectangle", None)
    if rectangle is None:
        return None

    try:
        return {
            "left": int(rectangle.left),
            "top": int(rectangle.top),
            "right": int(rectangle.right),
            "bottom": int(rectangle.bottom),
        }
    except (AttributeError, TypeError, ValueError):
        return None


def _safe_bool(wrapper: Any, method_name: str) -> bool | None:
    try:
        return bool(getattr(wrapper, method_name)())
    except Exception:
        return None


def matching_elements(
    descendants: Iterable[Any], automation_id: str
) -> list[tuple[Any, str]]:
    matches: list[tuple[Any, str]] = []
    for element in descendants:
        strategy = selector_match_strategy(element.element_info, automation_id)
        if strategy:
            matches.append((element, strategy))
    return matches


def matching_spec_elements(
    descendants: Iterable[Any], spec: ControlSpec
) -> list[tuple[Any, str]]:
    """Match by AutomationId, or by Name/ControlType when there is none."""

    matches: list[tuple[Any, str]] = []
    for element in descendants:
        strategy = spec_match_strategy(element.element_info, spec)
        if strategy:
            matches.append((element, strategy))
    return matches


def _probe_control(
    backend: str, descendants: list[Any], spec: ControlSpec
) -> ProbeResult:
    matches = matching_spec_elements(descendants, spec)

    if not matches:
        return ProbeResult(
            backend=backend,
            step=spec.step,
            automation_id=spec.automation_id,
            label=spec.label,
            intended_action=spec.action,
            status="not_found",
            selector_name=spec.name,
        )

    element, strategy = matches[0]
    info = element.element_info
    status = "found" if len(matches) == 1 else "ambiguous"

    return ProbeResult(
        backend=backend,
        step=spec.step,
        automation_id=spec.automation_id,
        label=spec.label,
        intended_action=spec.action,
        status=status,
        match_strategy=strategy,
        match_count=len(matches),
        control_type=str(getattr(info, "control_type", "") or "") or None,
        class_name=str(getattr(info, "class_name", "") or "") or None,
        visible=_safe_bool(element, "is_visible"),
        enabled=_safe_bool(element, "is_enabled"),
        rectangle=_safe_rectangle(info),
        selector_name=spec.name,
    )


def is_smartadvisor_window_identity(title: str, class_name: str) -> bool:
    """Match the exact SmartAdvisor WinForms top-level window identity."""

    return (
        title.strip().casefold() == SMARTADVISOR_WINDOW_TITLE.casefold()
        and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
    )


def _native_smartadvisor_handles() -> list[int]:
    """Enumerate live SmartAdvisor HWNDs without relying on UIA text."""

    import win32gui

    handles: list[int] = []

    def collect(hwnd: int, _context: object) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
        except Exception:
            return True

        if is_smartadvisor_window_identity(title, class_name):
            handles.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)
    return handles


def _window_area(hwnd: int) -> int:
    import win32gui

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return 0
    return max(0, right - left) * max(0, bottom - top)


def _preferred_native_handle(handles: list[int]) -> int | None:
    """Prefer the foreground match, then the largest visible window."""

    if not handles:
        return None

    import win32gui

    try:
        foreground = win32gui.GetForegroundWindow()
    except Exception:
        foreground = None
    if foreground in handles:
        return foreground

    return max(handles, key=_window_area)


def _element_handle(element: Any) -> int | None:
    """Read a wrapper's native HWND without depending on one backend."""

    info = getattr(element, "element_info", None)
    handle = getattr(info, "handle", None)
    if handle is None:
        handle = getattr(element, "handle", None)

    try:
        native_handle = int(handle)
    except (TypeError, ValueError):
        return None
    return native_handle if native_handle else None


def _native_named_descendants(
    parent_handle: int,
    expected_name: str,
) -> list[int]:
    """Find visible WinForms descendants by their exact native text."""

    import win32gui

    handles: list[int] = []

    def collect(hwnd: int, _context: object) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            name = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
        except Exception:
            return True

        if (
            name.strip().casefold() == expected_name.casefold()
            and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
        ):
            handles.append(hwnd)
        return True

    win32gui.EnumChildWindows(parent_handle, collect, None)
    return handles


def is_open_bill_frame_identity(
    name: str,
    automation_id: str,
    class_name: str,
) -> bool:
    """Match the stable UIA identity supplied for the Open Bill group."""

    return (
        name.strip().casefold() == OPEN_BILL_FRAME_NAME.casefold()
        and automation_id == OPEN_BILL_FRAME_AUTOMATION_ID
        and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
    )


def is_bill_search_frame_identity(
    name: str,
    automation_id: str,
    class_name: str,
) -> bool:
    """Match the stable UIA identity supplied for Bill Records."""

    return (
        name.strip().casefold() == BILL_SEARCH_FRAME_NAME.casefold()
        and automation_id == BILL_SEARCH_FRAME_AUTOMATION_ID
        and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
    )


def _element_name(element: Any) -> str:
    info = getattr(element, "element_info", None)
    try:
        name = str(element.window_text() or "")
    except Exception:
        name = ""
    return name or str(getattr(info, "name", "") or "")


def _find_frame_in_open_bill(
    open_bill: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Use the narrow Open Bill subtree if native frame lookup is unavailable."""

    try:
        descendants = list(open_bill.descendants())
    except Exception as exc:
        if trace:
            trace.record(
                "descendant_frame_search",
                "any",
                "descendant_scan_failed",
                exception=type(exc).__name__,
            )
        return None

    for element in descendants:
        info = element.element_info
        if is_open_bill_frame_identity(
            _element_name(element),
            str(getattr(info, "automation_id", "") or ""),
            str(getattr(info, "class_name", "") or ""),
        ):
            if trace:
                trace.record(
                    "descendant_frame_search", "any", "resolved"
                )
            return element
    if trace:
        trace.record(
            "descendant_frame_search",
            "any",
            "not_found",
            descendant_count=len(descendants),
        )
    return None


def _find_open_bill_in_main(
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Fall back to the supplied UIA ancestry when HWND nesting differs."""

    try:
        descendants = list(main_window.descendants(control_type="Window"))
    except Exception:
        try:
            descendants = list(main_window.descendants())
        except Exception as exc:
            if trace:
                trace.record(
                    "open_bill_in_main_descendants",
                    "uia",
                    "descendant_scan_failed",
                    exception=type(exc).__name__,
                )
            return None

    for element in descendants:
        info = element.element_info
        if (
            _element_name(element).strip().casefold()
            == OPEN_BILL_WINDOW_TITLE.casefold()
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            if trace:
                trace.record(
                    "open_bill_in_main_descendants", "uia", "resolved"
                )
            return element
    if trace:
        trace.record(
            "open_bill_in_main_descendants",
            "uia",
            "not_found",
            descendant_count=len(descendants),
        )
    return None


def _find_open_bill_process_window(
    desktop: Any,
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Find Open Bill by its own exact identity, independent of any
    assumption that it shares the main window's process ID.

    A Citrix-hosted modal is not guaranteed to report the same process ID
    as its logical parent, so this scans every top-level window rather than
    pre-filtering by `main_window`'s process, the same way the main window
    itself is found by identity alone.
    """

    stage = "process_window_title_search"
    main_process_id = getattr(main_window.element_info, "process_id", None)

    try:
        windows = list(desktop.windows())
    except Exception as exc:
        if trace:
            trace.record(
                stage,
                "any",
                "window_enumeration_failed",
                exception=type(exc).__name__,
            )
        return None

    matches = []
    for window in windows:
        info = window.element_info
        if (
            _element_name(window).strip().casefold()
            == OPEN_BILL_WINDOW_TITLE.casefold()
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            matches.append(window)

    if len(matches) == 1:
        if trace:
            matched_process_id = getattr(
                matches[0].element_info, "process_id", None
            )
            trace.record(
                stage,
                "any",
                "resolved",
                window_count=len(windows),
                same_process=(
                    main_process_id is not None
                    and matched_process_id == main_process_id
                ),
            )
        return matches[0]

    actionable = [
        window
        for window in matches
        if _find_frame_in_open_bill(window, trace=trace) is not None
    ]
    if len(actionable) == 1:
        if trace:
            trace.record(
                stage,
                "any",
                "resolved_by_actionable_frame",
                title_match_count=len(matches),
            )
        return actionable[0]

    if trace:
        trace.record(
            stage,
            "any",
            "title_not_uniquely_matched",
            window_count=len(windows),
            title_match_count=len(matches),
        )
    return None


def _direct_element_children(element_info: Any) -> list[Any]:
    """Read one UIA level while preserving partial-tree reliability."""

    try:
        return list(element_info.children())
    except Exception:
        return []


def _strict_uia_open_bill_frame(
    desktop: Any,
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Resolve the exact hierarchy proven by the object extractor.

    Open Bill is matched by its own exact identity across every top-level
    UIA window, not pre-filtered to `main_window`'s process ID - a
    Citrix-hosted modal is not guaranteed to report the same process as its
    logical parent.
    """

    stage = "strict_uia_hierarchy"
    main_process_id = getattr(main_window.element_info, "process_id", None)

    try:
        all_windows = list(desktop.windows())
    except Exception as exc:
        if trace:
            trace.record(
                stage,
                "uia",
                "window_enumeration_failed",
                exception=type(exc).__name__,
            )
        return None

    open_bill_matches = []
    for window in all_windows:
        info = window.element_info
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_WINDOW_AUTOMATION_ID
            and str(getattr(info, "name", "") or "").strip().casefold()
            == OPEN_BILL_WINDOW_TITLE.casefold()
            and str(getattr(info, "control_type", "") or "") == "Window"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            open_bill_matches.append(window)

    if len(open_bill_matches) != 1:
        if trace:
            trace.record(
                stage,
                "uia",
                "open_bill_not_uniquely_matched",
                window_count=len(all_windows),
                open_bill_match_count=len(open_bill_matches),
            )
        return None

    if trace:
        matched_process_id = getattr(
            open_bill_matches[0].element_info, "process_id", None
        )
        trace.record(
            stage,
            "uia",
            "open_bill_matched",
            same_process=(
                main_process_id is not None
                and matched_process_id == main_process_id
            ),
        )

    frame_matches = []
    for info in _direct_element_children(
        open_bill_matches[0].element_info
    ):
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_FRAME_AUTOMATION_ID
            and str(getattr(info, "name", "") or "").strip().casefold()
            == OPEN_BILL_FRAME_NAME.casefold()
            and str(getattr(info, "control_type", "") or "") == "Group"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            frame_matches.append(info)

    if len(frame_matches) != 1:
        if trace:
            trace.record(
                stage,
                "uia",
                "frame_not_uniquely_matched",
                direct_child_count=len(
                    _direct_element_children(open_bill_matches[0].element_info)
                ),
                frame_match_count=len(frame_matches),
            )
        return None
    frame_info = frame_matches[0]

    frame_children = _direct_element_children(frame_info)
    action_matches = [
        info
        for info in frame_children
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_ACTION_AUTOMATION_ID
            and str(getattr(info, "control_type", "") or "")
            == "Button"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        )
    ]
    if len(action_matches) != 1:
        if trace:
            trace.record(
                stage,
                "uia",
                "action_not_uniquely_matched",
                frame_direct_child_count=len(frame_children),
                action_match_count=len(action_matches),
            )
        return None

    frame_handle = _safe_int_handle(
        getattr(frame_info, "handle", None)
    )
    if frame_handle is None:
        if trace:
            trace.record(stage, "uia", "frame_handle_missing")
        return None
    try:
        wrapped = desktop.window(handle=frame_handle)
    except Exception as exc:
        if trace:
            trace.record(
                stage,
                "uia",
                "frame_handle_wrap_failed",
                exception=type(exc).__name__,
            )
        return None

    if trace:
        trace.record(stage, "uia", "resolved")
    return wrapped


def _safe_int_handle(value: object) -> int | None:
    try:
        handle = int(value)
    except (TypeError, ValueError):
        return None
    return handle if handle else None


def find_direct_uia_control(
    backend: str,
    parent: Any,
    automation_id: str,
) -> Any | None:
    """Wrap one exact direct UIA child by its dynamic native handle."""

    if backend != "uia":
        return None
    parent_info = getattr(parent, "element_info", None)
    if parent_info is None:
        return None

    matches = [
        info
        for info in _direct_element_children(parent_info)
        if (
            str(getattr(info, "automation_id", "") or "")
            == automation_id
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        )
    ]
    if len(matches) != 1:
        return None

    handle = _safe_int_handle(getattr(matches[0], "handle", None))
    if handle is None:
        return None

    from pywinauto import Desktop

    try:
        return Desktop(backend=backend).window(handle=handle)
    except Exception:
        return None


def find_bill_search_frame(
    backend: str,
    roots: Iterable[Any],
) -> Any | None:
    """Resolve frmBillSearch -> Frame1/Bill Records from visible roots."""

    if backend != "uia":
        return None

    bill_search_matches: list[Any] = []
    for root in roots:
        candidates = [root]
        try:
            candidates.extend(root.descendants())
        except Exception:
            pass

        for element in candidates:
            info = getattr(element, "element_info", None)
            if info is None:
                continue
            if (
                str(getattr(info, "automation_id", "") or "")
                == BILL_SEARCH_WINDOW_AUTOMATION_ID
                and str(getattr(info, "name", "") or "").strip().casefold()
                == BILL_SEARCH_WINDOW_TITLE.casefold()
                and str(getattr(info, "control_type", "") or "") == "Window"
                and str(getattr(info, "class_name", "") or "").startswith(
                    SMARTADVISOR_WINDOW_CLASS_PREFIX
                )
            ):
                bill_search_matches.append(element)

    if len(bill_search_matches) != 1:
        return None

    frame = find_direct_uia_control(
        backend,
        bill_search_matches[0],
        BILL_SEARCH_FRAME_AUTOMATION_ID,
    )
    if frame is None:
        return None

    info = getattr(frame, "element_info", None)
    if info is None or not is_bill_search_frame_identity(
        _element_name(frame),
        str(getattr(info, "automation_id", "") or ""),
        str(getattr(info, "class_name", "") or ""),
    ):
        return None
    return frame


def find_open_bill_frame(
    backend: str,
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Handshake through Main System -> Open Bill -> Frame1."""

    from pywinauto import Desktop

    main_handle = _element_handle(main_window)
    desktop = Desktop(backend=backend)
    if backend == "uia":
        strict_frame = _strict_uia_open_bill_frame(
            desktop,
            main_window,
            trace=trace,
        )
        if strict_frame is not None:
            return strict_frame

    open_bill = _find_open_bill_process_window(
        desktop, main_window, trace=trace
    )

    if open_bill is None and main_handle is not None:
        open_bill_handles = _native_named_descendants(
            main_handle,
            OPEN_BILL_WINDOW_TITLE,
        )
        open_bill_handle = _preferred_native_handle(open_bill_handles)
        if trace:
            trace.record(
                "native_child_search",
                backend,
                "resolved" if open_bill_handle is not None else "not_found",
                candidate_count=len(open_bill_handles),
            )
        if open_bill_handle is not None:
            open_bill = desktop.window(handle=open_bill_handle)

    if open_bill is None:
        open_bill = _find_open_bill_in_main(main_window, trace=trace)
    if open_bill is None:
        return None

    open_bill_handle = _element_handle(open_bill)
    if open_bill_handle is not None:
        frame_handles = _native_named_descendants(
            open_bill_handle,
            OPEN_BILL_FRAME_NAME,
        )
        frame_handle = _preferred_native_handle(frame_handles)
        if frame_handle is not None:
            frame = desktop.window(handle=frame_handle)
            info = frame.element_info
            if is_open_bill_frame_identity(
                _element_name(frame),
                str(getattr(info, "automation_id", "") or ""),
                str(getattr(info, "class_name", "") or ""),
            ):
                if trace:
                    trace.record(
                        "native_frame_search", backend, "resolved"
                    )
                return frame
        if trace:
            trace.record(
                "native_frame_search",
                backend,
                "not_found",
                candidate_count=len(frame_handles),
            )

    return _find_frame_in_open_bill(open_bill, trace=trace)


def _element_identity(window: Any) -> tuple[str, str]:
    """Read only static top-level identity properties."""

    info = window.element_info
    title = ""
    class_name = str(getattr(info, "class_name", "") or "")

    try:
        title = str(window.window_text() or "")
    except Exception:
        title = str(getattr(info, "name", "") or "")

    return title, class_name


def find_smartadvisor_window(
    backend: str,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Find SmartAdvisor by exact native HWND, with a strict UIA fallback."""

    from pywinauto import Desktop

    desktop = Desktop(backend=backend)

    native_handles = _native_smartadvisor_handles()
    native_handle = _preferred_native_handle(native_handles)
    if native_handle is not None:
        try:
            window = desktop.window(handle=native_handle)
        except Exception as exc:
            if trace:
                trace.record(
                    "main_window_native_handle",
                    backend,
                    "wrap_failed",
                    exception=type(exc).__name__,
                    candidate_count=len(native_handles),
                )
        else:
            if trace:
                trace.record(
                    "main_window_native_handle",
                    backend,
                    "resolved",
                    candidate_count=len(native_handles),
                )
            return window

    for window in desktop.windows():
        title, class_name = _element_identity(window)
        if is_smartadvisor_window_identity(title, class_name):
            if trace:
                trace.record(
                    "main_window_uia_fallback", backend, "resolved"
                )
            return window

    if trace:
        trace.record(
            "main_window_uia_fallback",
            backend,
            "not_found",
            native_candidate_count=len(native_handles),
        )
    return None


def probe_backend(
    backend: str,
    controls: tuple[ControlSpec, ...] = NO_BILL_ON_FILE_CONTROLS,
) -> dict[str, object]:
    """Probe one backend without clicking or reading control values."""

    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported backend: {backend}")

    try:
        window = find_smartadvisor_window(backend)
    except Exception as exc:
        return {
            "backend": backend,
            "window_status": "backend_error",
            "error_code": type(exc).__name__,
            "controls": [],
        }

    if window is None:
        return {
            "backend": backend,
            "window_status": "not_found",
            "error_code": None,
            "controls": [],
        }

    try:
        descendants = [window, *window.descendants()]
    except Exception as exc:
        return {
            "backend": backend,
            "window_status": "descendant_scan_error",
            "error_code": type(exc).__name__,
            "controls": [],
        }

    results = [
        _probe_control(backend, descendants, spec).to_public_dict()
        for spec in controls
    ]
    return {
        "backend": backend,
        "window_status": "found",
        "error_code": None,
        "controls": results,
    }


def scan_controls(
    backends: tuple[str, ...] = SUPPORTED_BACKENDS,
) -> dict[str, object]:
    """Return a PII-safe control validation report."""

    return {
        "schema_version": 1,
        "utility_version": "0.4.5",
        "workflow": WORKFLOW_NAME,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "privacy": {
            "includes_control_text": False,
            "includes_field_values": False,
            "includes_window_titles": False,
            "includes_credentials": False,
        },
        "backend_results": [probe_backend(backend) for backend in backends],
    }


# ==========================================================================
# SECTION 6 - THE DRIVER: doing things to controls
# ================================================
#
# A thin layer over pywinauto. Every method follows the same shape:
#
#     resolve the spec  ->  perform the action  ->  wrap any failure as
#     AutomationError
#
# `resolve()` is the important one. It polls until EXACTLY ONE visible, enabled
# element matches. Not "the first match" - exactly one. If two match it raises
# selector_ambiguous rather than clicking a guess. That strictness is deliberate:
# clicking the wrong bill is much worse than stopping.
#
# Things worth understanding here:
#
#   click()          Uses set_focus() then click_input(), a REAL mouse click.
#                    Note that pywinauto's .click() usually routes through the
#                    UIA InvokePattern instead, which some of these controls
#                    ignore. click_input() is the meaningfully different path.
#
#   focus_grid()     The search results grid only accepts arrow keys once focus
#                    is genuinely inside it, and a real click is the only
#                    reliable way in.
#
#   select_tab()     Switches the bill window's tab. It does NOT trust the
#                    keystroke: after each attempt it re-reads the tab control's
#                    Name (which is the selected page's text) to confirm the
#                    switch happened. It has to, because the control publishes
#                    only the SELECTED page's children - the controls we want do
#                    not exist until the switch has actually occurred. Three
#                    mechanisms are tried in order and the winner is logged.
#
#   _find_scope()    Resolves and CACHES a container. Caching matters enormously:
#                    one live run spent 28 seconds resolving frmBillEntry while
#                    scanning only 64 elements. The cost is per element, roughly
#                    440ms per COM property read over Citrix. Hence also
#                    SCOPE_SEARCH_DEPTH = 2.
#
#   invalidate_scopes()  Must be called once per candidate row, because each row
#                    opens a BRAND NEW bill window and a cached handle from the
#                    previous row is stale.
#
#   scan_texts()     Diagnostic only, and slow. Reads every control whose
#                    AutomationId starts with a prefix.
#
# Original file: src/smartadvisor_automation/driver.py
# ==========================================================================

# A scoped selector's container is looked up from the top-level windows.
# Keep this as shallow as the containers allow: a live run resolved
# frmBillEntry in 28s having scanned only 64 elements, so the cost is per
# element -- roughly 440ms for one COM property read over Citrix -- not tree
# size. frmBillEntry sits two levels below the main window (an anonymous pane
# in between), so two is enough. Falls back to an unrestricted walk if the
# backend does not support a depth argument.
SCOPE_SEARCH_DEPTH = 2


class SmartAdvisorDriver:
    """Small pywinauto adapter that resolves every selector before acting."""

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        poll_interval: float = 0.25,
        attach_timeout: float = 6.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.attach_timeout = attach_timeout
        self.backend: str | None = None
        self.process_id: int | None = None
        self._landmark_scope: Any | None = None
        self._landmark_automation_id: str | None = None
        self._log_callback = log
        self._scope_cache: dict[str, Any] = {}

    def _log(self, message: str) -> None:
        """Record a selector-level debug line.

        Driver lines carry selector metadata and outcomes. The workflow also
        logs amount values by decision, so a saved log is sensitive; see the
        privacy note in `recentconvo.md`.
        """

        if self._log_callback is not None:
            self._log_callback(message)

    @staticmethod
    def _describe(spec: ControlSpec) -> str:
        if spec.automation_id:
            described = spec.automation_id
        else:
            described = f"name={spec.name!r}"
        if spec.scope_automation_id:
            described = f"{spec.scope_automation_id}/{described}"
        return described

    def attach(
        self,
        landmark: ControlSpec,
        *,
        timeout: float | None = None,
    ) -> str:
        """Handshake through Open Bill/Frame1, retrying while it renders.

        Open Bill can take a moment to become enumerable (Citrix window
        registration lag) after the user opens it, so this polls the same
        way `resolve()` does rather than giving up after one pass.
        """

        trace = DiagnosticTrace()
        deadline = time.monotonic() + (
            self.attach_timeout if timeout is None else timeout
        )
        saw_smartadvisor_window = False
        saw_open_bill_frame = False
        launch_stage = 0
        attempt = 0

        while True:
            attempt += 1
            if attempt > 1:
                trace.record("attach_attempt", "", "retry", attempt=attempt)

            for backend in SUPPORTED_BACKENDS:
                try:
                    window = find_smartadvisor_window(backend, trace=trace)
                except Exception as exc:
                    trace.record(
                        "main_window_lookup",
                        backend,
                        "raised",
                        exception=type(exc).__name__,
                    )
                    continue
                if window is None:
                    continue
                saw_smartadvisor_window = True

                process_id = getattr(
                    window.element_info, "process_id", None
                )
                if process_id is None:
                    trace.record(
                        "main_window_lookup", backend, "no_process_id"
                    )
                    continue

                try:
                    landmark_scope = find_open_bill_frame(
                        backend, window, trace=trace
                    )
                except Exception as exc:
                    trace.record(
                        "open_bill_frame_lookup",
                        backend,
                        "raised",
                        exception=type(exc).__name__,
                    )
                    continue
                if landmark_scope is None:
                    if backend == "uia":
                        launch_stage = self._try_launch_open_bill(
                            window, launch_stage, trace=trace
                        )
                    continue
                saw_open_bill_frame = True

                direct_landmark = find_direct_uia_control(
                    backend,
                    landmark_scope,
                    landmark.automation_id,
                )
                if direct_landmark is not None:
                    landmark_scope = direct_landmark

                self.backend = backend
                self.process_id = int(process_id)
                self._landmark_scope = landmark_scope
                self._landmark_automation_id = landmark.automation_id
                try:
                    self.resolve(landmark, timeout=2.0)
                except AutomationError as exc:
                    trace.record(
                        "landmark_resolve",
                        backend,
                        "failed",
                        error_code=exc.code,
                    )
                    self.backend = None
                    self.process_id = None
                    self._landmark_scope = None
                    self._landmark_automation_id = None
                    continue
                return backend

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.poll_interval, remaining))

        if not saw_smartadvisor_window:
            code = "smartadvisor_window_not_found"
        elif not saw_open_bill_frame:
            code = "smartadvisor_open_bill_frame_not_accessible"
        else:
            code = "smartadvisor_controls_not_accessible"
        raise AutomationError(
            code, step=landmark.step, diagnostics=trace.to_report()
        )

    def _try_launch_open_bill(
        self,
        main_window: Any,
        launch_stage: int,
        *,
        trace: DiagnosticTrace,
    ) -> int:
        """Send Ctrl+O once, then only poll for the modal Open Bill window."""

        if launch_stage == 0:
            self._send_open_bill_shortcut(main_window, trace=trace)
            return 1
        return launch_stage

    @staticmethod
    def _send_open_bill_shortcut(
        main_window: Any, *, trace: DiagnosticTrace
    ) -> None:
        """Send the application's Ctrl+O Open Bill accelerator once."""

        stage = "open_bill_launch"
        try:
            main_window.set_focus()
            main_window.type_keys("^o")
        except Exception as exc:
            trace.record(
                stage,
                "uia",
                "shortcut_failed",
                exception=type(exc).__name__,
            )
            return

        trace.record(stage, "uia", "shortcut_sent")

    def _windows_for_process(self) -> list[Any]:
        if self.backend is None or self.process_id is None:
            raise AutomationError("not_attached")

        from pywinauto import Desktop

        try:
            return list(
                Desktop(backend=self.backend).windows(
                    process=self.process_id,
                    visible_only=True,
                    enabled_only=False,
                )
            )
        except Exception as exc:
            raise AutomationError("window_enumeration_failed") from exc

    @staticmethod
    def _elements_in_scope(
        scope: Any, *, depth: int | None = None
    ) -> list[Any]:
        elements = [scope]
        if depth is not None:
            try:
                elements.extend(scope.descendants(depth=depth))
                return elements
            except Exception:
                # Backend without depth support; fall through to a full walk.
                pass

        try:
            elements.extend(scope.descendants())
        except Exception:
            pass
        return elements

    def invalidate_scopes(self) -> None:
        """Forget cached containers.

        Each candidate row opens a fresh bill window, so a cached handle from
        the previous row must not be reused.
        """

        self._scope_cache.clear()

    def _find_scope(self, scope_automation_id: str) -> Any | None:
        """Resolve the single container a scoped selector searches inside.

        Cached, because resolving a container means walking top-level window
        subtrees and the same container is used by several steps in a row.
        """

        cached = self._scope_cache.get(scope_automation_id)
        if cached is not None and self._safe_state(cached, "is_visible"):
            return cached

        started = time.monotonic()
        candidates: list[Any] = []
        for window in self._windows_for_process():
            candidates.extend(
                self._elements_in_scope(window, depth=SCOPE_SEARCH_DEPTH)
            )

        matches = matching_elements(candidates, scope_automation_id)
        actionable = [
            element
            for element, _strategy in matches
            if self._safe_state(element, "is_visible")
        ]
        elapsed = time.monotonic() - started
        if len(actionable) != 1:
            self._scope_cache.pop(scope_automation_id, None)
            self._log(
                f"scope {scope_automation_id} not resolved in {elapsed:.1f}s "
                f"(matches={len(actionable)}, scanned={len(candidates)})"
            )
            return None

        self._scope_cache[scope_automation_id] = actionable[0]
        self._log(
            f"scope {scope_automation_id} resolved in {elapsed:.1f}s "
            f"(scanned={len(candidates)})"
        )
        return actionable[0]

    def _all_elements(self, spec: ControlSpec) -> list[Any]:
        if (
            self._landmark_scope is not None
            and spec.automation_id
            and spec.automation_id == self._landmark_automation_id
        ):
            return self._elements_in_scope(self._landmark_scope)

        if spec.scope_automation_id:
            scope = self._find_scope(spec.scope_automation_id)
            if scope is None:
                return []
            return self._elements_in_scope(scope)

        if spec.automation_id in BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS:
            frame = find_bill_search_frame(
                self.backend or "",
                self._windows_for_process(),
            )
            if frame is None:
                return []
            return self._elements_in_scope(frame)

        elements: list[Any] = []
        for window in self._windows_for_process():
            elements.extend(
                self._elements_in_scope(window, depth=spec.search_depth)
            )
        return elements

    def resolve(
        self,
        spec: ControlSpec,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Wait for exactly one visible, enabled selector match."""

        deadline = time.monotonic() + (
            self.timeout if timeout is None else timeout
        )
        last_match_count = 0

        while time.monotonic() < deadline:
            try:
                matches = matching_spec_elements(
                    self._all_elements(spec), spec
                )
            except AutomationError:
                raise
            except Exception:
                matches = []

            actionable = [
                element
                for element, _strategy in matches
                if self._safe_state(element, "is_visible")
                and self._safe_state(element, "is_enabled")
            ]
            last_match_count = len(actionable)
            if last_match_count == 1:
                return actionable[0]

            time.sleep(self.poll_interval)

        code = (
            "selector_ambiguous"
            if last_match_count > 1
            else "selector_not_found"
        )
        self._log(
            f"resolve {self._describe(spec)} -> {code} "
            f"(matches={last_match_count})"
        )
        raise AutomationError(code, step=spec.step)

    @staticmethod
    def _safe_state(element: Any, method_name: str) -> bool:
        try:
            return bool(getattr(element, method_name)())
        except Exception:
            return False

    def click(self, spec: ControlSpec) -> None:
        element = self.resolve(spec)
        try:
            element.set_focus()
            element.click_input()
        except Exception as exc:
            raise AutomationError("click_failed", step=spec.step) from exc
        self._log(f"click {self._describe(spec)}")

    def focus_grid(self, spec: ControlSpec) -> None:
        """Put keyboard focus inside the owner-drawn results grid.

        Arrow navigation only works once focus is genuinely inside the pane,
        and a real click is the only reliable way in. Where the click lands
        does not matter: the caller's calibration nudge normalises the
        selection onto the topmost row afterwards.
        """

        element = self.resolve(spec)
        try:
            element.set_focus()
        except Exception:
            # click_input() can still put focus inside an unfocused pane.
            pass

        try:
            element.click_input()
        except Exception as exc:
            raise AutomationError("focus_failed", step=spec.step) from exc
        self._log(f"focus {self._describe(spec)}")

    def send_keys(self, spec: ControlSpec, keys: str) -> None:
        """Type into an already-focused control without re-clicking it."""

        if not keys:
            return

        element = self.resolve(spec)
        try:
            element.type_keys(keys, set_foreground=True)
        except Exception as exc:
            raise AutomationError("send_keys_failed", step=spec.step) from exc
        self._log(f"keys {self._describe(spec)} {keys}")

    @staticmethod
    def _element_name(element: Any) -> str:
        try:
            return str(element.window_text() or "").strip()
        except Exception:
            return ""

    def _wait_for_tab_name(
        self,
        element: Any,
        *,
        wanted: str,
        differs_from: str,
        timeout: float,
    ) -> str:
        """Poll the tab control's Name until it changes or the wait expires.

        The Name is read live from the provider, so it is a reliable signal —
        but the app needs time to repaint, and over Citrix that is not
        instant. Reading immediately after a keystroke sees the old page and
        makes a working keystroke look like a no-op.
        """

        deadline = time.monotonic() + timeout
        name = self._element_name(element)
        while True:
            if wanted in name.casefold() or name != differs_from:
                return name
            if time.monotonic() >= deadline:
                return name
            time.sleep(self.poll_interval)
            name = self._element_name(element)

    def _click_tab_strip(self, element: Any) -> bool:
        """Click the tab strip so arrow keys reach it.

        The strip band is derived from the control's own rectangle and its
        page's rectangle rather than hardcoded, then the leftmost tab is
        clicked. Selecting whichever tab is leftmost is harmless: the caller
        arrows on from wherever it lands and verifies by Name.
        """

        try:
            rect = element.rectangle()
            strip_height = 24
            children = element.children()
            if children:
                page_top = children[0].rectangle().top
                derived = page_top - rect.top
                if 8 <= derived <= 80:
                    strip_height = derived
            element.click_input(coords=(30, max(4, strip_height // 2)))
        except Exception:
            return False
        return True

    def select_tab(
        self,
        spec: ControlSpec,
        *,
        expected_fragment: str,
        accelerator: str,
        next_key: str,
        fallback_key: str,
        max_presses: int,
        settle_timeout: float,
    ) -> None:
        """Bring a tab page to the front, verifying by the control's Name.

        This control publishes only the selected page's children, so the
        wanted controls do not exist until the switch has actually happened —
        an unverified keystroke is worthless here.

        Which mechanism works has not been pinned down: the "&L" in the tab
        text is a rendered underline and the control reports no AccessKey,
        yet the accelerator appears to do something; arrowing needs the strip
        to hold focus, which it may not after a dialog. So each mechanism is
        tried in turn and the one that worked is logged, rather than assumed.
        """

        element = self.resolve(spec)
        wanted = expected_fragment.casefold()

        start = self._element_name(element)
        if wanted in start.casefold():
            self._log(
                f"tab {self._describe(spec)} already on "
                f"{start}"
            )
            return
        self._log(
            f"tab {self._describe(spec)} starts on {start}"
        )

        for attempt in ("accelerator", "click_then_arrow", "fallback_key"):
            if attempt == "accelerator":
                worked = self._tab_by_accelerator(
                    element,
                    accelerator=accelerator,
                    wanted=wanted,
                    settle_timeout=settle_timeout,
                )
            elif attempt == "click_then_arrow":
                worked = self._tab_by_keypresses(
                    element,
                    key=next_key,
                    wanted=wanted,
                    max_presses=max_presses,
                    settle_timeout=settle_timeout,
                    click_strip_first=True,
                )
            else:
                worked = self._tab_by_keypresses(
                    element,
                    key=fallback_key,
                    wanted=wanted,
                    max_presses=max_presses,
                    settle_timeout=settle_timeout,
                    click_strip_first=False,
                )

            if worked:
                self._log(f"tab reached via {attempt}")
                return
            self._log(f"tab {attempt} did not reach {expected_fragment!r}")

        raise AutomationError("tab_not_found", step=spec.step)

    def _tab_by_accelerator(
        self,
        element: Any,
        *,
        accelerator: str,
        wanted: str,
        settle_timeout: float,
    ) -> bool:
        before = self._element_name(element)
        try:
            element.type_keys(accelerator, set_foreground=True)
        except Exception:
            return False

        name = self._wait_for_tab_name(
            element,
            wanted=wanted,
            differs_from=before,
            timeout=settle_timeout,
        )
        self._log(f"tab after accelerator: {name}")
        return wanted in name.casefold()

    def _tab_by_keypresses(
        self,
        element: Any,
        *,
        key: str,
        wanted: str,
        max_presses: int,
        settle_timeout: float,
        click_strip_first: bool,
    ) -> bool:
        if click_strip_first and not self._click_tab_strip(element):
            self._log("tab strip click failed")
            return False

        try:
            element.set_focus()
        except Exception:
            # The strip may already hold focus; the click above also grants it.
            pass

        seen: set[str] = set()
        for _press in range(max_presses):
            before = self._element_name(element)
            if wanted in before.casefold():
                return True
            if before and before in seen:
                self._log(f"tab strip cycled using {key}")
                return False
            seen.add(before)

            try:
                element.type_keys(key, set_foreground=True)
            except Exception:
                return False

            name = self._wait_for_tab_name(
                element,
                wanted=wanted,
                differs_from=before,
                timeout=settle_timeout,
            )
            self._log(f"tab after {key}: {name}")
            if wanted in name.casefold():
                return True
            if name == before:
                # The keystroke moved nothing, so more of them will not help.
                self._log(f"tab unchanged by {key}")
                return False

        return False

    def is_present(
        self,
        spec: ControlSpec,
        *,
        timeout: float = 1.5,
    ) -> bool:
        """Check for an optional control without failing when it is absent."""

        try:
            self.resolve(spec, timeout=timeout)
        except AutomationError:
            self._log(f"optional {self._describe(spec)} absent")
            return False
        self._log(f"optional {self._describe(spec)} present")
        return True

    def invoke(self, spec: ControlSpec) -> None:
        """Invoke a UIA control without moving the mouse."""

        element = self.resolve(spec)
        try:
            element.iface_invoke.Invoke()
        except Exception as exc:
            raise AutomationError("invoke_failed", step=spec.step) from exc

    def click_with_invoke_fallback(
        self,
        spec: ControlSpec,
        confirmation_spec: ControlSpec,
        *,
        confirmation_timeout: float = 2.0,
    ) -> None:
        """Click with real mouse input, then invoke if no result appears."""

        element = self.resolve(spec)
        try:
            element.set_focus()
        except Exception:
            # click_input() can still activate an unfocused control.
            pass

        try:
            element.click_input()
        except Exception:
            pass
        else:
            try:
                self.resolve(
                    confirmation_spec,
                    timeout=confirmation_timeout,
                )
                return
            except AutomationError:
                # The click completed but did not expose the expected control.
                pass

        try:
            element.iface_invoke.Invoke()
        except Exception as exc:
            raise AutomationError(
                "click_and_invoke_failed",
                step=spec.step,
            ) from exc

    def clear(self, spec: ControlSpec) -> None:
        element = self.resolve(spec)
        try:
            element.set_edit_text("")
            return
        except Exception:
            pass

        try:
            element.set_focus()
            element.click_input()
            element.type_keys("^a{BACKSPACE}", set_foreground=True)
        except Exception as exc:
            raise AutomationError("clear_failed", step=spec.step) from exc

    def input_text(self, spec: ControlSpec, value: str) -> None:
        element = self.resolve(spec)
        try:
            element.set_edit_text(value)
            return
        except Exception:
            pass

        try:
            element.set_focus()
            element.click_input()
            element.type_keys("^a{BACKSPACE}", set_foreground=True)
            element.type_keys(
                value,
                with_spaces=True,
                set_foreground=True,
            )
        except Exception as exc:
            raise AutomationError("input_failed", step=spec.step) from exc

    def scan_texts(
        self,
        scope_automation_id: str,
        prefix: str,
    ) -> list[tuple[str, str]]:
        """Read every control in a scope whose AutomationId starts with prefix.

        Diagnostic only, and slow: it touches every element in the subtree at
        Citrix COM latency. Used to find which control-array index actually
        holds a wanted value when the index turns out to be positional.
        """

        scope = self._find_scope(scope_automation_id)
        if scope is None:
            return []

        started = time.monotonic()
        found: list[tuple[str, str]] = []
        for element in self._elements_in_scope(scope):
            info = getattr(element, "element_info", None)
            if info is None:
                continue
            automation_id = str(getattr(info, "automation_id", "") or "")
            if not automation_id.startswith(prefix):
                continue
            try:
                text = str(element.window_text() or "")
            except Exception:
                continue
            found.append((automation_id, text))

        elapsed = time.monotonic() - started
        self._log(
            f"scan {prefix}* in {scope_automation_id}: "
            f"{len(found)} control(s) in {elapsed:.1f}s"
        )
        return found

    def read_text(self, spec: ControlSpec) -> str:
        element = self.resolve(spec)
        candidates: list[str] = []

        try:
            candidates.append(str(element.window_text() or ""))
        except Exception:
            pass

        try:
            candidates.extend(str(value or "") for value in element.texts())
        except Exception:
            pass

        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate).strip()
            if normalized:
                return normalized

        raise AutomationError("empty_extracted_value", step=spec.step)


# ==========================================================================
# SECTION 7 - THE WORKFLOW: the algorithm itself
# ==============================================
#
# If you only read one section, read this one. Everything above is plumbing.
#
# THE PROBLEM
# -----------
# After searching, SmartAdvisor shows results in a custom owner-drawn grid
# (`fpSearchResult`). That grid publishes NO accessibility information at all -
# no Grid pattern, no Table pattern, no rows, no cells, and its MSAA description
# never changes when the selection moves. Clipboard copy does not work either.
# So the rows genuinely CANNOT be read.
#
# But several bills can match a claim + date, and we need the one with a
# particular charge amount.
#
# THE SOLUTION
# ------------
# Do not read the grid. Open each row in turn and read the amount from the bill
# itself. And because closing a bill and returning to a still-populated grid was
# unreliable, EVERY candidate re-runs the whole flow from Ctrl+O. Nothing is
# carried over between candidates. It is slower, but it means no state has to
# survive anything.
#
# For candidate row i (zero-based, row 0 = topmost):
#
#     Ctrl+O                     open the Open Bill window
#     _cmdSearch_1               opens Bill Search
#     clear txtClient
#     btnAdvacedSearch           reveal the advanced fields
#     txtClaimID  <- claim id
#     txtDOSFrom  <- date
#     cmdOK                      runs the search; grid fills
#     click inside fpSearchResult put keyboard focus in the grid
#     {DOWN} x1 then {UP} x1     CALIBRATE onto the top row (see below)
#     {DOWN} x i                 seek down to row i
#     {ENTER}                    confirm the row
#     cmdOk                      Open Bill's OK -> opens the bill
#     [radButton1]               only if the "bill is pended" warning appears
#     select the Lines tab
#     read _lblTotals_59         the charge amount
#     close the bill window      then i += 1
#
# WHY CALIBRATE
# -------------
# A freshly filled grid has an indeterminate selection, and the click that gave
# it focus may have landed on any row. One Down then one Up always ends on the
# TOP row, whatever happened before. So the click position does not matter. This
# runs every iteration because every iteration has a fresh grid.
#
# Do not confuse it with the seek. Calibration is 1 down + 1 up. The seek is the
# separate `{DOWN}` x i afterwards.
#
# WHEN DOES IT STOP
# -----------------
#   * Match found -> stop, report the row, leave the bill open for the user.
#   * The amount REPEATS the previous row's -> `{DOWN}` x i has clamped at the
#     last row, so we are re-reading a row already checked. There are no more
#     rows. Stop with no_matching_candidate_row.
#
# There is deliberately NO row limit. Cancel is the operator's stop control,
# checked once per row. MAX_ITERATIONS exists only so a control that stops
# responding cannot spin forever.
#
# KNOWN LIMITATION
# ----------------
# If two CONSECUTIVE rows genuinely share the same charge amount and neither
# matches, the loop stops early and reports no match even though more rows exist.
# Amount is the only value available, so this is inherent to the stop condition.
# It is a known behaviour, not a surprise.
#
# AMOUNT PARSING
# --------------
# The totals label holds two figures, like "1,952.43" then "(312.57)" on a second
# line. Only the plain one is compared, so everything from the first "(" is
# discarded. Note these values carry no "$" - an earlier version of
# `extract_amount` required one and silently returned the whole label instead.
#
# Comparison is by Decimal, so "1,952.43" equals "$1952.4300".
#
# Original file: src/smartadvisor_automation/workflow.py
# ==========================================================================

OUTCOME_MESSAGE = (
    "There is not a bill on file that matches this date of service and "
    "billed amount. Please resubmit the bill with medical reports to:"
)

# Safety valve only. There is deliberately no candidate-row limit: the loop
# stops when the charge amount repeats, which is what happens once the seek
# clamps at the last row. This ceiling exists purely so a control that stops
# responding cannot spin forever in an unattended moment.
MAX_ITERATIONS = 500

ProgressCallback = Callable[[str, str], None]
LogCallback = Callable[[str], None]


class WorkflowDriver(Protocol):
    def attach(self, landmark: ControlSpec) -> str: ...

    def click_with_invoke_fallback(
        self,
        spec: ControlSpec,
        confirmation_spec: ControlSpec,
    ) -> None: ...

    def click(self, spec: ControlSpec) -> None: ...

    def clear(self, spec: ControlSpec) -> None: ...

    def input_text(self, spec: ControlSpec, value: str) -> None: ...

    def read_text(self, spec: ControlSpec) -> str: ...

    def focus_grid(self, spec: ControlSpec) -> None: ...

    def send_keys(self, spec: ControlSpec, keys: str) -> None: ...

    def select_tab(
        self,
        spec: ControlSpec,
        *,
        expected_fragment: str,
        accelerator: str,
        next_key: str,
        fallback_key: str,
        max_presses: int,
        settle_timeout: float,
    ) -> None: ...

    def is_present(self, spec: ControlSpec) -> bool: ...

    def invalidate_scopes(self) -> None: ...

    def scan_texts(
        self, scope_automation_id: str, prefix: str
    ) -> list[tuple[str, str]]: ...


def validate_claim_id(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,64}", normalized):
        raise ValueError(
            "Claim ID may contain only letters, numbers, dots, underscores, "
            "slashes, and hyphens."
        )
    return normalized


def normalize_dos(value: str) -> str:
    normalized = value.strip()
    try:
        parsed = datetime.strptime(normalized, "%m/%d/%Y")
    except ValueError as exc:
        raise ValueError("DOS From must use MM/DD/YYYY.") from exc
    return parsed.strftime("%m/%d/%Y")


def validate_expected_amount(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"\$?\s*[\d,]*\d(?:\.\d{1,2})?", normalized):
        raise ValueError(
            "Expected Amount must be a number such as 1,952.43 or $1952.43."
        )
    return normalized


def extract_patient_account(raw_text: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_text).strip()
    match = re.search(
        r"Patient\s+Account\s*[-:]\s*(.+)$",
        normalized,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else normalized


def extract_amount(raw_text: str) -> str:
    """Pull the plain charge amount out of a Lines totals label.

    The totals label carries two figures — a plain charge amount and a
    parenthesised adjustment — and `driver.read_text` has already collapsed
    the newline between them into a space. Only the plain one is compared,
    so anything from the first "(" onwards is discarded before parsing.

    Note these values carry no "$", which is why the original dollar-anchored
    pattern could not read them.
    """

    normalized = re.sub(r"\s+", " ", raw_text).strip()
    plain, _, _ = normalized.partition("(")
    match = re.search(r"\$?\s?[\d,]*\d(?:\.\d{2})?", plain)
    return match.group(0).strip() if match else ""


def normalize_amount(value: str) -> Decimal:
    """Compare amounts by value, so 1,952.43 equals $1952.4300."""

    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not a readable amount: {value!r}") from exc


def describe_comparison(amount: str, expected: str, matched: bool) -> str:
    """State a candidate comparison so a rejection is explicit in the log.

    Masking amounts to shapes hid whether a mismatch was a different value or
    the wrong control entirely, and a log that only implied "compared and
    rejected" led to a wrong diagnosis. Both values are recorded by decision;
    see the privacy note in `recentconvo.md`.
    """

    verdict = "MATCH" if matched else "no match"
    return f"amount={amount} vs expected={expected} -> {verdict}"


class NoBillOnFileWorkflow:
    """Execute the supplied attended SmartAdvisor workflow."""

    def __init__(
        self,
        driver: WorkflowDriver,
        *,
        cancel_event: threading.Event | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
        diagnose_amounts: bool = False,
    ) -> None:
        self.driver = driver
        self.cancel_event = cancel_event or threading.Event()
        self.progress = progress or (lambda _step, _message: None)
        self.log = log or (lambda _message: None)
        self.diagnose_amounts = diagnose_amounts
        self._scanned_totals = False

    def _diagnose_amount_controls(self, expected: Decimal) -> None:
        """Report which totals control holds the expected amount.

        A backstop, not the main diagnostic: an Inspect capture confirmed
        `_lblTotals_59` is the right control, so this exists for the case
        where a future bill layout moves it. Runs at most once per run.
        """

        if self._scanned_totals:
            return
        self._scanned_totals = True

        self.progress("7.5", "Scanning totals controls (slow)")
        controls = self.driver.scan_texts(
            BILL_ENTRY_WINDOW_AUTOMATION_ID, BILL_LINES_AMOUNT_PREFIX
        )
        if not controls:
            self.log("amount-scan found no totals controls")
            return

        for automation_id, raw_text in controls:
            amount = extract_amount(raw_text)
            if not amount:
                self.log(f"amount-scan {automation_id} unparseable")
                continue
            try:
                matched = normalize_amount(amount) == expected
            except ValueError:
                self.log(f"amount-scan {automation_id} unparseable")
                continue
            verdict = "MATCHES EXPECTED" if matched else "no match"
            self.log(f"amount-scan {automation_id} amount={amount} {verdict}")

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise WorkflowCancelled()

    def _run_step(
        self,
        step: str,
        message: str,
        action: Callable[[], None],
    ) -> None:
        self._check_cancelled()
        self.progress(step, message)
        action()

    def _search(self, claim_id: str, dos_from: str) -> None:
        """Run Open Bill through to a populated results grid.

        Every candidate re-runs this from Ctrl+O. Nothing is carried over
        between candidates, which is what removes the need to close a bill
        and return to a still-populated grid.
        """

        self._check_cancelled()
        self.progress("attach", "Attaching to SmartAdvisor")
        backend = self.driver.attach(CONTROLS_BY_STEP["1"])
        self.log(f"attached backend={backend}")

        self._run_step(
            "1",
            "Opening search options",
            lambda: self.driver.click_with_invoke_fallback(
                CONTROLS_BY_STEP["1"],
                CONTROLS_BY_STEP["2"],
            ),
        )
        self._run_step(
            "2",
            "Clearing the search box",
            lambda: self.driver.clear(CONTROLS_BY_STEP["2"]),
        )
        self._run_step(
            "3",
            "Opening Advanced Search",
            lambda: self.driver.click(CONTROLS_BY_STEP["3"]),
        )
        self._run_step(
            "4",
            "Entering Claim ID",
            lambda: self.driver.input_text(CONTROLS_BY_STEP["4"], claim_id),
        )
        self._run_step(
            "5",
            "Entering DOS From",
            lambda: self.driver.input_text(CONTROLS_BY_STEP["5"], dos_from),
        )
        self._run_step(
            "6",
            "Running the search",
            lambda: self.driver.click(CONTROLS_BY_STEP["6"]),
        )

    def _select_row(self, row_index: int) -> None:
        """Focus the grid, calibrate to the top row, then seek down."""

        grid = CONTROLS_BY_STEP["7.0"]
        seek = CONTROLS_BY_STEP["7.1"]

        self._run_step(
            "7.0",
            "Focusing the results grid",
            lambda: self.driver.focus_grid(grid),
        )

        # A freshly populated grid has an indeterminate selection, so one
        # Down plus one Up lands on the topmost row regardless of where the
        # focusing click fell. This is calibration, not part of the seek.
        self._run_step(
            "7.1",
            "Calibrating to the first row",
            lambda: self.driver.send_keys(seek, GRID_CALIBRATE_DOWN),
        )
        self.driver.send_keys(seek, GRID_CALIBRATE_UP)

        if row_index:
            self.progress("7.1", f"Moving down to row {row_index + 1}")
            self.driver.send_keys(seek, GRID_SEEK_DOWN * row_index)

        self._check_cancelled()
        self.driver.send_keys(seek, GRID_CONFIRM_ROW)
        self.log(f"row {row_index} confirmed")

    def _read_candidate_amount(self) -> str:
        """Open the selected bill and read its Lines charge amount."""

        self._run_step(
            "7.2",
            "Opening the selected bill",
            lambda: self.driver.click(CONTROLS_BY_STEP["7.2"]),
        )

        warning = CONTROLS_BY_STEP["7.3"]
        self._check_cancelled()
        if self.driver.is_present(warning):
            self.progress("7.3", "Acknowledging the pended bill warning")
            self.driver.click(warning)

        # The tab control only publishes the selected page's children, so the
        # amount does not exist until Lines is genuinely selected. select_tab
        # confirms the switch from the control's own Name rather than firing
        # an accelerator and hoping.
        self._run_step(
            "7.4",
            "Switching to the Lines tab",
            lambda: self.driver.select_tab(
                CONTROLS_BY_STEP["7.4"],
                expected_fragment=BILL_LINES_TAB_NAME_FRAGMENT,
                accelerator=BILL_TAB_ACCELERATOR,
                next_key=BILL_TAB_NEXT_KEY,
                fallback_key=BILL_TAB_FALLBACK_KEY,
                max_presses=BILL_TAB_MAX_PRESSES,
                settle_timeout=BILL_TAB_SETTLE_TIMEOUT,
            ),
        )

        self._check_cancelled()
        self.progress("7.5", "Reading the charge amount")
        amount = extract_amount(self.driver.read_text(CONTROLS_BY_STEP["7.5"]))
        if not amount:
            self.log("amount not parseable from the totals label")
            raise AutomationError("amount_not_readable", step="7.5")
        self.log(f"amount read={amount}")
        return amount

    def run(
        self,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
    ) -> WorkflowResult:
        claim_id = validate_claim_id(claim_id)
        dos_from = normalize_dos(dos_from)
        expected_amount = validate_expected_amount(expected_amount)
        expected = normalize_amount(expected_amount)

        self.log(f"run start expected={expected_amount}")

        previous_amount: str | None = None
        row_index = 0

        while row_index < MAX_ITERATIONS:
            self._check_cancelled()
            self.progress(
                "candidate", f"Checking candidate row {row_index + 1}"
            )
            self.log(f"--- candidate row {row_index} ---")

            # Each row opens a fresh bill window, so any container cached for
            # the previous row is stale.
            self.driver.invalidate_scopes()
            self._search(claim_id, dos_from)
            self._select_row(row_index)
            amount = self._read_candidate_amount()

            if self.diagnose_amounts:
                self._diagnose_amount_controls(expected)

            matched = normalize_amount(amount) == expected
            self.log(
                f"row {row_index} "
                f"{describe_comparison(amount, expected_amount, matched)}"
            )

            if matched:
                self.progress(
                    "complete", f"Matched on row {row_index + 1}"
                )
                self.log(f"match on row {row_index}; bill left open")
                return WorkflowResult(
                    patient_account=None,
                    amount=amount,
                    outcome=OUTCOME_MESSAGE,
                    row_index=row_index,
                    rows_examined=row_index + 1,
                )

            if previous_amount is not None and amount == previous_amount:
                # The seek clamped at the last row, so this is a re-read of
                # the row already checked: the grid has no further rows.
                self.log(
                    f"row {row_index} repeated the previous amount; "
                    "last row reached"
                )
                # Nothing matched. The run has already failed, so reporting
                # which control would have matched costs nothing and saves a
                # rerun. The bill is still open, which the scan needs.
                self._diagnose_amount_controls(expected)
                self.driver.click(CONTROLS_BY_STEP["7.6"])
                raise AutomationError(
                    "no_matching_candidate_row", step="7.5"
                )

            previous_amount = amount
            self._run_step(
                "7.6",
                "Closing the bill and trying the next row",
                lambda: self.driver.click(CONTROLS_BY_STEP["7.6"]),
            )
            row_index += 1

        self.log(f"stopped after {MAX_ITERATIONS} iterations")
        raise AutomationError("candidate_iteration_limit", step="7.5")


# ==========================================================================
# SECTION 8 - THE USER INTERFACE (Tkinter)
# ========================================
#
# Plain Tkinter, no dependencies. Three things worth knowing:
#
# THREADING
# ---------
# The workflow runs on a BACKGROUND thread, because it takes minutes and would
# otherwise freeze the window. Tkinter is not thread-safe, so the worker never
# touches a widget. It puts messages on `self.events` (a queue.Queue) and
# `_poll_events()` drains that queue on the UI thread every 100ms. If you add a
# feature, follow this pattern - do not call a widget from the worker thread.
#
# CANCELLATION
# ------------
# `self.cancel_event` is a threading.Event. The workflow checks it between steps
# and raises WorkflowCancelled. This is the only way to stop a run, since there
# is no row limit.
#
# THE LOG PANEL AND PRIVACY
# -------------------------
# The Log panel DOES contain charge amounts, on purpose. Amounts were originally
# masked to shapes like "#,###.##", but that made a wrong value and a right value
# look identical and caused a real misdiagnosis. Now the log records each row's
# amount, the expected amount and the verdict.
#
# Consequences you must respect:
#
#   * A saved log is SENSITIVE. The panel says so and the saved file has a
#     warning header. Do not paste it into chat, tickets or email.
#   * Claim ID, DOS and Patient Account are still NEVER logged.
#   * The separate JSON diagnostics (SECTION 2) remain completely value-free.
#
# Original file: src/smartadvisor_automation/app.py
# ==========================================================================

# The log records charge amounts alongside selector metadata and step
# outcomes, by decision -- masking them to shapes hid whether a mismatch was a
# different value or the wrong control. A saved log is therefore sensitive.
# Claim ids, dates and patient accounts are still never logged. The redacted
# JSON diagnostics written by DiagnosticTrace stay value-free.
MAX_LOG_LINES = 2000


class AutomationApp:
    """Tkinter front end for the attended No Bill on File workflow."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Automation")
        self.root.geometry("760x860")
        self.root.minsize(680, 640)

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False

        self.claim_id = tk.StringVar()
        self.dos_from = tk.StringVar()
        self.expected_amount = tk.StringVar()
        self.patient_account = tk.StringVar()
        self.amount = tk.StringVar()
        self.matched_row = tk.StringVar()
        self.diagnose_amounts = tk.BooleanVar(value=False)
        self.status = tk.StringVar(
            value="Open and sign in to SmartAdvisor before running."
        )

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(
            container,
            text="No Bill on File",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(
            container,
            text=(
                "Attended workflow — SmartAdvisor must already be open "
                "and authenticated."
            ),
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(4, 18),
        )

        ttk.Label(container, text="Claim ID").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12), pady=6
        )
        self.claim_entry = ttk.Entry(
            container, textvariable=self.claim_id, width=36
        )
        self.claim_entry.grid(row=2, column=1, sticky=tk.EW, pady=6)

        ttk.Label(container, text="DOS From").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 12), pady=6
        )
        self.dos_entry = ttk.Entry(
            container, textvariable=self.dos_from, width=36
        )
        self.dos_entry.grid(row=3, column=1, sticky=tk.EW, pady=6)
        ttk.Label(
            container,
            text="MM/DD/YYYY",
            foreground="#666666",
        ).grid(row=4, column=1, sticky=tk.W)

        ttk.Label(container, text="Expected Amount").grid(
            row=5, column=0, sticky=tk.W, padx=(0, 12), pady=6
        )
        self.amount_entry = ttk.Entry(
            container, textvariable=self.expected_amount, width=36
        )
        self.amount_entry.grid(row=5, column=1, sticky=tk.EW, pady=6)
        ttk.Label(
            container,
            text="Charge amount to match, e.g. 1,952.43",
            foreground="#666666",
        ).grid(row=6, column=1, sticky=tk.W)

        actions = ttk.Frame(container)
        actions.grid(
            row=7,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(16, 16),
        )

        self.run_button = ttk.Button(
            actions, text="Run workflow", command=self._start_workflow
        )
        self.run_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(
            actions,
            text="Cancel",
            command=self._cancel_workflow,
            state=tk.DISABLED,
        )
        self.cancel_button.pack(side=tk.LEFT, padx=(8, 0))

        self.validate_button = ttk.Button(
            actions,
            text="Validate controls",
            command=self._start_validation,
        )
        self.validate_button.pack(side=tk.LEFT, padx=(8, 0))

        # On its own row: sharing the button row clipped it off-screen at the
        # default window width. Off by default because the scan touches every
        # element in the bill window at Citrix COM latency.
        self.diagnose_check = ttk.Checkbutton(
            container,
            text="Diagnose totals fields (slow)",
            variable=self.diagnose_amounts,
        )
        self.diagnose_check.grid(
            row=8, column=0, columnspan=2, sticky=tk.W, pady=(0, 12)
        )

        result_box = ttk.LabelFrame(container, text="Result", padding=12)
        result_box.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 12),
        )
        result_box.columnconfigure(1, weight=1)
        container.rowconfigure(9, weight=1)

        ttk.Label(result_box, text="Patient Account").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 12), pady=5
        )
        ttk.Entry(
            result_box,
            textvariable=self.patient_account,
            state="readonly",
        ).grid(row=0, column=1, sticky=tk.EW, pady=5)

        ttk.Label(result_box, text="Amount").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 12), pady=5
        )
        ttk.Entry(
            result_box,
            textvariable=self.amount,
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, pady=5)

        ttk.Label(result_box, text="Matched row").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12), pady=5
        )
        ttk.Entry(
            result_box,
            textvariable=self.matched_row,
            state="readonly",
        ).grid(row=2, column=1, sticky=tk.EW, pady=5)

        ttk.Label(result_box, text="Outcome").grid(
            row=3, column=0, sticky=tk.NW, padx=(0, 12), pady=5
        )
        self.outcome = tk.Text(
            result_box,
            height=5,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.outcome.grid(row=3, column=1, sticky="nsew", pady=5)
        result_box.rowconfigure(3, weight=1)

        result_actions = ttk.Frame(result_box)
        result_actions.grid(row=4, column=1, sticky=tk.W, pady=(8, 0))
        self.copy_button = ttk.Button(
            result_actions,
            text="Copy result",
            command=self._copy_result,
            state=tk.DISABLED,
        )
        self.copy_button.pack(side=tk.LEFT)
        ttk.Button(
            result_actions,
            text="Clear",
            command=self._clear_result,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._build_log_panel(container, row=10)

        ttk.Separator(container).grid(
            row=11, column=0, columnspan=2, sticky=tk.EW
        )
        ttk.Label(
            container,
            textvariable=self.status,
            anchor=tk.W,
        ).grid(
            row=12,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(10, 0),
        )

        self.claim_entry.focus_set()

    def _build_log_panel(self, container: ttk.Frame, *, row: int) -> None:
        """Scrolling step-by-step log for diagnosing a failed run."""

        log_box = ttk.LabelFrame(container, text="Log", padding=12)
        log_box.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 12),
        )
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        container.rowconfigure(row, weight=2)

        self.log_text = tk.Text(
            log_box,
            height=14,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            log_box,
            orient=tk.VERTICAL,
            command=self.log_text.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        log_actions = ttk.Frame(log_box)
        log_actions.grid(row=1, column=0, columnspan=2, sticky=tk.W,
                         pady=(8, 0))
        ttk.Button(
            log_actions,
            text="Copy log",
            command=self._copy_log,
        ).pack(side=tk.LEFT)
        ttk.Button(
            log_actions,
            text="Save log",
            command=self._save_log,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            log_actions,
            text="Clear log",
            command=self._clear_log,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            log_actions,
            text="Contains amount values — do not share outside SmartAdvisor.",
            foreground="#a03030",
        ).pack(side=tk.LEFT, padx=(12, 0))

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{stamp}] {message}\n")

        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            trim = line_count - MAX_LOG_LINES
            self.log_text.delete("1.0", f"{trim + 1}.0")

        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _copy_log(self) -> None:
        contents = self.log_text.get("1.0", tk.END).strip()
        if not contents:
            self.status.set("The log is empty.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(contents)
        self.status.set("Log copied to the clipboard.")

    def _save_log(self) -> None:
        contents = self.log_text.get("1.0", tk.END).strip()
        if not contents:
            self.status.set("The log is empty.")
            return

        directory = self._diagnostics_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = directory / f"run-log-{stamp}.txt"
            path.write_text(
                "SmartAdvisor Automation run log\n"
                "WARNING: contains charge amount values. Treat as "
                "sensitive and do not share outside SmartAdvisor.\n\n"
                + contents
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            self.status.set(f"Could not save the log: {type(exc).__name__}")
            return
        self.status.set(f"Log saved to {path}")

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _start_workflow(self) -> None:
        if self.running:
            return

        try:
            claim_id = validate_claim_id(self.claim_id.get())
            dos_from = normalize_dos(self.dos_from.get())
            expected_amount = validate_expected_amount(
                self.expected_amount.get()
            )
        except ValueError as exc:
            messagebox.showerror(
                "Invalid input",
                str(exc),
                parent=self.root,
            )
            return

        self._clear_result()
        self.cancel_event.clear()
        self._set_running(True)
        self.status.set("Starting workflow...")
        self._append_log("=" * 52)
        self._append_log("workflow started")

        worker = threading.Thread(
            target=self._workflow_worker,
            args=(claim_id, dos_from, expected_amount),
            daemon=True,
        )
        worker.start()

    def _workflow_worker(
        self,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
    ) -> None:
        driver = SmartAdvisorDriver(
            log=lambda message: self.events.put(("log", message)),
        )
        workflow = NoBillOnFileWorkflow(
            driver,
            cancel_event=self.cancel_event,
            progress=lambda step, message: self.events.put(
                ("progress", (step, message))
            ),
            log=lambda message: self.events.put(("log", message)),
            diagnose_amounts=self.diagnose_amounts.get(),
        )

        try:
            result = workflow.run(claim_id, dos_from, expected_amount)
        except WorkflowCancelled:
            self.events.put(("cancelled", None))
        except AutomationError as exc:
            self.events.put(
                ("automation_error", (exc.code, exc.step, exc.diagnostics))
            )
        except Exception as exc:
            self.events.put(("unexpected_error", type(exc).__name__))
        else:
            self.events.put(("complete", result))

    def _cancel_workflow(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.status.set("Cancellation requested; waiting for the current step.")
        self._append_log("cancellation requested")

    def _start_validation(self) -> None:
        if self.running:
            return
        self._set_running(True, allow_cancel=False)
        self.status.set("Validating known selectors without clicking...")
        self._append_log("selector validation started")
        threading.Thread(
            target=self._validation_worker,
            daemon=True,
        ).start()

    def _validation_worker(self) -> None:
        try:
            report = scan_controls()
        except Exception as exc:
            self.events.put(("unexpected_error", type(exc).__name__))
        else:
            self.events.put(("validation_complete", report))

    def _poll_events(self) -> None:
        while True:
            try:
                event_name, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event_name == "progress":
                step, message = payload
                self.status.set(f"Step {step}: {message}")
                self._append_log(f"step {step}: {message}")
            elif event_name == "log":
                self._append_log(str(payload))
            elif event_name == "complete" and isinstance(
                payload, WorkflowResult
            ):
                self._workflow_complete(payload)
            elif event_name == "cancelled":
                self._set_running(False)
                self.status.set("Workflow cancelled safely.")
                self._append_log("workflow cancelled")
            elif event_name == "automation_error":
                code, step, diagnostics = payload
                self._automation_failed(code, step, diagnostics)
            elif event_name == "unexpected_error":
                self._unexpected_failed(str(payload))
            elif event_name == "validation_complete":
                self._validation_complete(payload)

        self.root.after(100, self._poll_events)

    def _workflow_complete(self, result: WorkflowResult) -> None:
        self.patient_account.set(result.patient_account or "")
        self.amount.set(result.amount)
        self.matched_row.set(
            f"row {result.row_index + 1} of {result.rows_examined} checked"
        )
        self._set_outcome(result.outcome)
        self.copy_button.configure(state=tk.NORMAL)
        self._set_running(False)
        self.status.set("Workflow complete.")
        self._append_log(
            f"workflow complete on row {result.row_index}; "
            f"{result.rows_examined} row(s) opened"
        )

    def _automation_failed(
        self,
        code: str,
        step: str | None,
        diagnostics: dict[str, object] | None,
    ) -> None:
        self._set_running(False)
        location = f" at step {step}" if step else ""
        self.status.set(f"Workflow stopped safely{location}: {code}")
        self._append_log(f"stopped{location}: {code}")

        trace_path = (
            self._save_diagnostics(diagnostics) if diagnostics else None
        )
        trace_line = (
            f"\n\nDiagnostic trace saved to:\n{trace_path}"
            if trace_path is not None
            else ""
        )
        messagebox.showerror(
            "Automation stopped",
            (
                f"The workflow stopped safely{location}.\n\n"
                f"Reason: {code}\n\n"
                "The Log panel shows the step-by-step trace, including "
                "the amounts compared."
                f"{trace_line}"
            ),
            parent=self.root,
        )

    @staticmethod
    def _diagnostics_directory() -> Path:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "SmartAdvisorAutomation" / "diagnostics"

    @classmethod
    def _save_diagnostics(
        cls, diagnostics: dict[str, object]
    ) -> Path | None:
        """Write the redacted attach trace next to the executable's data dir."""

        directory = cls._diagnostics_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "latest-attach-trace.json"
            path.write_text(
                json.dumps(diagnostics, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            return None
        return path

    def _unexpected_failed(self, error_code: str) -> None:
        self._set_running(False)
        self.status.set(f"Workflow stopped safely: {error_code}")
        self._append_log(f"unexpected failure: {error_code}")
        messagebox.showerror(
            "Automation stopped",
            f"The workflow stopped safely ({error_code}).",
            parent=self.root,
        )

    def _validation_complete(self, report: dict[str, object]) -> None:
        found = 0
        checked = 0
        for backend_result in report.get("backend_results", []):
            if not isinstance(backend_result, dict):
                continue
            controls = backend_result.get("controls", [])
            if not isinstance(controls, list):
                continue
            for control in controls:
                if not isinstance(control, dict):
                    continue
                checked += 1
                if control.get("status") == "found":
                    found += 1
                    continue
                selector = (
                    control.get("automation_id")
                    or control.get("selector_name")
                    or "?"
                )
                self._append_log(
                    f"validation {control.get('step')} {selector} "
                    f"-> {control.get('status')}"
                )

        self._set_running(False)
        self.status.set(
            f"Validation complete: {found} unique matches across "
            f"{checked} backend checks."
        )
        self._append_log(
            f"validation complete: {found}/{checked} matched"
        )

    def _set_running(
        self,
        running: bool,
        *,
        allow_cancel: bool = True,
    ) -> None:
        self.running = running
        entry_state = tk.DISABLED if running else tk.NORMAL
        button_state = tk.DISABLED if running else tk.NORMAL
        self.claim_entry.configure(state=entry_state)
        self.dos_entry.configure(state=entry_state)
        self.amount_entry.configure(state=entry_state)
        self.run_button.configure(state=button_state)
        self.validate_button.configure(state=button_state)
        self.diagnose_check.configure(state=button_state)
        self.cancel_button.configure(
            state=tk.NORMAL if running and allow_cancel else tk.DISABLED
        )

    def _set_outcome(self, value: str) -> None:
        self.outcome.configure(state=tk.NORMAL)
        self.outcome.delete("1.0", tk.END)
        self.outcome.insert("1.0", value)
        self.outcome.configure(state=tk.DISABLED)

    def _clear_result(self) -> None:
        self.patient_account.set("")
        self.amount.set("")
        self.matched_row.set("")
        self._set_outcome("")
        self.copy_button.configure(state=tk.DISABLED)

    def _copy_result(self) -> None:
        result = (
            f"Patient Account: {self.patient_account.get()}\n"
            f"Amount: {self.amount.get()}\n"
            f"Matched row: {self.matched_row.get()}\n"
            f"Outcome: {self.outcome.get('1.0', tk.END).strip()}"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        self.status.set("Result copied to the clipboard.")


def main() -> None:
    root = tk.Tk()
    AutomationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()


# ============================================================================
# SECTION 9 - ENTRY POINT
# ============================================================================
#
# `main()` above builds the Tk root and starts the event loop. This guard lets
# the file be run directly:
#
#     python smartadvisor_automation_all_in_one.py
#
# ----------------------------------------------------------------------------
# OPEN ITEM, so you are not surprised by it
# ----------------------------------------------------------------------------
# The Result box shows "Patient Account" but it is always BLANK.
#
# The original single-result version of this workflow read it from a control
# whose AutomationId was the numeric "198916". That id was retired along with
# the rest of the old single-result path, and the current row-walking flow has
# no equivalent, so `WorkflowResult.patient_account` is None.
#
# The value most likely lives on the bill window's Header tab (the tab
# frmBillEntry opens on). Filling it in needs one Inspect capture of that
# field's AutomationId, then a step modelled on step 7.5.
#
# Nothing depends on it: matching is on charge amount only.
# ============================================================================

if __name__ == "__main__":
    main()
