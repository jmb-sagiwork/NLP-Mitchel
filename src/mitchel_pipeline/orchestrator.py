from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Callable, Iterable
from typing import Protocol

from email_triage import TriageEngine, classify_email

from .helper_client import SmartAdvisorHelperClient, SmartAdvisorHelperError
from .jobs import deduplicate_jobs, jobs_from_result
from .models import ExtractedEmail, PipelineEvent, RunSummary, SmartAdvisorJob
from .results_workbook import ResultsWorkbook
from .run_control import ParkRequested, RunCancelled, RunControl

EventCallback = Callable[[PipelineEvent], None]
ExtractedCallback = Callable[[ExtractedEmail], None]
NlpCallback = Callable[[dict[str, object]], None]
ReplyCallback = Callable[[str], bool]
LayersCallback = Callable[[tuple[str, ...]], None]

MANUAL_REVIEW_REPLY = (
    "To: Requestor\n"
    "Subject: Bill Status Response\n\n"
    "Concern: Manual Review Required\n\n"
    "We could not create a complete SmartAdvisor lookup from this email. "
    "Please review the extracted email and NLP output."
)


class Extractor(Protocol):
    def extract(
        self,
        control: RunControl,
        progress: Callable[[int, int, str], None],
    ) -> Iterable[ExtractedEmail]: ...

    def send_reply(self, reply_text: str) -> None: ...

    def park_now(self) -> None: ...

    def close(self) -> None: ...


class SiteIdLookup(Protocol):
    def site_id_for_claim(self, claim_number: str) -> str: ...

    def close(self) -> None: ...


class Helper(Protocol):
    def run_job(
        self,
        job: SmartAdvisorJob,
        control: RunControl,
        progress: Callable[[str, str], None],
        *,
        leave_open: bool = True,
    ) -> dict[str, object]: ...

    def close(self) -> None: ...


class PipelineOrchestrator:
    def __init__(
        self,
        extractor: Extractor,
        *,
        enable_minilm: bool,
        helper: Helper | None = None,
        salesforce: SiteIdLookup | None = None,
        results_workbook: ResultsWorkbook | None = None,
        emit: EventCallback | None = None,
        engine: TriageEngine | None = None,
        on_extracted: ExtractedCallback | None = None,
        on_nlp: NlpCallback | None = None,
        on_reply: ReplyCallback | None = None,
        on_layers: LayersCallback | None = None,
        skip_count: int = 0,
    ) -> None:
        self.extractor = extractor
        self.enable_minilm = enable_minilm
        self.helper = helper or SmartAdvisorHelperClient()
        self.salesforce = salesforce
        self.results_workbook = results_workbook or ResultsWorkbook()
        self.emit = emit or (lambda _event: None)
        self.engine = engine
        self.on_extracted = on_extracted or (lambda _email: None)
        self.on_nlp = on_nlp or (lambda _result: None)
        self.on_reply = on_reply or (lambda _reply: True)
        self.on_layers = on_layers or (lambda _layers: None)
        self.skip_count = max(skip_count, 0)
        self._progress = 0.0

    def _approve_or_stop(self, reply: str, control: RunControl, summary: RunSummary) -> None:
        """Ask the operator to approve the generated reply; stop the run on decline."""

        if self.on_reply(reply):
            return
        self._event(
            "status",
            "Run stopped: reply declined",
            self._progress,
            summary.to_dict(),
        )
        control.cancel()
        raise RunCancelled()

    def _event(
        self,
        kind: str,
        message: str,
        progress: float,
        data: dict[str, object] | None = None,
    ) -> None:
        self._progress = max(self._progress, min(100.0, progress))
        self.emit(
            PipelineEvent(
                kind=kind,  # type: ignore[arg-type]
                message=message,
                progress=self._progress,
                data=data or {},
            )
        )

    def run(self, control: RunControl) -> RunSummary:
        summary = RunSummary()
        try:
            control.checkpoint()
            self._event("status", "Starting NICE CXone", 1)
            self._event(
                "status",
                "Loading MiniLM" if self.enable_minilm else "Loading rules engine",
                2,
            )
            engine = self.engine or TriageEngine(enable_embeddings=self.enable_minilm)
            if self.enable_minilm and not engine.embeddings_active:
                self._event("status", "MiniLM unavailable; using rules", 3)
            self.on_layers(getattr(engine, "layers_used", ()))

            extraction_total = 1

            def extraction_progress(done: int, total: int, message: str) -> None:
                nonlocal extraction_total
                extraction_total = max(total, 1)
                completed_emails = max(done - 1, 0) if done else 0
                progress = 5 + ((completed_emails + 0.15) / extraction_total) * 90
                self._event("progress", message, progress)

            emails = self.extractor.extract(control, extraction_progress)
            if self.skip_count:
                self._event(
                    "status", f"Skipping first {self.skip_count} email(s)", 5
                )
                emails = itertools.islice(emails, self.skip_count, None)
            for email_index, email in enumerate(emails, start=1):
                control.checkpoint()
                total = max(extraction_total, email_index)
                slice_start = 5 + ((email_index - 1) / total) * 90
                slice_span = 90 / total
                summary.extracted += 1
                self._event(
                    "summary",
                    summary.display(),
                    slice_start + slice_span * 0.2,
                    summary.to_dict(),
                )
                self.on_extracted(email)

                try:
                    result = classify_email(
                        email.body,
                        email.subject,
                        engine=engine,
                        message_key=email.message_id,
                    )
                    summary.classified += 1
                    self.on_nlp(result.to_dict())
                    jobs = deduplicate_jobs(jobs_from_result(result, email.message_id))
                except Exception as exc:
                    summary.nlp_errors += 1
                    summary.skipped += 1
                    self.on_nlp(
                        {
                            "status": "ERROR",
                            "message_key": email.message_id,
                            "error_code": type(exc).__name__,
                        }
                    )
                    self._approve_or_stop(MANUAL_REVIEW_REPLY, control, summary)
                    self.extractor.send_reply(MANUAL_REVIEW_REPLY)
                    self._event(
                        "summary",
                        summary.display(),
                        slice_start + slice_span,
                        summary.to_dict(),
                    )
                    continue

                self._event(
                    "progress",
                    f"Classified email {email_index} of {total}",
                    slice_start + slice_span * 0.35,
                )
                summary.jobs_created += len(jobs)

                if not jobs:
                    summary.skipped += 1
                    self._approve_or_stop(MANUAL_REVIEW_REPLY, control, summary)
                    self.extractor.send_reply(MANUAL_REVIEW_REPLY)
                    self._event(
                        "summary",
                        summary.display(),
                        slice_start + slice_span,
                        summary.to_dict(),
                    )
                    continue

                try:
                    last_reply = MANUAL_REVIEW_REPLY
                    for job_index, job in enumerate(jobs):
                        job_start = slice_start + slice_span * (
                            0.35 + (job_index / len(jobs)) * 0.55
                        )
                        job_span = slice_span * 0.55 / len(jobs)

                        if self.salesforce is not None:
                            try:
                                site_id = self.salesforce.site_id_for_claim(job.claim_id)
                                job = dataclasses.replace(job, site_id=site_id)
                            except Exception as exc:
                                self._event(
                                    "status",
                                    f"Salesforce Site ID lookup failed: {type(exc).__name__}",
                                    job_start,
                                )

                        helper_result = self._run_smartadvisor_job(
                            job,
                            control,
                            summary,
                            job_start,
                            job_span,
                        )
                        summary.jobs_completed += 1
                        reply = str(
                            helper_result.get("reply_template")
                            or "SmartAdvisor processing completed."
                        )
                        last_reply = reply
                        self._approve_or_stop(reply, control, summary)
                        self.results_workbook.append_result(job, helper_result, reply_sent=True)
                        self._event(
                            "summary",
                            summary.display(),
                            job_start + job_span,
                            summary.to_dict(),
                        )

                    self.extractor.send_reply(last_reply)
                    self._event(
                        "progress",
                        f"Finished email {email_index} of {total}",
                        slice_start + slice_span,
                    )
                except ParkRequested:
                    summary.parked += 1
                    self.extractor.park_now()
                    self._event(
                        "summary",
                        f"Parked email {email_index} of {total} (operator request)",
                        slice_start + slice_span,
                        summary.to_dict(),
                    )
                    continue

            message = "Workflow complete" if summary.extracted else "No CXone emails found"
            self._event("complete", message, 100, summary.to_dict())
            return summary
        except RunCancelled:
            self._event("status", "Run cancelled", self._progress, summary.to_dict())
            return summary
        finally:
            self.extractor.close()
            self.helper.close()
            if self.salesforce is not None:
                self.salesforce.close()

    def _run_smartadvisor_job(
        self,
        job: SmartAdvisorJob,
        control: RunControl,
        summary: RunSummary,
        job_start: float,
        job_span: float,
    ) -> dict[str, object]:
        while True:
            control.checkpoint()
            if control.consume_park_request():
                raise ParkRequested()

            def helper_progress(step: str, message: str) -> None:
                step_fraction = {
                    "attach": 0.05,
                    "1": 0.10,
                    "2": 0.15,
                    "3": 0.20,
                    "4": 0.25,
                    "5": 0.30,
                    "6": 0.35,
                    "candidate": 0.45,
                    "7.0": 0.55,
                    "7.1": 0.62,
                    "7.2": 0.70,
                    "7.3": 0.75,
                    "7.4": 0.80,
                    "7.5": 0.84,
                    "7.6": 0.87,
                    "7.7": 0.90,
                    "7.8": 0.93,
                    "7.9": 0.96,
                    "complete": 1.0,
                }.get(step, 0.45)
                self._event("progress", message, job_start + job_span * step_fraction)

            try:
                return self.helper.run_job(
                    job,
                    control,
                    helper_progress,
                    leave_open=False,
                )
            except SmartAdvisorHelperError as exc:
                summary.smartadvisor_errors += 1
                control.pause()
                self._event(
                    "error",
                    f"SmartAdvisor paused at {exc.step or 'workflow'}: {exc.code}. Resume retries.",
                    self._progress,
                    summary.to_dict(),
                )
                control.wait_for_resume()
