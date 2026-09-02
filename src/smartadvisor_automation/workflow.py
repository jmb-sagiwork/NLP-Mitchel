from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import zip_longest
from pathlib import Path
from typing import Protocol

from smartadvisor_automation.errors import AutomationError, WorkflowCancelled
from smartadvisor_automation.models import ControlSpec, WorkflowResult
from smartadvisor_automation.selectors import (
    BILL_ENTRY_WINDOW_AUTOMATION_ID,
    BILL_HEADER_TAB_NAME_FRAGMENT,
    BILL_HISTORY_TAB_NAME_FRAGMENT,
    BILL_LINES_TAB_NAME_FRAGMENT,
    BILL_TAB_ACCELERATOR,
    BILL_TAB_FALLBACK_KEY,
    BILL_TAB_MAX_PRESSES,
    BILL_TAB_NEXT_KEY,
    BILL_TAB_SETTLE_TIMEOUT,
    CONTROLS_BY_STEP,
    EOR_OUTPUT_DIRECTORY_NAME,
    EXPORT_REPORT_OK_BUTTON_NAME,
    EXPORT_REPORT_OK_KEYS,
    EXPORT_REPORT_WINDOW_NAME,
    GRID_CALIBRATE_DOWN,
    GRID_CALIBRATE_UP,
    GRID_CONFIRM_ROW,
    GRID_COPY_ROW,
    GRID_FIRST_ROW_CLICK_Y,
    GRID_FIRST_ROW_LOWER_CLICK_Y,
    GRID_SEEK_DOWN,
    LINES_BRADJ_MSG_ROW_COPY_INDEX,
    LINES_BR_MSG_ROW_COPY_INDEX,
    LINES_DENIED_CODE_MAX_ROWS,
    LINES_FIRST_ROW_CLICK_Y,
    LINES_ROW_HEIGHT,
    LINES_ROW_SELECTOR_CLICK_X,
    PRINT_EOR_ADD_FALLBACK_KEYS,
    PRINT_EOR_BILL_LIST_COMMIT_KEYS,
    PRINT_EOR_KEYS,
    PRINT_EOR_OK_FALLBACK_KEYS,
    PRINT_SETUP_FILE_FALLBACK_KEYS,
    SAVE_AS_FILENAME_KEYS,
    SAVE_AS_REVIEW_DELAY_SECONDS,
    SAVE_AS_SAVE_KEYS,
    SCOPE_SEARCH_DEPTH,
)

OUTCOME_MESSAGE = (
    "There is not a bill on file that matches this date of service and "
    "billed amount. Please resubmit the bill with medical reports to:"
)
NO_CLAIM_ON_FILE_EMAIL_INTRO = (
    "Hello, Thank you for your inquiry, unfortunitely additional information "
    "is need insurance carrier."
)
NO_CLAIM_ON_FILE_REQUEST_FIELDS = (
    ("Claim #:", "claim_id"),
    ("Date of service:", "dos_from"),
    ("Total Billed Amount :", "expected_amount"),
    ("Provider Tax ID :", "prov_tin"),
)
MAX_ITERATIONS = 500
HISTORY_TAB_READY_TIMEOUT = 25.0
MINIMUM_SUCCESSFUL_SEARCH_FIELDS = 2
# DOS matches too many unrelated claims to identify one on its own; it only
# counts toward MINIMUM_SUCCESSFUL_SEARCH_FIELDS when paired with a field
# that is actually unique, like Claim ID, Prov TIN, or Patient Account.
NON_UNIQUE_SEARCH_LABELS = frozenset({"DOS From"})

SEARCH_RESULT_ROW_HEADERS = (
    "H", "B", "W", "S", "Client", "Bill No", "Provider", "Claimant",
    "Reviewed", "Create User", "Mod User", "DCN", "Claim Sys", "Claim ID",
    "Patient Account #", "Prov ZIP", "Prov TIN", "Facility NPI",
    "Rendering NPI", "External ID", "TOB", "DOS From", "DOS To", "SSN",
    "Carrier Sequence #", "Patient DOB", "Total Charges", "Total Allowance",
)
SEARCH_RESULT_DETAIL_KEYS = {
    "Patient DOB": "Patient DOB",
    "Total Charges": "Total Charges",
    "Total Allowance": "Total Allowance",
    "Provider": "Provider",
    "Client": "Client",
    "Bill no": "Bill No",
    "Claimant": "Claimant",
    "Prov zip": "Prov ZIP",
    "Prov TIN": "Prov TIN",
    "Patient Account": "Patient Account #",
    "Bill Search Reviewed": "Reviewed",
    "Bill Search DCN": "DCN",
    "Bill Search Claim Sys": "Claim Sys",
    "Bill Search TOB": "TOB",
    "Bill Search DOS From": "DOS From",
    "Bill Search DOS To": "DOS To",
    "Bill Search Facility NPI": "Facility NPI",
    "Bill Search Rendering NPI": "Rendering NPI",
    "Bill Search External ID": "External ID",
}

DENIAL_CODE_REASONS = {
    "C56": "PAID WITHOUT PREJUDICE",
    "932": "NOT AUTHORIZED PER UR - [ CA ]",
    "G21": "OUTPATIENT REIMBURSEMENT",
    "D02": "The claim/service has been transferred to the proper payer/processor for "
    "processing; claim/service not covered by this payer/processor.",
    "XAW": "The disposition of this claim/service is pending further review.",
    "XDC": "Worker compensation claim adjudicated as non-compensable; this payer is not "
    "liable for the claim or service/treatment.",
    "224": "A charge was made for a duplicate procedure and/or supply.",
    "D03": "Claim has been controverted by a FROI or SROI-04.",
    "XCS": "Precertification/Authorization/Notification absent.",
    "D08": "Prior authorization was not granted for the medical treatment guideline "
    "procedure/treatment requiring pre-authorization.",
    "608": "The APR-DRG and the severity of illness factor are both required in order "
    "to determine the APR-DRG allowance.",
    "XCY": "Workers compensation case settled. Patient responsible for amount of this "
    "claim per WC Medicare set-aside arrangement or other agreement.",
    "XDL": "Workers compensation claim is under investigation.",
    "220": "The provider billed for a visit on the same day of surgery or within the "
    "follow-up of a previously performed surgery.",
    "936": "This code is either deleted, non-covered, bundled, invalid, or the status "
    "indicator is not allowable under the provider's jurisdiction.",
    "225": "The submitted documentation does not support the service being billed for; "
    "we will re-evaluate this upon receipt of clarifying information.",
    "D22": "Diagnostic test was performed outside of network. Supporting documents are "
    "required to proceed with the review.",
    "972": "This is not related to the injury and is denied.",
    "PPD": "The network has identified this bill as a duplicate; please contact the "
    "network.",
    "QC9": "Based on documentation submitted it is recommended that service should. "
    "However, supporting documents are required to proceed with the review.",
    "217": "The value of this procedure is included in the value of another procedure "
    "performed on this date.",
    "Q88": "Radiology services require a copy of images not provided. Submit copy of "
    "image or statement that equipment cannot store or export images.",
    "D10": "Treatment provided was for a non-established body site or for a body site "
    "that the employer/insurer has not accepted liability for.",
    "D24": "Treatment provided was not based on correct application of the guidelines.",
    "D26": "Treatment deviates from the guidelines without securing a variance.",
    "CND": "Workers compensation claim adjudicated as non-compensable. This payer not "
    "liable for claim or service/treatment.",
    "P86": "Allowance has been priced in accordance with your Multiplan contract; "
    "questions call 800-937-6824.",
    "P24": "Payment adjusted based on preferred provider organization (PPO).",
    "XBW": "This diagnosis is not covered.",
    "201": "A charge was made for two visits on the same day.",
    "D15": "Medical report not timely filed.",
    "X26": "Expenses incurred prior to coverage.",
    "F15": "No allowance has been recommended as this code has not been adopted for use "
    "in the fee schedule.",
    "D05": "Claim has been controverted. The case has been denied.",
    "X38": "Services not provided or authorized by designated (network/primary care) "
    "providers.",
    "790": "This bill was reviewed using the official medical fee schedule of Alabama.",
    "722": "The service/chargemaster code is either invalid or not provided; please "
    "resubmit the correct or missing information.",
    "253": "In order to review this charge, please submit a copy of the invoice.",
    "PDN": "Payment recommendation is per payor request or state reimbursement rules.",
    "P04": "Reviewed to standard of reasonableness based on comparisons to industry "
    "benchmarks of charges and reimbursement for services in the area.",
    "PHO": "Surgical implant charges reviewed separately by Foresight Medical; please "
    "direct inquiries for surgical implant charges to 855-481-1205.",
    "D35": "The time limit for filing has expired.",
    "435": "The value of this procedure is included in the value of the comprehensive "
    "procedure.",
    "H57": "The total component has been reimbursed; therefore the professional and "
    "technical components are denied.",
    "P57": "Allowance has been priced in accordance with your Coventry-owned contract; "
    "questions call 800-937-6824.",
    "X51": "These are non-covered services because this is a pre-existing condition.",
    "X50": "These are non-covered services because this is not deemed a medical "
    "necessity by the payer.",
    "H06": "The allowance for this code is included in the pricing of other services "
    "on the bill.",
    "D52": "Provider not authorized to function as a pharmacy or render pharmacy "
    "services; please refer to a licensed pharmacy.",
}
BR_MSG_CODE_REASONS = {
    "U02": "The billed service was reviewed by UR and denied.",
    "U05": "The billed service exceeds the UR amount authorized.",
}

ProgressCallback = Callable[[str, str], None]
LogCallback = Callable[[str], None]


class WorkflowDriver(Protocol):
    def attach(self, landmark: ControlSpec) -> str: ...

    def click_with_invoke_fallback(
        self, spec: ControlSpec, confirmation_spec: ControlSpec
    ) -> None: ...

    def click(self, spec: ControlSpec) -> None: ...

    def clear(self, spec: ControlSpec) -> None: ...

    def input_text(self, spec: ControlSpec, value: str) -> None: ...

    def input_child_edit_text(self, spec: ControlSpec, value: str) -> None: ...

    def read_text(
        self, spec: ControlSpec, *, timeout: float | None = None
    ) -> str: ...

    def focus_grid(self, spec: ControlSpec) -> None: ...

    def click_grid_row(
        self,
        spec: ControlSpec,
        row_index: int,
        *,
        first_row_y: int = GRID_FIRST_ROW_CLICK_Y,
    ) -> None: ...

    def click_at(self, spec: ControlSpec, *, x: int, y: int) -> None: ...

    def send_focused_keys(self, keys: str, *, step: str) -> None: ...

    def paste_focused_text(self, value: str, *, step: str) -> None: ...

    def wait_for_window_title(self, title: str, *, timeout: float) -> bool: ...

    def focus_window_title(self, title: str, *, timeout: float) -> None: ...

    def click_child_in_window_title(
        self,
        title: str,
        spec: ControlSpec,
        *,
        timeout: float,
    ) -> None: ...

    def acknowledge_duplicate_selection_popup(
        self, *, timeout: float = 1.0
    ) -> bool: ...

    def acknowledge_save_as_overwrite_popup(
        self, *, timeout: float = 1.0
    ) -> bool: ...

    def acknowledge_smartadvisor_exception_popup(
        self, *, timeout: float = 1.0
    ) -> bool: ...

    def acknowledge_no_records_popup(self, *, timeout: float = 3.0) -> bool: ...

    def close_all_subwindows_for_finish(self) -> int: ...

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

    def is_present(
        self, spec: ControlSpec, *, timeout: float = 1.5
    ) -> bool: ...

    def invalidate_scopes(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LinesRowCopy:
    has_data: bool
    denied_code: str
    br_msg_code: str
    signature: str


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


def validate_optional_claim_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return validate_claim_id(normalized)


def parse_direct_bill_reference(value: str) -> tuple[str, str] | None:
    """Parse compact direct bill input like AMNY714 or AMNY-714."""

    normalized = str(value or "").strip()
    match = re.fullmatch(r"([A-Za-z]{4})[\s_-]*(\d{1,12})", normalized)
    if match is None:
        return None
    return match.group(1).upper(), match.group(2)


def normalize_dos(value: str) -> str:
    normalized = value.strip()
    try:
        parsed = datetime.strptime(normalized, "%m/%d/%Y")
    except ValueError as exc:
        raise ValueError("DOS From must use MM/DD/YYYY.") from exc
    return parsed.strftime("%m/%d/%Y")


def normalize_optional_dos(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return normalize_dos(normalized)


def validate_search_inputs(
    claim_id: str,
    dos_from: str,
    prov_tin: str,
    patient_account: str,
) -> None:
    if any((claim_id, dos_from, prov_tin, patient_account)):
        return
    raise ValueError(
        "Enter at least one search value: Claim ID, DOS, Patient Account, "
        "or Prov TIN."
    )


def validate_expected_amount(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"\$?\s*[\d,]*\d(?:\.\d{1,4})?", normalized):
        raise ValueError(
            "Expected Amount must be a number such as 1,952.43 or $1952.43."
        )
    return normalized


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_amount(value: str) -> Decimal:
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not a readable amount: {value!r}") from exc


def amount_is_nonzero(value: str) -> bool:
    try:
        return normalize_amount(value) != Decimal("0")
    except ValueError:
        return False


def bill_document_name(row_details: dict[str, str]) -> str:
    client = (row_details.get("Client") or "").strip()
    bill_no = (
        row_details.get("Bill No")
        or row_details.get("Bill no")
        or ""
    ).strip()
    if client and bill_no:
        return f"{client}-{bill_no}"
    return bill_no or client or "bill"


def describe_comparison(amount: str, expected: str, matched: bool) -> str:
    verdict = "MATCH" if matched else "no match"
    return f"amount={amount} vs expected={expected} -> {verdict}"


def read_clipboard_text() -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(
            win32clipboard.CF_UNICODETEXT
        ):
            return ""
        return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
    finally:
        win32clipboard.CloseClipboard()


def write_clipboard_text(value: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, value)
    finally:
        win32clipboard.CloseClipboard()


def parse_search_result_clipboard(raw_text: str) -> dict[str, str]:
    row = next(
        (line for line in raw_text.replace("\r\n", "\n").split("\n") if line.strip()),
        "",
    )
    if not row:
        return {}
    values = [normalize_text(value) for value in row.rstrip("\t").split("\t")]
    copied = {
        header: value
        for header, value in zip_longest(
            SEARCH_RESULT_ROW_HEADERS, values, fillvalue=""
        )
        if header and value
    }
    parsed = dict(copied)
    parsed.update(
        {
            detail_key: copied[source_key]
            for detail_key, source_key in SEARCH_RESULT_DETAIL_KEYS.items()
            if copied.get(source_key)
        }
    )
    return parsed


def search_result_signature(details: dict[str, str]) -> str:
    for key in (
        "Bill Search DCN", "Bill no", "Patient Account", "Provider",
        "Total Allowance", "Total Charges",
    ):
        value = details.get(key)
        if value:
            return f"{key}:{value}"
    return "|".join(f"{key}={value}" for key, value in sorted(details.items()))


DENIED_CODE_PATTERN = re.compile(r"^(?:[A-Za-z]{1,4}-?\d{0,4}|\d{2,4})$")
DENIED_CODE_IN_TEXT_PATTERN = re.compile(
    r"(?:Msg\s+Code\s+Entry\s*:?\s*|^|\s-\s)"
    r"([A-Za-z]{1,4}-?\d{0,4}|\d{2,4})(?=\s|$)",
    re.IGNORECASE,
)


def normalize_denied_code(raw_value: str) -> str:
    value = normalize_text(raw_value).strip(":- ")
    if not value:
        return ""
    if DENIED_CODE_PATTERN.fullmatch(value):
        return value.upper()
    match = DENIED_CODE_IN_TEXT_PATTERN.search(value)
    return match.group(1).upper() if match else ""


def _first_clipboard_row(raw_text: str) -> str:
    return next(
        (line for line in raw_text.replace("\r\n", "\n").split("\n") if line.strip()),
        "",
    )


def extract_lines_bradj_code_from_clipboard(raw_text: str) -> str:
    row = _first_clipboard_row(raw_text)
    if not row:
        return ""
    values = [normalize_text(value) for value in row.rstrip("\t").split("\t")]
    if LINES_BRADJ_MSG_ROW_COPY_INDEX < len(values):
        code = normalize_denied_code(values[LINES_BRADJ_MSG_ROW_COPY_INDEX])
        if code:
            return code
    for value in values:
        code = normalize_denied_code(value)
        if code in DENIAL_CODE_REASONS:
            return code
    return ""


def extract_lines_br_msg_code_from_clipboard(raw_text: str) -> str:
    row = _first_clipboard_row(raw_text)
    if not row:
        return ""
    values = [normalize_text(value) for value in row.rstrip("\t").split("\t")]
    if LINES_BR_MSG_ROW_COPY_INDEX < len(values):
        code = normalize_denied_code(values[LINES_BR_MSG_ROW_COPY_INDEX])
        if code in BR_MSG_CODE_REASONS:
            return code
    for value in values:
        code = normalize_denied_code(value)
        if code in BR_MSG_CODE_REASONS:
            return code
    return ""


def copied_lines_row_signature(raw_text: str) -> str:
    return normalize_text(_first_clipboard_row(raw_text))


def copied_lines_row_has_data(raw_text: str) -> bool:
    row = _first_clipboard_row(raw_text)
    if not row.strip():
        return False
    if "\t" in row:
        return any(normalize_text(value) for value in row.rstrip("\t").split("\t"))
    return bool(re.search(r"[A-Za-z0-9]", row))


def extract_lines_count(tab_name: str) -> int | None:
    match = re.search(r"Lines\s*\(\s*(\d+)\s*\)", tab_name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _values_near_labels(
    controls: list[tuple[str, str]], labels: tuple[str, ...]
) -> list[str]:
    lowered = tuple(label.casefold().replace(" ", "") for label in labels)
    values: list[str] = []
    for index, (automation_id, value) in enumerate(controls):
        haystack = f"{automation_id} {value}".casefold().replace(" ", "")
        if not any(label in haystack for label in lowered):
            continue
        for _, candidate in controls[index : index + 4]:
            normalized = normalize_text(candidate)
            if normalized and normalized not in values:
                values.append(normalized)
    return values


_MONEY_RE = re.compile(r"-?\$?\s*[\d,]+(?:\.\d{1,2})?")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")


def extract_history_details(
    controls: list[tuple[str, str]],
) -> tuple[str | None, str | None, str | None]:
    """Compatibility parser for diagnostic snapshots."""

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
    labels = ("denial code", "denial reason", "reason code", "denialcode")
    for candidate in _values_near_labels(controls, labels):
        lowered = candidate.casefold()
        cleaned = candidate
        for label in labels:
            position = lowered.find(label)
            if position >= 0:
                cleaned = candidate[position + len(label) :].lstrip(" :-#")
                break
        code = normalize_denied_code(cleaned)
        if code:
            return code
    return None


def _denial_reason_text(denial_code: str | None) -> str:
    if not denial_code:
        return ""
    codes = [code.strip() for code in denial_code.split(",") if code.strip()]
    reasons: list[str] = []
    for code in codes:
        reason = DENIAL_CODE_REASONS.get(code) or BR_MSG_CODE_REASONS.get(code) or code
        if reason not in reasons:
            reasons.append(reason)
    return ", ".join(reasons)


def build_reply_template(
    disposition: str,
    *,
    claim_id: str,
    dos_from: str,
    expected_amount: str,
    prov_tin: str = "",
    patient_account: str = "",
    paid_amount: str | None = None,
    paid_date: str | None = None,
    check_number: str | None = None,
    denial_code: str | None = None,
    received_date: str | None = None,
    bill_name: str = "",
) -> str:
    if disposition == "no_claim_on_file":
        provided_values = {
            "claim_id": claim_id,
            "dos_from": dos_from,
            "expected_amount": expected_amount,
            "prov_tin": prov_tin,
        }
        missing_fields = [
            label
            for label, key in NO_CLAIM_ON_FILE_REQUEST_FIELDS
            if not str(provided_values.get(key, "")).strip()
        ]
        return (
            "\n".join([NO_CLAIM_ON_FILE_EMAIL_INTRO, "", *missing_fields])
            if missing_fields
            else NO_CLAIM_ON_FILE_EMAIL_INTRO
        )
    if disposition == "no_match":
        return (
            f"We could not locate a bill matching claim {claim_id}, "
            + f"DOS {dos_from}, and billed amount {expected_amount}.\n"
            + "Please resubmit the bill with the supporting medical reports."
        )
    name = bill_name or claim_id
    if disposition == "denied":
        reason = _denial_reason_text(denial_code)
        denial_line = (
            f"Denial Reason : Bill has been denied with {reason}."
            if reason
            else "Denial Reason : Bill has been denied."
        )
        return (
            "Hello,\n"
            f"This bill {name} has been completed processing and denied "
            "please see the attached EOR's for processing details .\n"
            f"{denial_line}"
        )
    if disposition == "pending":
        return (
            f"This bill {name} was received on "
            f"{received_date or 'Unavailable'} and is currently pending "
            "with the carrier . Please reach the carrier at 833-520-8786 "
            "for additional information"
        )
    lines = [
        "Hello,",
        (
            f"This bill {name} has been completed processing and "
            "paid. Please see the attached EOR's for processing details ."
        ),
    ]
    if paid_amount:
        amount_text = (
            paid_amount if paid_amount.startswith("$") else f"${paid_amount}"
        )
        lines.append(f"Paid Amount : {amount_text}")
    if check_number:
        lines.append(f"Check/Transaction # : {check_number}")
    if paid_date:
        lines.append(f"Paid Date : {paid_date}")
    return "\n".join(lines)


class NoBillOnFileWorkflow:
    """Run the current all-in-one SmartAdvisor flow for one NLP job."""

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

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise WorkflowCancelled()

    def _run_step(
        self, step: str, message: str, action: Callable[[], None]
    ) -> None:
        self._check_cancelled()
        self.progress(step, message)
        action()

    def _search(self, claim_id: str, dos_from: str) -> None:
        self._check_cancelled()
        self.progress("attach", "Attaching to SmartAdvisor")
        backend = self.driver.attach(CONTROLS_BY_STEP["1"])
        self.log(f"attached backend={backend}")
        self._run_step(
            "1", "Opening search options",
            lambda: self.driver.click_with_invoke_fallback(
                CONTROLS_BY_STEP["1"], CONTROLS_BY_STEP["2"]
            ),
        )
        self._run_step(
            "2", "Clearing the search box",
            lambda: self.driver.clear(CONTROLS_BY_STEP["2"]),
        )
        self._run_step(
            "3", "Opening Advanced Search",
            lambda: self.driver.click(CONTROLS_BY_STEP["3"]),
        )
        self._run_step(
            "4", "Entering Claim ID",
            lambda: self.driver.input_text(CONTROLS_BY_STEP["4"], claim_id),
        )
        self._run_step(
            "5", "Entering DOS From",
            lambda: self.driver.input_text(CONTROLS_BY_STEP["5"], dos_from),
        )
        self._run_step(
            "6", "Running the search",
            lambda: self.driver.click(CONTROLS_BY_STEP["6"]),
        )

    def _open_search_once_for_case(self) -> None:
        self._check_cancelled()
        self.progress("fresh-start", "Closing old SmartAdvisor subwindows")
        closed_windows = self.driver.close_all_subwindows_for_finish()
        if closed_windows:
            self.log(f"fresh-start closed {closed_windows} subwindow(s)")

        self.progress("attach", "Attaching to SmartAdvisor")
        backend = self.driver.attach(CONTROLS_BY_STEP["1"])
        self.log(f"attached backend={backend}")
        self._run_step(
            "1", "Opening search options",
            lambda: self.driver.click_with_invoke_fallback(
                CONTROLS_BY_STEP["1"], CONTROLS_BY_STEP["2"]
            ),
        )
        self._run_step(
            "2", "Clearing the search box",
            lambda: self.driver.clear(CONTROLS_BY_STEP["2"]),
        )
        self._run_step(
            "3", "Opening Advanced Search",
            lambda: self.driver.click(CONTROLS_BY_STEP["3"]),
        )

    def _clear_progressive_search_field(self, label: str, clear_step: str) -> None:
        self._run_step(
            clear_step,
            f"Clearing optional {label}",
            lambda: self.driver.clear(CONTROLS_BY_STEP[clear_step]),
        )

    def _enter_progressive_search_field(
        self,
        label: str,
        clear_step: str,
        input_step: str,
        value: str,
    ) -> None:
        self._clear_progressive_search_field(label, clear_step)
        self._run_step(
            input_step,
            f"Entering optional {label}",
            lambda: self.driver.input_text(CONTROLS_BY_STEP[clear_step], value),
        )

    def _run_search_step(self, *, prefer_enter: bool = False) -> bool:
        if self.driver.acknowledge_no_records_popup(timeout=0.5):
            self.log("SmartAdvisor reported no records found before search OK")
            return False

        try:
            if prefer_enter:
                self.driver.send_focused_keys("{ENTER}", step="6")
            else:
                self.driver.click(CONTROLS_BY_STEP["6"])
        except AutomationError as exc:
            if self.driver.acknowledge_no_records_popup(timeout=2.0):
                self.log("SmartAdvisor reported no records found while running search")
                return False
            if not prefer_enter:
                self.log("search OK button unavailable; retrying search with Enter")
                try:
                    self.driver.send_focused_keys("{ENTER}", step="6")
                except AutomationError:
                    if self.driver.acknowledge_no_records_popup(timeout=2.0):
                        self.log(
                            "SmartAdvisor reported no records found while "
                            "running Enter fallback search"
                        )
                        return False
                    raise exc
            else:
                raise

        self.driver.acknowledge_smartadvisor_exception_popup(timeout=1.0)
        if self.driver.acknowledge_no_records_popup(timeout=3.0):
            self.log("SmartAdvisor reported no records found after search")
            return False
        return True

    def _search_with_claim_id_fallback(
        self,
        claim_id: str,
        dos_from: str,
        prov_tin: str,
        patient_account: str,
        expected_amount: str,
    ) -> WorkflowResult | None:
        """Enter each identifying field in priority order, cumulatively.

        Claim ID, DOS, Tax ID, and Patient Account are added on top of each
        other one at a time. A field that comes back "No records found" is
        removed, but every previously-kept field stays in place. If fewer
        than MINIMUM_SUCCESSFUL_SEARCH_FIELDS end up kept, a single input
        cannot confidently identify a claim, so it is reported as not on
        file rather than handed off for amount matching. Returns a
        WorkflowResult when no claim was found, or None when the caller
        should proceed to amount matching against the open results.
        """
        provided_fields = [
            ("Claim ID", claim_id, "4", "4.1"),
            ("DOS From", dos_from, "5", "5.1"),
            ("Prov TIN", prov_tin, "5.5", "5.6"),
            ("Patient Account", patient_account, "5.7", "5.8"),
        ]
        provided_fields = [
            (label, value, clear_step, input_step)
            for label, value, clear_step, input_step in provided_fields
            if str(value or "").strip()
        ]

        kept_labels: list[str] = []
        final_results_open = False

        self._open_search_once_for_case()

        for label, value, clear_step, input_step in provided_fields:
            self.log(
                "search attempt adding "
                + label
                + (
                    f" to kept inputs: {', '.join(kept_labels)}"
                    if kept_labels
                    else ""
                )
            )
            self._enter_progressive_search_field(
                label, clear_step, input_step, str(value).strip()
            )
            self._check_cancelled()
            self.progress("6", f"Running search after adding {label}")
            if self._run_search_step():
                kept_labels.append(label)
                final_results_open = True
                self.log(f"search kept {label}; matched search inputs={len(kept_labels)}")
                self.driver.invalidate_scopes()
                continue

            final_results_open = False
            self.log(f"search rejected {label}; clearing only that input")
            self.driver.invalidate_scopes()
            self._clear_progressive_search_field(label, clear_step)
            if kept_labels:
                self.progress(
                    "6", "Restoring results after clearing rejected " + label
                )
                if self._run_search_step(prefer_enter=True):
                    final_results_open = True
                    self.log(
                        "search rows restored from kept inputs: "
                        + ", ".join(kept_labels)
                    )
                    self.driver.invalidate_scopes()
                else:
                    final_results_open = False
                    self.log(
                        "kept-input restore found no records after rejecting "
                        + label
                    )

        unique_kept_labels = [
            label for label in kept_labels if label not in NON_UNIQUE_SEARCH_LABELS
        ]
        if (
            len(kept_labels) < MINIMUM_SUCCESSFUL_SEARCH_FIELDS
            or not unique_kept_labels
        ):
            self.log(
                "no claim on file; fewer than "
                f"{MINIMUM_SUCCESSFUL_SEARCH_FIELDS} unique input(s) returned rows "
                f"(kept={', '.join(kept_labels) or 'none'})"
            )
            return self._no_claim_on_file_result(
                claim_id=claim_id,
                dos_from=dos_from,
                expected_amount=expected_amount,
                prov_tin=prov_tin,
                patient_account=patient_account,
            )

        if not final_results_open:
            self.log(
                "rerunning final kept-input search without fresh-start: "
                + ", ".join(kept_labels)
            )
            self.driver.invalidate_scopes()
            self.progress("6", "Running final kept-input search")
            if self._run_search_step(prefer_enter=True):
                return None
            self.log("final kept-input search unexpectedly found no records")
            return self._no_claim_on_file_result(
                claim_id=claim_id,
                dos_from=dos_from,
                expected_amount=expected_amount,
                prov_tin=prov_tin,
                patient_account=patient_account,
            )

        self.log("final search rows ready from kept inputs: " + ", ".join(kept_labels))
        return None

    def _select_row(self, row_index: int) -> None:
        self._run_step(
            "7.0", "Focusing the results grid",
            lambda: self.driver.focus_grid(CONTROLS_BY_STEP["7.0"]),
        )
        self._run_step(
            "7.1", "Calibrating to the first row",
            lambda: self.driver.send_focused_keys(GRID_CALIBRATE_DOWN, step="7.1"),
        )
        self.driver.send_focused_keys(GRID_CALIBRATE_UP, step="7.1")
        if row_index:
            self.progress("7.1", f"Moving down to row {row_index + 1}")
            self.driver.send_focused_keys(GRID_SEEK_DOWN * row_index, step="7.1")
        self._check_cancelled()
        self.log(f"row {row_index} selected")

    def _copy_selected_search_row(self, row_index: int) -> dict[str, str]:
        details = self._copy_selected_search_row_once(row_index)
        if details.get("Total Charges"):
            return details
        self.log(f"row {row_index} partial copy; retrying with direct row click")
        first_row_y = (
            GRID_FIRST_ROW_LOWER_CLICK_Y if row_index == 0 else GRID_FIRST_ROW_CLICK_Y
        )
        self.driver.click_grid_row(
            CONTROLS_BY_STEP["7.1"], row_index, first_row_y=first_row_y
        )
        details = self._copy_selected_search_row_once(row_index)
        if details.get("Total Charges") or row_index != 0:
            return details
        self.driver.click_grid_row(
            CONTROLS_BY_STEP["7.1"], row_index, first_row_y=GRID_FIRST_ROW_CLICK_Y
        )
        return self._copy_selected_search_row_once(row_index)

    def _copy_selected_search_row_once(self, row_index: int) -> dict[str, str]:
        try:
            write_clipboard_text("")
        except Exception as exc:
            self.log(f"row {row_index} clipboard clear failed: {type(exc).__name__}")
        self._run_step(
            "7.1", "Copying selected search row",
            lambda: self.driver.send_focused_keys(GRID_COPY_ROW, step="7.1"),
        )
        self.driver.acknowledge_smartadvisor_exception_popup(timeout=0.75)
        raw_text = ""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            self._check_cancelled()
            try:
                raw_text = read_clipboard_text()
            except Exception as exc:
                self.log(f"row {row_index} clipboard read failed: {type(exc).__name__}")
                return {}
            if raw_text.strip():
                break
            time.sleep(0.1)
        details = parse_search_result_clipboard(raw_text)
        if not details:
            self.log(f"row {row_index} clipboard row copy produced no details")
            return {}
        self.log(
            "copied search row "
            + "; ".join(f"{key}={value}" for key, value in sorted(details.items()))
        )
        return details

    def _open_selected_bill(self) -> None:
        self._run_step(
            "7.2", "Confirming the selected search row",
            lambda: self.driver.send_focused_keys(GRID_CONFIRM_ROW, step="7.2"),
        )
        self._run_step(
            "7.2", "Opening the selected bill",
            lambda: self.driver.click(CONTROLS_BY_STEP["7.2"]),
        )
        warning = CONTROLS_BY_STEP["7.3"]
        self._check_cancelled()
        if self.driver.is_present(warning, timeout=1.0):
            self.progress("7.3", "Acknowledging the pended bill warning")
            self.driver.click(warning)

    def _enter_open_bill_client(self, client: str) -> None:
        client = client.strip().upper()
        client_spec = CONTROLS_BY_STEP["7.20"]
        self.driver.click(client_spec)
        self.driver.send_focused_keys("^a{BACKSPACE}", step="7.20")
        self.driver.paste_focused_text(client, step="7.20")
        self.driver.send_focused_keys("{ENTER}", step="7.20")
        time.sleep(0.6)

        selected_client = self.driver.read_text(client_spec, timeout=8.0)
        selected_normalized = selected_client.strip().upper()
        valid_prefixes = (client, f"{client} ", f"{client}-", f"{client} -")
        if not any(
            selected_normalized.startswith(prefix) for prefix in valid_prefixes
        ):
            self.log(
                "Open Bill client verification failed after paste; "
                f"selected={selected_client!r}"
            )
            self.driver.input_text(client_spec, client)
            self.driver.send_focused_keys("{ENTER}", step="7.20")
            time.sleep(0.6)
            selected_client = self.driver.read_text(client_spec, timeout=8.0)
            selected_normalized = selected_client.strip().upper()
            if not any(
                selected_normalized.startswith(prefix) for prefix in valid_prefixes
            ):
                raise AutomationError(
                    "direct_bill_client_not_selected",
                    step="7.20",
                    diagnostics={
                        "client": client,
                        "selected_client": selected_client,
                    },
                )
        self.log(f"Open Bill client selected: {selected_client}")

    def _wait_for_bill_entry_after_open(
        self,
        *,
        timeout: float,
        error_code: str,
        step: str,
    ) -> None:
        initial_timeout = min(timeout, 3.0)
        if self.driver.is_present(CONTROLS_BY_STEP["7.4"], timeout=initial_timeout):
            return

        self.log("bill entry tab not ready; checking pended warning")
        warning = CONTROLS_BY_STEP["7.3"]
        self._check_cancelled()
        if self.driver.is_present(warning, timeout=1.0):
            self.progress("7.3", "Acknowledging the pended bill warning")
            self.driver.click(warning)

        if not self.driver.is_present(CONTROLS_BY_STEP["7.4"], timeout=timeout):
            raise AutomationError(error_code, step=step)

    def _open_bill_by_reference(self, client: str, bill_no: str) -> dict[str, str]:
        self._check_cancelled()
        self.progress("fresh-start", "Closing old SmartAdvisor subwindows")
        closed_windows = self.driver.close_all_subwindows_for_finish()
        if closed_windows:
            self.log(f"fresh-start closed {closed_windows} subwindow(s)")

        self.progress("attach", "Attaching to SmartAdvisor")
        backend = self.driver.attach(CONTROLS_BY_STEP["1"])
        self.log(f"attached backend={backend}")

        self._run_step(
            "7.20",
            f"Selecting Open Bill client {client}",
            lambda: self._enter_open_bill_client(client),
        )
        self._run_step(
            "7.21",
            "Entering Open Bill number",
            lambda: self.driver.input_child_edit_text(
                CONTROLS_BY_STEP["7.21"], bill_no
            ),
        )
        self._run_step(
            "7.22",
            "Opening direct bill reference",
            lambda: self.driver.click(CONTROLS_BY_STEP["7.22"]),
        )
        self._wait_for_bill_entry_after_open(
            timeout=25.0,
            error_code="direct_bill_open_failed",
            step="7.22",
        )
        self.log(f"direct bill {client}-{bill_no} opened")
        return {"Client": client, "Bill No": bill_no}

    def _select_bill_tab(self, step: str, label: str, fragment: str) -> None:
        self._run_step(
            step, f"Switching to the {label} tab",
            lambda: self.driver.select_tab(
                CONTROLS_BY_STEP["7.4"],
                expected_fragment=fragment,
                accelerator=BILL_TAB_ACCELERATOR,
                next_key=BILL_TAB_NEXT_KEY,
                fallback_key=BILL_TAB_FALLBACK_KEY,
                max_presses=BILL_TAB_MAX_PRESSES,
                settle_timeout=BILL_TAB_SETTLE_TIMEOUT,
            ),
        )

    def _wait_for_history_paid_amount(self) -> str:
        deadline = time.monotonic() + HISTORY_TAB_READY_TIMEOUT
        last_error = ""
        while time.monotonic() < deadline:
            self._check_cancelled()
            try:
                value = self.driver.read_text(
                    CONTROLS_BY_STEP["7.6"], timeout=1.0
                ).strip()
            except AutomationError as exc:
                last_error = exc.code
                time.sleep(0.5)
                continue
            if value:
                return value
            last_error = "empty_paid_amount"
            time.sleep(0.5)
        self.log(
            f"history paid amount not ready after {HISTORY_TAB_READY_TIMEOUT:.0f}s; "
            f"last={last_error}"
        )
        raise AutomationError("history_paid_amount_not_ready", step="7.6")

    def _read_history_check_transaction(self) -> str:
        self.progress("7.10", "Reading history check/transaction")
        try:
            return self.driver.read_text(CONTROLS_BY_STEP["7.10"]).strip()
        except AutomationError as exc:
            self.log(f"history check/transaction unavailable ({exc.code})")
            return ""

    def _read_header_paid_date(self) -> str:
        self.progress("7.12", "Reading header paid date")
        try:
            return self.driver.read_text(
                CONTROLS_BY_STEP["7.12"], timeout=3.0
            ).strip()
        except AutomationError as exc:
            self.log(f"header paid date unavailable ({exc.code})")
            return ""

    def _read_header_received_date(self) -> str:
        self.progress("7.13", "Reading header received date")
        try:
            return self.driver.read_text(
                CONTROLS_BY_STEP["7.13"], timeout=3.0
            ).strip()
        except AutomationError as exc:
            self.log(f"header received date unavailable ({exc.code})")
            return ""

    def _current_lines_row_count(self) -> int:
        try:
            tab_name = self.driver.read_text(CONTROLS_BY_STEP["7.4"])
        except AutomationError:
            return LINES_DENIED_CODE_MAX_ROWS
        count = extract_lines_count(tab_name)
        return count if count is not None else LINES_DENIED_CODE_MAX_ROWS

    def _copy_lines_denied_row(self, row_index: int) -> LinesRowCopy:
        row_y = LINES_FIRST_ROW_CLICK_Y + (LINES_ROW_HEIGHT * row_index)
        try:
            write_clipboard_text("")
        except Exception as exc:
            self.log(
                f"lines row {row_index + 1} clipboard clear failed: "
                f"{type(exc).__name__}"
            )
        self.driver.click_at(
            CONTROLS_BY_STEP["7.8"], x=LINES_ROW_SELECTOR_CLICK_X, y=row_y
        )
        self.driver.send_focused_keys(GRID_COPY_ROW, step="7.8")
        self.driver.acknowledge_smartadvisor_exception_popup(timeout=0.5)
        raw_text = ""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            self._check_cancelled()
            try:
                raw_text = read_clipboard_text()
            except Exception as exc:
                self.log(
                    f"lines row {row_index + 1} clipboard read failed: "
                    f"{type(exc).__name__}"
                )
                return LinesRowCopy(False, "", "", "")
            if raw_text.strip():
                break
            time.sleep(0.1)
        return LinesRowCopy(
            copied_lines_row_has_data(raw_text),
            extract_lines_bradj_code_from_clipboard(raw_text),
            extract_lines_br_msg_code_from_clipboard(raw_text),
            copied_lines_row_signature(raw_text),
        )

    def _read_lines_denied_codes(self) -> tuple[str, str]:
        minimum_rows = max(0, self._current_lines_row_count())
        denied_codes: list[str] = []
        br_msg_codes: list[str] = []
        previous_signature = ""
        for row_index in range(LINES_DENIED_CODE_MAX_ROWS):
            self._check_cancelled()
            row_copy = self._copy_lines_denied_row(row_index)
            if not row_copy.has_data:
                break
            if (
                row_index + 1 > minimum_rows
                and row_copy.signature
                and row_copy.signature == previous_signature
            ):
                break
            previous_signature = row_copy.signature
            if row_copy.denied_code and row_copy.denied_code not in denied_codes:
                denied_codes.append(row_copy.denied_code)
            if row_copy.br_msg_code and row_copy.br_msg_code not in br_msg_codes:
                br_msg_codes.append(row_copy.br_msg_code)
        return ", ".join(denied_codes), ", ".join(br_msg_codes)

    def _open_print_eor_window(self) -> None:
        self._run_step(
            "7.9",
            "Opening Print Explanation of Review",
            lambda: self.driver.send_focused_keys(PRINT_EOR_KEYS, step="7.9"),
        )
        if not self.driver.is_present(CONTROLS_BY_STEP["7.9"], timeout=10.0):
            raise AutomationError("print_eor_window_not_found", step="7.9")
        self.log("Print Explanation of Review window ready")

    def _click_print_eor_add(self) -> None:
        try:
            self.driver.click(CONTROLS_BY_STEP["8.3"])
            return
        except AutomationError as exc:
            if exc.code not in {
                "selector_not_found",
                "selector_ambiguous",
                "click_failed",
            }:
                raise

        self.log("Print EOR Add selector unavailable; trying Alt+A")
        self.driver.send_focused_keys(PRINT_EOR_ADD_FALLBACK_KEYS, step="8.3")

    def _click_print_eor_ok(self) -> None:
        try:
            self.driver.click(CONTROLS_BY_STEP["8.4"])
            return
        except AutomationError as exc:
            if exc.code not in {
                "selector_not_found",
                "selector_ambiguous",
                "click_failed",
            }:
                raise

        self.log("Print EOR OK selector unavailable; trying Alt+O")
        self.driver.send_focused_keys(PRINT_EOR_OK_FALLBACK_KEYS, step="8.4")

    def _prepare_print_eor_selection(self, row_details: dict[str, str]) -> None:
        bill_no = (
            row_details.get("Bill No")
            or row_details.get("Bill no")
            or ""
        ).strip()
        if not bill_no:
            raise AutomationError("print_eor_bill_no_missing", step="8.2")

        self._run_step(
            "8.0",
            "Selecting Print EOR List option",
            lambda: self.driver.click(CONTROLS_BY_STEP["8.0"]),
        )
        self._run_step(
            "8.1",
            "Selecting Print EOR Bill No option",
            lambda: self.driver.click(CONTROLS_BY_STEP["8.1"]),
        )
        self._run_step(
            "8.2",
            "Entering Print EOR bill number",
            lambda: self.driver.input_child_edit_text(
                CONTROLS_BY_STEP["8.2"], bill_no
            ),
        )
        self._run_step(
            "8.2.1",
            "Committing Print EOR bill number",
            lambda: self.driver.send_focused_keys(
                PRINT_EOR_BILL_LIST_COMMIT_KEYS,
                step="8.2.1",
            ),
        )
        self._run_step(
            "8.3",
            "Adding bill to Print EOR selection",
            self._click_print_eor_add,
        )
        if self.driver.acknowledge_duplicate_selection_popup(timeout=2.5):
            self.log("Print EOR duplicate selection was not added again")
        else:
            self.log(f"Print EOR bill {bill_no} added or already ready")
        self._run_step(
            "8.4",
            "Confirming Print EOR selection",
            self._click_print_eor_ok,
        )
        self.log("Print EOR OK clicked")
        self._confirm_print_setup_file_output()

    def _confirm_print_setup_file_output(self) -> None:
        if not self.driver.is_present(CONTROLS_BY_STEP["8.5"], timeout=10.0):
            raise AutomationError("print_setup_window_not_found", step="8.5")
        self.log("Print Setup window ready")

        try:
            self._run_step(
                "8.6",
                "Selecting Print Setup File option",
                lambda: self.driver.click(CONTROLS_BY_STEP["8.6"]),
            )
        except AutomationError:
            self.log("Print Setup File radio not resolved; trying Alt+F")
            self.driver.send_focused_keys(
                PRINT_SETUP_FILE_FALLBACK_KEYS,
                step="8.6",
            )

        self._run_step(
            "8.7",
            "Confirming Print Setup",
            lambda: self.driver.click(CONTROLS_BY_STEP["8.7"]),
        )
        self.log("Print Setup OK clicked")

    @staticmethod
    def _eor_output_directory() -> Path:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "SmartAdvisorAutomation" / EOR_OUTPUT_DIRECTORY_NAME

    @staticmethod
    def _safe_file_stem(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value).strip(" .-")
        return cleaned or "bill"

    def _eor_pdf_path(self, row_details: dict[str, str]) -> Path:
        bill_name = self._safe_file_stem(bill_document_name(row_details))
        return self._eor_output_directory() / f"{bill_name}.pdf"

    def _save_export_report_pdf(self, row_details: dict[str, str]) -> str:
        pdf_path = self._eor_pdf_path(row_details)
        try:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AutomationError("eor_directory_not_created", step="8.8") from exc

        if self.driver.wait_for_window_title(
            EXPORT_REPORT_WINDOW_NAME,
            timeout=45.0,
        ):
            self.log("Export Report found via global window search")
        else:
            raise AutomationError(
                "export_report_window_not_found",
                step="8.8",
            )
        self.log("Export Report window ready")

        export_ok_spec = ControlSpec(
            step="9.2",
            automation_id="",
            label="Export Report OK",
            action="click",
            name=EXPORT_REPORT_OK_BUTTON_NAME,
            control_type="Button",
            search_depth=SCOPE_SEARCH_DEPTH,
        )

        def click_export_browse() -> None:
            try:
                self.driver.click_child_in_window_title(
                    EXPORT_REPORT_WINDOW_NAME,
                    CONTROLS_BY_STEP["8.9"],
                    timeout=15.0,
                )
            except AutomationError:
                self.driver.click(CONTROLS_BY_STEP["8.9"])

        def confirm_export_report() -> None:
            try:
                self.driver.click_child_in_window_title(
                    EXPORT_REPORT_WINDOW_NAME,
                    export_ok_spec,
                    timeout=15.0,
                )
            except AutomationError:
                self.driver.focus_window_title(
                    EXPORT_REPORT_WINDOW_NAME,
                    timeout=15.0,
                )
                self.driver.send_focused_keys(
                    EXPORT_REPORT_OK_KEYS,
                    step="9.2",
                )

        self._run_step("8.9", "Opening EOR Save As", click_export_browse)
        time.sleep(0.8)
        self._run_step(
            "9.0",
            "Entering EOR PDF path",
            lambda: self._enter_save_as_path(str(pdf_path)),
        )
        self.log(
            f"waiting {SAVE_AS_REVIEW_DELAY_SECONDS:g}s before Save As confirm"
        )
        time.sleep(SAVE_AS_REVIEW_DELAY_SECONDS)
        self._run_step(
            "9.1",
            "Saving EOR PDF path",
            lambda: self.driver.send_focused_keys(
                SAVE_AS_SAVE_KEYS,
                step="9.1",
            ),
        )
        if self.driver.acknowledge_save_as_overwrite_popup(timeout=4.0):
            self.log("existing EOR PDF overwrite confirmed")
        time.sleep(1.0)
        self._run_step("9.2", "Confirming Export Report", confirm_export_report)
        self.log(f"EOR PDF save requested at {pdf_path}")
        return str(pdf_path)

    def _enter_save_as_path(self, pdf_path: str) -> None:
        self.driver.send_focused_keys(SAVE_AS_FILENAME_KEYS, step="9.0")
        self.driver.send_focused_keys("^a{BACKSPACE}", step="9.0")
        self.driver.paste_focused_text(pdf_path, step="9.0")

    def _resolve_matched_bill(
        self,
        *,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        amount: str,
        row_index: int,
        row_details: dict[str, str],
    ) -> WorkflowResult:
        self._open_selected_bill()
        return self._classify_open_bill_status(
            claim_id=claim_id,
            dos_from=dos_from,
            expected_amount=expected_amount,
            amount=amount,
            row_index=row_index,
            row_details=row_details,
            patient_account=row_details.get("Patient Account"),
        )

    def _classify_open_bill_status(
        self,
        *,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        amount: str,
        row_index: int,
        row_details: dict[str, str],
        patient_account: str | None,
    ) -> WorkflowResult:
        self._select_bill_tab("7.4", "History", BILL_HISTORY_TAB_NAME_FRAGMENT)
        paid_amount = self._wait_for_history_paid_amount()
        check_number = self._read_history_check_transaction()
        if not amount_is_nonzero(paid_amount):
            self._select_bill_tab("7.5", "Lines", BILL_LINES_TAB_NAME_FRAGMENT)
            denied_codes, br_msg_codes = self._read_lines_denied_codes()
            denial_code = ", ".join(
                value for value in (denied_codes, br_msg_codes) if value
            ) or None
            if denial_code:
                self._open_print_eor_window()
                self._prepare_print_eor_selection(row_details)
                eor_pdf_path = self._save_export_report_pdf(row_details)
                reply = build_reply_template(
                    "denied",
                    claim_id=claim_id,
                    dos_from=dos_from,
                    expected_amount=expected_amount,
                    paid_amount=paid_amount,
                    denial_code=denial_code,
                    bill_name=bill_document_name(row_details),
                )
                return WorkflowResult(
                    patient_account=patient_account,
                    amount=amount,
                    outcome="Completed Processing - Denied",
                    row_index=row_index,
                    rows_examined=row_index + 1,
                    disposition="denied",
                    reply_template=reply,
                    paid_amount=paid_amount,
                    denial_code=denial_code,
                    eor_pdf_path=eor_pdf_path,
                )

            self._select_bill_tab("7.11", "Header", BILL_HEADER_TAB_NAME_FRAGMENT)
            received_date = self._read_header_received_date()
            reply = build_reply_template(
                "pending",
                claim_id=claim_id,
                dos_from=dos_from,
                expected_amount=expected_amount,
                received_date=received_date,
                bill_name=bill_document_name(row_details),
            )
            return WorkflowResult(
                patient_account=patient_account,
                amount=amount,
                outcome=(
                    "Bill found but still in temporary - Bill Status pending"
                ),
                row_index=row_index,
                rows_examined=row_index + 1,
                disposition="pending",
                reply_template=reply,
                received_date=received_date or None,
            )

        self._select_bill_tab("7.11", "Header", BILL_HEADER_TAB_NAME_FRAGMENT)
        paid_date = self._read_header_paid_date()
        self._open_print_eor_window()
        self._prepare_print_eor_selection(row_details)
        eor_pdf_path = self._save_export_report_pdf(row_details)
        reply = build_reply_template(
            "paid",
            claim_id=claim_id,
            dos_from=dos_from,
            expected_amount=expected_amount,
            paid_amount=paid_amount,
            paid_date=paid_date,
            check_number=check_number,
            bill_name=bill_document_name(row_details),
        )
        return WorkflowResult(
            patient_account=patient_account,
            amount=amount,
            outcome="Completed Processing - Paid",
            row_index=row_index,
            rows_examined=row_index + 1,
            disposition="paid",
            reply_template=reply,
            paid_amount=paid_amount,
            paid_date=paid_date or None,
            check_number=check_number or None,
            eor_pdf_path=eor_pdf_path,
        )

    def _no_claim_on_file_result(
        self,
        *,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        prov_tin: str,
        patient_account: str,
    ) -> WorkflowResult:
        reply = build_reply_template(
            "no_claim_on_file",
            claim_id=claim_id,
            dos_from=dos_from,
            expected_amount=expected_amount,
            prov_tin=prov_tin,
            patient_account=patient_account,
        )
        self.progress("complete", "No claim on file")
        return WorkflowResult(
            patient_account=patient_account or None,
            amount=expected_amount,
            outcome="There is no claim on file matching the information provided.",
            row_index=0,
            rows_examined=0,
            disposition="no_claim_on_file",
            reply_template=reply,
        )

    def _no_match_result(
        self,
        *,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        amount: str,
        row_index: int,
    ) -> WorkflowResult:
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

    def run(
        self,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
        prov_tin: str = "",
        patient_account: str = "",
        *,
        leave_match_open: bool = True,
    ) -> WorkflowResult:
        claim_id = validate_optional_claim_id(claim_id)
        direct_bill = parse_direct_bill_reference(claim_id)
        if direct_bill is not None:
            client, bill_no = direct_bill
            prov_tin = prov_tin.strip()
            patient_account = patient_account.strip()
            self.log(f"run start direct bill reference={client}-{bill_no}")
            self.driver.invalidate_scopes()
            row_details = self._open_bill_by_reference(client, bill_no)
            result = self._classify_open_bill_status(
                claim_id=claim_id,
                dos_from=dos_from,
                expected_amount=expected_amount,
                amount=expected_amount,
                row_index=0,
                row_details=row_details,
                patient_account=patient_account or None,
            )
            self.progress("complete", result.outcome)
            if not leave_match_open:
                self._run_step(
                    "7.7", "Closing the matched bill before the next job",
                    lambda: self.driver.click(CONTROLS_BY_STEP["7.7"]),
                )
            return result

        dos_from = normalize_optional_dos(dos_from)
        expected_amount = validate_expected_amount(expected_amount)
        expected = normalize_amount(expected_amount)
        prov_tin = prov_tin.strip()
        patient_account = patient_account.strip()
        validate_search_inputs(claim_id, dos_from, prov_tin, patient_account)
        self.log(f"run start expected={expected_amount}")

        self.driver.invalidate_scopes()
        no_claim_result = self._search_with_claim_id_fallback(
            claim_id, dos_from, prov_tin, patient_account, expected_amount
        )
        if no_claim_result is not None:
            return no_claim_result
        previous_amount: str | None = None
        previous_signature: str | None = None
        for row_index in range(MAX_ITERATIONS):
            self._check_cancelled()
            self.progress("candidate", f"Checking candidate row {row_index + 1}")
            self._select_row(row_index)
            row_details = self._copy_selected_search_row(row_index)
            signature = search_result_signature(row_details) if row_details else ""
            amount = row_details.get("Total Charges", "") or "0"
            if signature and signature == previous_signature:
                self.log(f"row {row_index} repeated the previous copied row")
                return self._no_match_result(
                    claim_id=claim_id,
                    dos_from=dos_from,
                    expected_amount=expected_amount,
                    amount=amount,
                    row_index=row_index,
                )
            if not signature and previous_amount is not None and amount == previous_amount:
                self.log(f"row {row_index} repeated the previous amount")
                return self._no_match_result(
                    claim_id=claim_id,
                    dos_from=dos_from,
                    expected_amount=expected_amount,
                    amount=amount,
                    row_index=row_index,
                )

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
                    row_details=row_details,
                )
                self.progress("complete", result.outcome)
                if not leave_match_open:
                    self._run_step(
                        "7.7", "Closing the matched bill before the next job",
                        lambda: self.driver.click(CONTROLS_BY_STEP["7.7"]),
                    )
                return result
            previous_amount = amount
            previous_signature = signature or previous_signature
        raise AutomationError("candidate_iteration_limit", step="7.1")
