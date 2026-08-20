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
    BILL_ENTRY_WINDOW_AUTOMATION_ID,
    BILL_HISTORY_TAB_ACCELERATOR,
    BILL_HISTORY_TAB_NAME_FRAGMENT,
    BILL_LINES_AMOUNT_PREFIX,
    BILL_LINES_TAB_NAME_FRAGMENT,
    BILL_TAB_ACCELERATOR,
    BILL_TAB_FALLBACK_KEY,
    BILL_TAB_MAX_PRESSES,
    BILL_TAB_NEXT_KEY,
    BILL_TAB_SETTLE_TIMEOUT,
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
    if re.fullmatch(r"\d{8}", normalized):
        normalized = f"{normalized[:-1]}-{normalized[-1]}"
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


_MONEY_RE = re.compile(r"-?\$?\s*[\d,]+(?:\.\d{1,2})?")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")


def _values_near_labels(
    controls: list[tuple[str, str]],
    labels: tuple[str, ...],
) -> list[str]:
    """Return a labelled control's text and its next few text controls.

    The working all-in-one driver exposes controls in UIA traversal order.
    SmartAdvisor versions vary between putting a label and value in one
    control or in adjacent controls, so this supports both layouts without
    inventing positional AutomationIds.
    """

    lowered = tuple(label.casefold().replace(" ", "") for label in labels)
    values: list[str] = []
    for index, (automation_id, text) in enumerate(controls):
        haystack = f"{automation_id} {text}".casefold().replace(" ", "")
        if not any(label in haystack for label in lowered):
            continue
        for _, candidate in controls[index : index + 4]:
            normalized = re.sub(r"\s+", " ", candidate).strip()
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def extract_history_details(
    controls: list[tuple[str, str]],
) -> tuple[str | None, str | None, str | None]:
    """Extract paid amount, paid date, and check number from History controls."""

    paid_amount = None
    for candidate in _values_near_labels(
        controls, ("paid amount", "amount paid", "paidamount")
    ):
        match = _MONEY_RE.search(candidate)
        if match:
            paid_amount = match.group(0).replace(" ", "")
            break

    paid_date = None
    for candidate in _values_near_labels(
        controls, ("paid date", "payment date", "paiddate")
    ):
        match = _DATE_RE.search(candidate)
        if match:
            paid_date = match.group(0)
            break

    check_number = None
    labels = ("check number", "check no", "check #", "checknumber")
    for candidate in _values_near_labels(controls, labels):
        cleaned = candidate
        lowered = cleaned.casefold()
        for label in labels:
            position = lowered.find(label)
            if position >= 0:
                cleaned = cleaned[position + len(label) :].lstrip(" :-#")
                break
        match = re.search(r"\b[A-Z0-9][A-Z0-9._/-]{1,63}\b", cleaned, re.IGNORECASE)
        if match and not _DATE_RE.fullmatch(match.group(0)):
            check_number = match.group(0)
            break

    return paid_amount, paid_date, check_number


def extract_denial_code(controls: list[tuple[str, str]]) -> str | None:
    """Extract a labelled denial/reason code from the selected Lines tab."""

    labels = ("denial code", "denial reason", "reason code", "denialcode")
    for candidate in _values_near_labels(controls, labels):
        cleaned = candidate
        lowered = cleaned.casefold()
        for label in labels:
            position = lowered.find(label)
            if position >= 0:
                cleaned = cleaned[position + len(label) :].lstrip(" :-#")
                break
        match = re.search(r"\b[A-Z0-9][A-Z0-9._/-]{0,31}\b", cleaned, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def build_reply_template(
    disposition: str,
    *,
    claim_id: str,
    dos_from: str,
    expected_amount: str,
    paid_amount: str | None = None,
    paid_date: str | None = None,
    check_number: str | None = None,
    denial_code: str | None = None,
) -> str:
    """Build the simulated email displayed after one email is processed."""

    header = "To: Requestor\nSubject: Bill Status Response\n\n"
    if disposition == "no_match":
        return (
            header
            + "Concern: No Bill on File\n\n"
            + f"We could not locate a bill matching claim {claim_id}, "
            + f"DOS {dos_from}, and billed amount {expected_amount}.\n"
            + "Please resubmit the bill with the supporting medical reports."
        )
    if disposition == "denied":
        return (
            header
            + "Concern: Completed Processing - Denied\n\n"
            + f"The bill for claim {claim_id} and DOS {dos_from} was processed "
            + "and denied.\n"
            + f"Denial code: {denial_code or 'Unavailable'}"
        )
    return (
        header
        + "Concern: Completed Processing - Paid\n\n"
        + f"The bill for claim {claim_id} and DOS {dos_from} was processed "
        + "and paid.\n"
        + f"Paid amount: {paid_amount or 'Unavailable'}\n"
        + f"Paid date: {paid_date or 'Unavailable'}\n"
        + f"Check number: {check_number or 'Unavailable'}"
    )


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

    def _select_and_scan_tab(
        self,
        step: str,
        fragment: str,
        accelerator: str,
    ) -> list[tuple[str, str]]:
        self._run_step(
            step,
            f"Switching to the {fragment} tab",
            lambda: self.driver.select_tab(
                CONTROLS_BY_STEP["7.4"],
                expected_fragment=fragment,
                accelerator=accelerator,
                next_key=BILL_TAB_NEXT_KEY,
                fallback_key=BILL_TAB_FALLBACK_KEY,
                max_presses=BILL_TAB_MAX_PRESSES,
                settle_timeout=BILL_TAB_SETTLE_TIMEOUT,
            ),
        )
        self._check_cancelled()
        self.progress(step, f"Reading {fragment} fields (slow)")
        return self.driver.scan_texts(BILL_ENTRY_WINDOW_AUTOMATION_ID, "")

    def _resolve_matched_bill(
        self,
        *,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        amount: str,
        row_index: int,
    ) -> WorkflowResult:
        history = self._select_and_scan_tab(
            "7.7",
            BILL_HISTORY_TAB_NAME_FRAGMENT,
            BILL_HISTORY_TAB_ACCELERATOR,
        )
        self._check_cancelled()
        self.progress("7.8", "Evaluating the paid amount")
        paid_amount, paid_date, check_number = extract_history_details(history)
        if paid_amount is None:
            raise AutomationError("paid_amount_not_readable", step="7.7")

        if normalize_amount(paid_amount) == Decimal("0"):
            lines = self._select_and_scan_tab(
                "7.9",
                BILL_LINES_TAB_NAME_FRAGMENT,
                BILL_TAB_ACCELERATOR,
            )
            denial_code = extract_denial_code(lines)
            if denial_code is None:
                raise AutomationError("denial_code_not_readable", step="7.9")
            disposition = "denied"
            outcome = "Completed Processing - Denied"
            reply = build_reply_template(
                disposition,
                claim_id=claim_id,
                dos_from=dos_from,
                expected_amount=expected_amount,
                paid_amount=paid_amount,
                denial_code=denial_code,
            )
            return WorkflowResult(
                patient_account=None,
                amount=amount,
                outcome=outcome,
                row_index=row_index,
                rows_examined=row_index + 1,
                disposition="denied",
                reply_template=reply,
                paid_amount=paid_amount,
                denial_code=denial_code,
            )

        if paid_date is None:
            raise AutomationError("paid_date_not_readable", step="7.7")
        if check_number is None:
            raise AutomationError("check_number_not_readable", step="7.7")
        disposition = "paid"
        outcome = "Completed Processing - Paid"
        reply = build_reply_template(
            disposition,
            claim_id=claim_id,
            dos_from=dos_from,
            expected_amount=expected_amount,
            paid_amount=paid_amount,
            paid_date=paid_date,
            check_number=check_number,
        )
        return WorkflowResult(
            patient_account=None,
            amount=amount,
            outcome=outcome,
            row_index=row_index,
            rows_examined=row_index + 1,
            disposition="paid",
            reply_template=reply,
            paid_amount=paid_amount,
            paid_date=paid_date,
            check_number=check_number,
        )

    def run(
        self,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        *,
        leave_match_open: bool = True,
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
                result = self._resolve_matched_bill(
                    claim_id=claim_id,
                    dos_from=dos_from,
                    expected_amount=expected_amount,
                    amount=amount,
                    row_index=row_index,
                )
                self.progress("complete", result.outcome)
                self.log(f"match on row {row_index}; disposition={result.disposition}")
                if not leave_match_open:
                    self._run_step(
                        "7.6",
                        "Closing the matched bill before the next job",
                        lambda: self.driver.click(CONTROLS_BY_STEP["7.6"]),
                    )
                return result

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
                reply = build_reply_template(
                    "no_match",
                    claim_id=claim_id,
                    dos_from=dos_from,
                    expected_amount=expected_amount,
                )
                self.progress("complete", "No matching bill amount")
                return WorkflowResult(
                    patient_account=None,
                    amount=amount,
                    outcome=OUTCOME_MESSAGE,
                    row_index=row_index,
                    rows_examined=row_index + 1,
                    disposition="no_match",
                    reply_template=reply,
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
