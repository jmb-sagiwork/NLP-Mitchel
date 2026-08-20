from __future__ import annotations

import threading
from pathlib import Path

from email_triage.types import FieldValue, TriageResult, TriageStatus

from mitchel_pipeline.helper_client import SmartAdvisorHelperError
from mitchel_pipeline.models import ExtractedEmail
from mitchel_pipeline.orchestrator import PipelineOrchestrator
from mitchel_pipeline.run_control import RunControl


class FakeExtractor:
    def __init__(self, emails):
        self.emails = emails
        self.closed = False

    def extract(self, control, progress):
        progress(0, len(self.emails), "extracting")
        progress(len(self.emails), len(self.emails), "extracted")
        return self.emails

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
