from __future__ import annotations

from email_triage.textprep import prepare, separate_transport_headers
from email_triage.types import Segment


PASTED_EMAIL = """From: sender@example.com
Sent: Mon Jul 27 2026 17:21:18 GMT-0400 (Eastern Daylight Time)
To: claims@example.com
Subject: CLAIM STATUS

Hello,

I need to obtain bill status.
Claim: 4184847CMT1
Date(s) of service as billed: 05/30/2026-05/30/2026
Billed amount(s): $3,842.00
"""


def test_pasted_transport_headers_move_subject_and_are_removed_from_body():
    subject, body = separate_transport_headers(PASTED_EMAIL)

    assert subject == "CLAIM STATUS"
    assert body.startswith("Hello,")
    assert "From:" not in body
    assert "Sent:" not in body
    assert "To:" not in body
    assert "Subject:" not in body


def test_prepare_treats_pasted_header_as_current_message_not_history():
    prepared = prepare(PASTED_EMAIL)

    assert prepared.subject == "CLAIM STATUS"
    assert prepared.segment(Segment.QUOTED_HISTORY.value) is None
    newest = prepared.segment(Segment.NEWEST_BODY.value)
    assert newest is not None
    assert "Claim: 4184847CMT1" in newest.text


def test_explicit_subject_wins_while_pasted_headers_are_removed():
    subject, body = separate_transport_headers(PASTED_EMAIL, "Manual subject")

    assert subject == "Manual subject"
    assert body.startswith("Hello,")
