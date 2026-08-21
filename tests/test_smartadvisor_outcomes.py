from __future__ import annotations

from smartadvisor_automation.workflow import (
    NoBillOnFileWorkflow,
    bill_document_name,
    build_reply_template,
    extract_denial_code,
    extract_history_details,
    extract_lines_br_msg_code_from_clipboard,
    extract_lines_bradj_code_from_clipboard,
    parse_search_result_clipboard,
)


def test_extract_history_details_supports_adjacent_label_value_controls():
    controls = [
        ("lblPaidAmount", "Paid Amount"),
        ("txtPaidAmount", "$1,245.60"),
        ("lblPaidDate", "Paid Date"),
        ("txtPaidDate", "08/20/2026"),
        ("lblCheckNumber", "Check Number"),
        ("txtCheckNumber", "CHK-77421"),
    ]

    assert extract_history_details(controls) == (
        "$1,245.60",
        "08/20/2026",
        "CHK-77421",
    )


def test_extract_denial_code_supports_combined_label_and_value():
    controls = [("lineReason", "Denial Code: CO-16")]

    assert extract_denial_code(controls) == "CO-16"


def test_reply_templates_cover_no_match_denied_and_paid():
    common = {
        "claim_id": "4211490-1",
        "dos_from": "08/01/2026",
        "expected_amount": "527.00",
    }

    no_match = build_reply_template("no_match", **common)
    denied = build_reply_template("denied", denial_code="CO-16", **common)
    paid = build_reply_template(
        "paid",
        paid_amount="$527.00",
        paid_date="08/20/2026",
        check_number="CHK-77421",
        **common,
    )

    assert "Concern: No Bill on File" in no_match
    assert "Concern: Completed Processing - Denied" in denied
    assert "Denial code: CO-16" in denied
    assert "Concern: Completed Processing - Paid" in paid
    assert "Paid date: 08/20/2026" in paid
    assert "Check number: CHK-77421" in paid


class _NoMatchDriver:
    def invalidate_scopes(self):
        pass

    def click(self, _spec):
        pass


class _NoMatchWorkflow(NoBillOnFileWorkflow):
    def __init__(self, driver):
        super().__init__(driver)
        self.search_calls = 0
        self.rows_selected = []

    def _search_with_claim_id_fallback(self, claim_id, dos_from, prov_tin, patient_account):
        self.search_calls += 1

    def _select_row(self, row_index):
        self.rows_selected.append(row_index)

    def _copy_selected_search_row(self, row_index):
        return {
            "Bill Search DCN": "DCN-1",
            "Total Charges": "10.00",
        }


def test_no_matching_amount_returns_a_normal_result():
    workflow = _NoMatchWorkflow(_NoMatchDriver())

    result = workflow.run("42114901", "08/01/2026", "527.00")

    assert result.disposition == "no_match"
    assert result.rows_examined == 2
    assert "Concern: No Bill on File" in result.reply_template
    assert workflow.search_calls == 1
    assert workflow.rows_selected == [0, 1]


def test_search_result_clipboard_maps_total_charges_and_row_details():
    values = [""] * 28
    values[4] = "CLIENT"
    values[5] = "BILL-77"
    values[14] = "PATIENT-9"
    values[26] = "$527.00"

    parsed = parse_search_result_clipboard("\t".join(values))

    assert parsed["Total Charges"] == "$527.00"
    assert parsed["Bill no"] == "BILL-77"
    assert parsed["Patient Account"] == "PATIENT-9"


def test_lines_clipboard_uses_current_bradj_and_br_message_columns():
    values = [""] * 16
    values[7] = "U02"
    values[14] = "C56"
    copied = "\t".join(values)

    assert extract_lines_br_msg_code_from_clipboard(copied) == "U02"
    assert extract_lines_bradj_code_from_clipboard(copied) == "C56"


class _StatusDriver:
    pass


class _StatusWorkflow(NoBillOnFileWorkflow):
    def __init__(self, paid_amount, denied_codes=("C56", "U02")):
        super().__init__(_StatusDriver())
        self.paid_amount = paid_amount
        self.denied_codes = denied_codes
        self.tabs = []
        self.opened = 0
        self.eor_calls = []

    def _open_selected_bill(self):
        self.opened += 1

    def _select_bill_tab(self, step, label, fragment):
        self.tabs.append(label)

    def _wait_for_history_paid_amount(self):
        return self.paid_amount

    def _read_history_check_transaction(self):
        return "CHK-77421"

    def _read_header_paid_date(self):
        return "08/20/2026"

    def _read_lines_denied_codes(self):
        return self.denied_codes

    def _open_print_eor_window(self):
        self.eor_calls.append("open")

    def _prepare_print_eor_selection(self, row_details):
        self.eor_calls.append(("prepare", row_details["Bill no"]))

    def _save_export_report_pdf(self, row_details):
        self.eor_calls.append(("save", row_details["Bill no"]))
        return rf"C:\EOR's\{row_details['Bill no']}.pdf"


def _resolve_status(workflow):
    return workflow._resolve_matched_bill(
        claim_id="4211490-1",
        dos_from="08/01/2026",
        expected_amount="527.00",
        amount="527.00",
        row_index=0,
        row_details={
            "Client": "CLIENT",
            "Bill no": "BILL-77",
            "Patient Account": "PATIENT-9",
        },
    )


def test_zero_paid_amount_uses_history_then_lines_denial_flow():
    workflow = _StatusWorkflow("0.00")

    result = _resolve_status(workflow)

    assert result.disposition == "denied"
    assert result.denial_code == "C56, U02"
    assert workflow.opened == 1
    assert workflow.tabs == ["History", "Lines"]
    assert workflow.eor_calls == [
        "open",
        ("prepare", "BILL-77"),
        ("save", "BILL-77"),
    ]
    assert result.eor_pdf_path == r"C:\EOR's\BILL-77.pdf"


def test_zero_paid_amount_without_denial_codes_does_not_save_eor():
    workflow = _StatusWorkflow("0.00", denied_codes=("", ""))

    result = _resolve_status(workflow)

    assert result.disposition == "denied"
    assert result.denial_code is None
    assert result.eor_pdf_path is None
    assert workflow.eor_calls == []


def test_nonzero_paid_amount_uses_history_then_header_payment_flow():
    workflow = _StatusWorkflow("527.00")

    result = _resolve_status(workflow)

    assert result.disposition == "paid"
    assert result.paid_date == "08/20/2026"
    assert result.check_number == "CHK-77421"
    assert workflow.opened == 1
    assert workflow.tabs == ["History", "Header"]
    assert workflow.eor_calls == [
        "open",
        ("prepare", "BILL-77"),
        ("save", "BILL-77"),
    ]
    assert result.eor_pdf_path == r"C:\EOR's\BILL-77.pdf"


def test_eor_path_uses_client_and_bill_with_safe_filename(monkeypatch, tmp_path):
    workflow = _StatusWorkflow("527.00")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    path = workflow._eor_pdf_path({"Client": "A:C", "Bill no": "B/7"})

    assert bill_document_name({"Client": "A:C", "Bill no": "B/7"}) == "A:C-B/7"
    assert path == tmp_path / "SmartAdvisorAutomation" / "EOR's" / "A-C-B-7.pdf"
