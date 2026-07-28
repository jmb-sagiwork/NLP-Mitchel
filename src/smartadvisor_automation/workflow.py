from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from smartadvisor_automation.errors import WorkflowCancelled
from smartadvisor_automation.models import ControlSpec, WorkflowResult
from smartadvisor_automation.selectors import CONTROLS_BY_STEP

OUTCOME_MESSAGE = (
    "There is not a bill on file that matches this date of service and "
    "billed amount. Please resubmit the bill with medical reports to:"
)

ProgressCallback = Callable[[str, str], None]


class WorkflowDriver(Protocol):
    def attach(self, landmark: ControlSpec) -> str: ...

    def invoke(self, spec: ControlSpec) -> None: ...

    def click(self, spec: ControlSpec) -> None: ...

    def clear(self, spec: ControlSpec) -> None: ...

    def input_text(self, spec: ControlSpec, value: str) -> None: ...

    def read_text(self, spec: ControlSpec) -> str: ...


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


def extract_patient_account(raw_text: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_text).strip()
    match = re.search(
        r"Patient\s+Account\s*[-:]\s*(.+)$",
        normalized,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else normalized


def extract_amount(raw_text: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_text).strip()
    match = re.search(r"\$[\d,]+(?:\.\d{2})?", normalized)
    return match.group(0) if match else normalized


class NoBillOnFileWorkflow:
    """Execute the supplied attended SmartAdvisor workflow."""

    def __init__(
        self,
        driver: WorkflowDriver,
        *,
        cancel_event: threading.Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.driver = driver
        self.cancel_event = cancel_event or threading.Event()
        self.progress = progress or (lambda _step, _message: None)

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

    def run(self, claim_id: str, dos_from: str) -> WorkflowResult:
        claim_id = validate_claim_id(claim_id)
        dos_from = normalize_dos(dos_from)

        self._check_cancelled()
        self.progress("attach", "Attaching to SmartAdvisor")
        backend = self.driver.attach(CONTROLS_BY_STEP["1"])
        self.progress("attach", f"Attached using {backend.upper()}")

        self._run_step(
            "1",
            "Opening search options",
            lambda: self.driver.invoke(CONTROLS_BY_STEP["1"]),
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
            lambda: self.driver.input_text(
                CONTROLS_BY_STEP["4"], claim_id
            ),
        )
        self._run_step(
            "5",
            "Entering DOS From",
            lambda: self.driver.input_text(
                CONTROLS_BY_STEP["5"], dos_from
            ),
        )
        self._run_step(
            "6",
            "Submitting search criteria",
            lambda: self.driver.click(CONTROLS_BY_STEP["6"]),
        )
        self._run_step(
            "7.1",
            "Opening claim details",
            lambda: self.driver.click(CONTROLS_BY_STEP["7.1"]),
        )

        self._check_cancelled()
        self.progress("7.2", "Reading Patient Account")
        patient_account = extract_patient_account(
            self.driver.read_text(CONTROLS_BY_STEP["7.2"])
        )

        self._check_cancelled()
        self.progress("7.3", "Reading and confirming Amount")
        amount = extract_amount(
            self.driver.read_text(CONTROLS_BY_STEP["7.3"])
        )
        self.driver.click(CONTROLS_BY_STEP["7.3"])

        self._run_step(
            "8",
            "Closing the result window",
            lambda: self.driver.click(CONTROLS_BY_STEP["8"]),
        )

        self.progress("complete", "Workflow complete")
        return WorkflowResult(
            patient_account=patient_account,
            amount=amount,
            outcome=OUTCOME_MESSAGE,
        )
