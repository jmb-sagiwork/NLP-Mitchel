from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from email_triage import TriageEngine, classify_email

from .helper_client import SmartAdvisorHelperClient, SmartAdvisorHelperError
from .jobs import deduplicate_jobs, jobs_from_result
from .models import ExtractedEmail, PipelineEvent, RunSummary, SmartAdvisorJob
from .run_control import RunCancelled, RunControl

EventCallback = Callable[[PipelineEvent], None]


class Extractor(Protocol):
    def extract(
        self,
        control: RunControl,
        progress: Callable[[int, int, str], None],
    ) -> list[ExtractedEmail]: ...

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
        emit: EventCallback | None = None,
        engine: TriageEngine | None = None,
    ) -> None:
        self.extractor = extractor
        self.enable_minilm = enable_minilm
        self.helper = helper or SmartAdvisorHelperClient()
        self.emit = emit or (lambda _event: None)
        self.engine = engine
        self._progress = 0.0

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

            def extraction_progress(done: int, total: int, message: str) -> None:
                denominator = max(total, 1)
                self._event("progress", message, 10 + (done / denominator) * 25)

            emails = self.extractor.extract(control, extraction_progress)
            summary.extracted = len(emails)
            self._event("summary", summary.display(), 35, summary.to_dict())

            control.checkpoint()
            self._event(
                "status",
                "Loading MiniLM" if self.enable_minilm else "Loading rules engine",
                36,
            )
            engine = self.engine or TriageEngine(enable_embeddings=self.enable_minilm)
            if self.enable_minilm and not engine.embeddings_active:
                self._event("status", "MiniLM unavailable; using rules", 37)

            jobs: list[SmartAdvisorJob] = []
            for index, email in enumerate(emails, start=1):
                control.checkpoint()
                try:
                    result = classify_email(
                        email.body,
                        email.subject,
                        engine=engine,
                        message_key=email.message_id,
                    )
                    summary.classified += 1
                    mapped = jobs_from_result(result, email.message_id)
                    if not mapped:
                        summary.skipped += 1
                    jobs.extend(mapped)
                except Exception:
                    summary.nlp_errors += 1
                    summary.skipped += 1
                self._event(
                    "progress",
                    f"Classified email {index} of {len(emails)}",
                    35 + (index / max(len(emails), 1)) * 15,
                )

            jobs = deduplicate_jobs(jobs)
            summary.jobs_created = len(jobs)
            self._event("summary", summary.display(), 50, summary.to_dict())

            if not jobs:
                self._event("complete", "No eligible SmartAdvisor jobs", 100, summary.to_dict())
                return summary

            for index, job in enumerate(jobs):
                job_start = 50 + (index / len(jobs)) * 50
                job_span = 50 / len(jobs)
                while True:
                    control.checkpoint()

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
                            "7.4": 0.82,
                            "7.5": 0.90,
                            "7.6": 0.95,
                            "complete": 1.0,
                        }.get(step, 0.45)
                        self._event("progress", message, job_start + job_span * step_fraction)

                    try:
                        self.helper.run_job(
                            job,
                            control,
                            helper_progress,
                            leave_open=index == len(jobs) - 1,
                        )
                        summary.jobs_completed += 1
                        self._event(
                            "summary",
                            summary.display(),
                            job_start + job_span,
                            summary.to_dict(),
                        )
                        break
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

            self._event("complete", "Workflow complete", 100, summary.to_dict())
            return summary
        except RunCancelled:
            self._event("status", "Run cancelled", self._progress, summary.to_dict())
            return summary
        finally:
            self.extractor.close()
            self.helper.close()
