from __future__ import annotations

from smartadvisor_automation.workflow import (
    NoBillOnFileWorkflow,
    build_reply_template,
    extract_denial_code,
    extract_history_details,
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
    def _search(self, claim_id, dos_from):
        pass

    def _select_row(self, row_index):
        pass

    def _read_candidate_amount(self):
        return "10.00"

    def _diagnose_amount_controls(self, expected):
        pass


def test_no_matching_amount_returns_a_normal_result():
    workflow = _NoMatchWorkflow(_NoMatchDriver())

    result = workflow.run("42114901", "08/01/2026", "527.00")

    assert result.disposition == "no_match"
    assert result.rows_examined == 2
    assert "Concern: No Bill on File" in result.reply_template
