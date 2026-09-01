from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

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
Disposition = Literal["no_match", "denied", "paid", "pending", "no_claim_on_file"]


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
    disposition: Disposition = "no_match"
    reply_template: str = ""
    paid_amount: str | None = None
    paid_date: str | None = None
    check_number: str | None = None
    denial_code: str | None = None
    received_date: str | None = None
    eor_pdf_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
