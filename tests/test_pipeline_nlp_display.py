from __future__ import annotations

from mitchel_pipeline.app import format_nlp_output


def test_nlp_popup_is_human_readable_and_contains_extracted_values():
    message = format_nlp_output(
        {
            "status": "CLASSIFIED",
            "display_name": "Bill Status",
            "confidence": 0.93,
            "needs_review": False,
            "reason_display_name": None,
            "fields": {
                "claim_id": {
                    "display_name": "Claim ID",
                    "value": "4184847-1",
                    "values": ["4184847-1"],
                },
                "date_of_service": {
                    "display_name": "DOS (Date of Service)",
                    "value": "2026-05-30",
                    "values": ["2026-05-30"],
                },
                "expected_amount": {
                    "display_name": "Expected Amount",
                    "value": "3842.00",
                    "values": ["3842.00"],
                },
            },
            "missing_fields": [],
            "ambiguous_fields": [],
        }
    )

    assert "Concern: Bill Status" in message
    assert "Status: Classified" in message
    assert "Confidence: 93%" in message
    assert "Claim ID: 4184847-1" in message
    assert "DOS (Date of Service): 05/30/2026" in message
    assert "Expected Amount: $3,842.00" in message
    assert "{" not in message
    assert '"status"' not in message


def test_nlp_popup_explains_missing_fields_without_json():
    message = format_nlp_output(
        {
            "status": "AMBIGUOUS",
            "display_name": "Bill Status",
            "confidence": 0.48,
            "needs_review": True,
            "fields": {
                "claim_id": {
                    "display_name": "Claim ID",
                    "value": None,
                    "values": [],
                }
            },
            "missing_fields": ["claim_id"],
            "ambiguous_fields": [],
        }
    )

    assert "Status: Needs review" in message
    assert "Manual review required: Yes" in message
    assert "Missing required information: Claim ID" in message
    assert "{" not in message


def test_nlp_popup_formats_errors_for_an_operator():
    message = format_nlp_output(
        {
            "status": "ERROR",
            "error_code": "ValueError",
        }
    )

    assert message == (
        "The email could not be analyzed.\n\n"
        "Status: Error\n"
        "Manual review required: Yes\n"
        "Error: ValueError"
    )
