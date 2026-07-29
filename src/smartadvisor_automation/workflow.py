from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from smartadvisor_automation.errors import AutomationError, WorkflowCancelled
from smartadvisor_automation.models import ControlSpec, WorkflowResult
from smartadvisor_automation.selectors import (
    BILL_LINES_TAB_NAME_FRAGMENT,
    BILL_TAB_MAX_PRESSES,
    BILL_TAB_NEXT_KEY,
    CONTROLS_BY_STEP,
    GRID_CALIBRATE_DOWN,
    GRID_CALIBRATE_UP,
    GRID_CONFIRM_ROW,
    GRID_SEEK_DOWN,
)

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
        keys: str,
        expected_fragment: str,
        max_presses: int,
    ) -> None: ...

    def is_present(self, spec: ControlSpec) -> bool: ...

    def invalidate_scopes(self) -> None: ...


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


def mask_amount_shape(value: str) -> str:
    """Render an amount as its shape (#,###.##) for value-free logging."""

    return re.sub(r"\d", "#", value)


class NoBillOnFileWorkflow:
    """Execute the supplied attended SmartAdvisor workflow."""

    def __init__(
        self,
        driver: WorkflowDriver,
        *,
        cancel_event: threading.Event | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> None:
        self.driver = driver
        self.cancel_event = cancel_event or threading.Event()
        self.progress = progress or (lambda _step, _message: None)
        self.log = log or (lambda _message: None)

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
                keys=BILL_TAB_NEXT_KEY,
                expected_fragment=BILL_LINES_TAB_NAME_FRAGMENT,
                max_presses=BILL_TAB_MAX_PRESSES,
            ),
        )

        self._check_cancelled()
        self.progress("7.5", "Reading the charge amount")
        amount = extract_amount(self.driver.read_text(CONTROLS_BY_STEP["7.5"]))
        if not amount:
            self.log("amount not parseable from the totals label")
            raise AutomationError("amount_not_readable", step="7.5")
        self.log(f"amount read shape={mask_amount_shape(amount)}")
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

        self.log(
            "run start expected_shape="
            f"{mask_amount_shape(expected_amount)}"
        )

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

            if normalize_amount(amount) == expected:
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
