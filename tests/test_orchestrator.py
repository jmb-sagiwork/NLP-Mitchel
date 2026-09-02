from __future__ import annotations

import threading
from pathlib import Path

from email_triage.types import FieldValue, TriageResult, TriageStatus

from mitchel_pipeline.helper_client import SmartAdvisorHelperError
from mitchel_pipeline.models import ExtractedEmail
from mitchel_pipeline.orchestrator import PipelineOrchestrator
from mitchel_pipeline.run_control import ParkRequested, RunControl


class FakeExtractor:
    def __init__(self, emails):
        self.emails = emails
        self.closed = False
        self.replies_sent = []
        self.parked = 0

    def extract(self, control, progress):
        progress(0, len(self.emails), "extracting")
        progress(len(self.emails), len(self.emails), "extracted")
        return self.emails

    def send_reply(self, reply_text):
        self.replies_sent.append(reply_text)

    def park_now(self):
        self.parked += 1

    def close(self):
        self.closed = True


class RetryHelper:
    def __init__(self):
        self.calls = 0
        self.failed = threading.Event()
        self.closed = False

    def run_job(self, job, control, progress, *, leave_open=True):
        self.calls += 1
        if self.calls == 1:
            self.failed.set()
            raise SmartAdvisorHelperError("window_not_found", "attach")
        progress("complete", "matched")
        return {"amount": job.expected_amount}

    def close(self):
        self.closed = True


class OrderedExtractor:
    def __init__(self, emails, order):
        self.emails = emails
        self.order = order
        self.closed = False

    def extract(self, control, progress):
        total = len(self.emails)
        for index, email in enumerate(self.emails, start=1):
            progress(index - 1, total, "extracting")
            self.order.append(f"extract:{email.message_id}")
            progress(index, total, "extracted")
            yield email

    def send_reply(self, reply_text):
        self.order.append(f"send:{reply_text}")

    def park_now(self):
        self.order.append("park")

    def close(self):
        self.closed = True


class OrderedHelper:
    def __init__(self, order):
        self.order = order
        self.closed = False

    def run_job(self, job, control, progress, *, leave_open=True):
        assert leave_open is False
        self.order.append(f"smartadvisor:{job.source_message_id}")
        progress("complete", "complete")
        return {"reply_template": f"reply:{job.source_message_id}"}

    def close(self):
        self.closed = True


class ParkingHelper:
    """SmartAdvisor helper that raises ParkRequested on its first job."""

    def __init__(self, order):
        self.order = order
        self.closed = False
        self.calls = 0

    def run_job(self, job, control, progress, *, leave_open=True):
        self.calls += 1
        self.order.append(f"smartadvisor:{job.source_message_id}")
        if self.calls == 1:
            raise ParkRequested()
        progress("complete", "complete")
        return {"reply_template": f"reply:{job.source_message_id}"}

    def close(self):
        self.closed = True


def bill_result():
    return TriageResult(
        status=TriageStatus.CLASSIFIED,
        concern_id="bill_status",
        display_name="Bill Status",
        confidence=0.9,
        margin=0.5,
        needs_review=False,
        fields={
            "claim_id": FieldValue("claim_id", "Claim ID", "WC123"),
            "date_of_service": FieldValue("date_of_service", "DOS", "2026-04-21"),
            "expected_amount": FieldValue("expected_amount", "Amount", "527.00"),
        },
    )


def test_smartadvisor_error_pauses_and_resume_retries(monkeypatch):
    email = ExtractedEmail("email-1", "Bill", "body", Path("email.txt"))
    extractor = FakeExtractor([email])
    helper = RetryHelper()
    events = []
    control = RunControl()
    monkeypatch.setattr("mitchel_pipeline.orchestrator.classify_email", lambda *a, **k: bill_result())
    orchestrator = PipelineOrchestrator(
        extractor,
        enable_minilm=False,
        helper=helper,
        emit=events.append,
        engine=object(),
    )
    worker = threading.Thread(target=orchestrator.run, args=(control,))
    worker.start()
    assert helper.failed.wait(1)
    for _ in range(100):
        if control.paused:
            break
        threading.Event().wait(0.01)
    assert control.paused

    control.resume()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert helper.calls == 2
    assert helper.closed and extractor.closed
    assert any(event.kind == "error" for event in events)
    assert events[-1].kind == "complete"


def test_each_email_finishes_before_the_next_email_is_extracted(monkeypatch):
    emails = [
        ExtractedEmail("email-1", "Bill 1", "body 1", Path("email-1.txt")),
        ExtractedEmail("email-2", "Bill 2", "body 2", Path("email-2.txt")),
    ]
    order = []
    extractor = OrderedExtractor(emails, order)
    helper = OrderedHelper(order)

    def classify(*_args, **kwargs):
        order.append(f"nlp:{kwargs['message_key']}")
        return bill_result()

    def approve_reply(reply):
        order.append(reply)
        return True

    monkeypatch.setattr("mitchel_pipeline.orchestrator.classify_email", classify)
    orchestrator = PipelineOrchestrator(
        extractor,
        enable_minilm=False,
        helper=helper,
        engine=object(),
        on_reply=approve_reply,
    )

    summary = orchestrator.run(RunControl())

    assert order == [
        "extract:email-1",
        "nlp:email-1",
        "smartadvisor:email-1",
        "reply:email-1",
        "send:reply:email-1",
        "extract:email-2",
        "nlp:email-2",
        "smartadvisor:email-2",
        "reply:email-2",
        "send:reply:email-2",
    ]
    assert summary.extracted == 2
    assert summary.jobs_completed == 2
    assert extractor.closed and helper.closed


def test_declining_the_reply_stops_the_run_without_sending(monkeypatch):
    emails = [
        ExtractedEmail("email-1", "Bill 1", "body 1", Path("email-1.txt")),
        ExtractedEmail("email-2", "Bill 2", "body 2", Path("email-2.txt")),
    ]
    order = []
    extractor = OrderedExtractor(emails, order)
    helper = OrderedHelper(order)

    monkeypatch.setattr(
        "mitchel_pipeline.orchestrator.classify_email", lambda *a, **k: bill_result()
    )
    events = []
    orchestrator = PipelineOrchestrator(
        extractor,
        enable_minilm=False,
        helper=helper,
        engine=object(),
        emit=events.append,
        on_reply=lambda _reply: False,
    )

    summary = orchestrator.run(RunControl())

    assert not any(entry.startswith("send:") for entry in order)
    assert "extract:email-2" not in order
    assert extractor.closed and helper.closed
    assert events[-1].kind == "status" and events[-1].message == "Run cancelled"


def test_park_it_aborts_the_job_and_continues_to_the_next_email(monkeypatch):
    emails = [
        ExtractedEmail("email-1", "Bill 1", "body 1", Path("email-1.txt")),
        ExtractedEmail("email-2", "Bill 2", "body 2", Path("email-2.txt")),
    ]
    order = []
    extractor = OrderedExtractor(emails, order)
    helper = ParkingHelper(order)

    monkeypatch.setattr(
        "mitchel_pipeline.orchestrator.classify_email", lambda *a, **k: bill_result()
    )
    orchestrator = PipelineOrchestrator(
        extractor,
        enable_minilm=False,
        helper=helper,
        engine=object(),
        on_reply=lambda _reply: True,
    )

    summary = orchestrator.run(RunControl())

    assert order == [
        "extract:email-1",
        "smartadvisor:email-1",
        "park",
        "extract:email-2",
        "smartadvisor:email-2",
        "send:reply:email-2",
    ]
    assert summary.parked == 1
    assert summary.jobs_completed == 1
    assert extractor.closed and helper.closed
