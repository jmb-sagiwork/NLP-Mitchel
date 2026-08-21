from __future__ import annotations

import json
import sys
import threading
from typing import Any

from smartadvisor_automation.driver import SmartAdvisorDriver
from smartadvisor_automation.errors import AutomationError, WorkflowCancelled
from smartadvisor_automation.workflow import NoBillOnFileWorkflow

from .models import SmartAdvisorJob
from .run_control import RunControl, WorkflowCancelAdapter


class HelperServer:
    def __init__(self) -> None:
        self._write_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._control: RunControl | None = None
        self._stopping = False

    def send(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def run_job(self, job: SmartAdvisorJob, leave_open: bool) -> None:
        control = RunControl()
        self._control = control
        terminal: dict[str, Any]

        def progress(step: str, message: str) -> None:
            self.send({"type": "progress", "step": step, "message": message})

        try:
            driver = SmartAdvisorDriver()
            workflow = NoBillOnFileWorkflow(
                driver,
                cancel_event=WorkflowCancelAdapter(control),
                progress=progress,
            )
            result = workflow.run(
                job.claim_id,
                job.dos_from,
                job.expected_amount,
                job.provider_tin,
                job.patient_account,
                leave_match_open=leave_open,
            )
            terminal = {
                "type": "result",
                "result": result.to_dict(),
            }
        except AutomationError as exc:
            terminal = {"type": "error", "code": exc.code, "step": exc.step}
        except WorkflowCancelled:
            terminal = {"type": "cancelled"}
        except Exception as exc:
            terminal = {"type": "error", "code": type(exc).__name__, "step": None}
        finally:
            self._control = None
            self._worker = None
        self.send(terminal)

    def handle(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "run":
            if self._worker is not None and self._worker.is_alive():
                self.send({"type": "error", "code": "helper_busy", "step": None})
                return
            job = SmartAdvisorJob.from_dict(dict(message.get("job") or {}))
            self._worker = threading.Thread(
                target=self.run_job,
                args=(job, bool(message.get("leave_open", True))),
                daemon=False,
            )
            self._worker.start()
        elif message_type == "pause" and self._control is not None:
            self._control.pause()
        elif message_type == "resume" and self._control is not None:
            self._control.resume()
        elif message_type == "cancel" and self._control is not None:
            self._control.cancel()
        elif message_type == "quit":
            self._stopping = True
            if self._control is not None:
                self._control.cancel()

    def serve(self) -> int:
        self.send({"type": "ready", "protocol": 1})
        for raw_line in sys.stdin:
            try:
                message = json.loads(raw_line)
                if not isinstance(message, dict):
                    raise ValueError("message_not_object")
                self.handle(message)
            except Exception as exc:
                self.send({"type": "error", "code": type(exc).__name__, "step": "protocol"})
            if self._stopping:
                break
        if self._worker is not None:
            self._worker.join(timeout=10)
        return 0


def main() -> int:
    return HelperServer().serve()


if __name__ == "__main__":
    raise SystemExit(main())
