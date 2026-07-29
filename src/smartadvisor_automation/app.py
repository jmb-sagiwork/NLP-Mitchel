from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from smartadvisor_automation.driver import SmartAdvisorDriver
from smartadvisor_automation.errors import AutomationError, WorkflowCancelled
from smartadvisor_automation.models import WorkflowResult
from smartadvisor_automation.probe import scan_controls
from smartadvisor_automation.workflow import (
    NoBillOnFileWorkflow,
    normalize_dos,
    validate_claim_id,
    validate_expected_amount,
)

# The log records charge amounts alongside selector metadata and step
# outcomes, by decision -- masking them to shapes hid whether a mismatch was a
# different value or the wrong control. A saved log is therefore sensitive.
# Claim ids, dates and patient accounts are still never logged. The redacted
# JSON diagnostics written by DiagnosticTrace stay value-free.
MAX_LOG_LINES = 2000


class AutomationApp:
    """Tkinter front end for the attended No Bill on File workflow."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Automation")
        self.root.geometry("760x860")
        self.root.minsize(680, 640)

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False

        self.claim_id = tk.StringVar()
        self.dos_from = tk.StringVar()
        self.expected_amount = tk.StringVar()
        self.patient_account = tk.StringVar()
        self.amount = tk.StringVar()
        self.matched_row = tk.StringVar()
        self.diagnose_amounts = tk.BooleanVar(value=False)
        self.status = tk.StringVar(
            value="Open and sign in to SmartAdvisor before running."
        )

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(
            container,
            text="No Bill on File",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(
            container,
            text=(
                "Attended workflow — SmartAdvisor must already be open "
                "and authenticated."
            ),
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(4, 18),
        )

        ttk.Label(container, text="Claim ID").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12), pady=6
        )
        self.claim_entry = ttk.Entry(
            container, textvariable=self.claim_id, width=36
        )
        self.claim_entry.grid(row=2, column=1, sticky=tk.EW, pady=6)

        ttk.Label(container, text="DOS From").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 12), pady=6
        )
        self.dos_entry = ttk.Entry(
            container, textvariable=self.dos_from, width=36
        )
        self.dos_entry.grid(row=3, column=1, sticky=tk.EW, pady=6)
        ttk.Label(
            container,
            text="MM/DD/YYYY",
            foreground="#666666",
        ).grid(row=4, column=1, sticky=tk.W)

        ttk.Label(container, text="Expected Amount").grid(
            row=5, column=0, sticky=tk.W, padx=(0, 12), pady=6
        )
        self.amount_entry = ttk.Entry(
            container, textvariable=self.expected_amount, width=36
        )
        self.amount_entry.grid(row=5, column=1, sticky=tk.EW, pady=6)
        ttk.Label(
            container,
            text="Charge amount to match, e.g. 1,952.43",
            foreground="#666666",
        ).grid(row=6, column=1, sticky=tk.W)

        actions = ttk.Frame(container)
        actions.grid(
            row=7,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(16, 16),
        )

        self.run_button = ttk.Button(
            actions, text="Run workflow", command=self._start_workflow
        )
        self.run_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(
            actions,
            text="Cancel",
            command=self._cancel_workflow,
            state=tk.DISABLED,
        )
        self.cancel_button.pack(side=tk.LEFT, padx=(8, 0))

        self.validate_button = ttk.Button(
            actions,
            text="Validate controls",
            command=self._start_validation,
        )
        self.validate_button.pack(side=tk.LEFT, padx=(8, 0))

        # On its own row: sharing the button row clipped it off-screen at the
        # default window width. Off by default because the scan touches every
        # element in the bill window at Citrix COM latency.
        self.diagnose_check = ttk.Checkbutton(
            container,
            text="Diagnose totals fields (slow)",
            variable=self.diagnose_amounts,
        )
        self.diagnose_check.grid(
            row=8, column=0, columnspan=2, sticky=tk.W, pady=(0, 12)
        )

        result_box = ttk.LabelFrame(container, text="Result", padding=12)
        result_box.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 12),
        )
        result_box.columnconfigure(1, weight=1)
        container.rowconfigure(9, weight=1)

        ttk.Label(result_box, text="Patient Account").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 12), pady=5
        )
        ttk.Entry(
            result_box,
            textvariable=self.patient_account,
            state="readonly",
        ).grid(row=0, column=1, sticky=tk.EW, pady=5)

        ttk.Label(result_box, text="Amount").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 12), pady=5
        )
        ttk.Entry(
            result_box,
            textvariable=self.amount,
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, pady=5)

        ttk.Label(result_box, text="Matched row").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12), pady=5
        )
        ttk.Entry(
            result_box,
            textvariable=self.matched_row,
            state="readonly",
        ).grid(row=2, column=1, sticky=tk.EW, pady=5)

        ttk.Label(result_box, text="Outcome").grid(
            row=3, column=0, sticky=tk.NW, padx=(0, 12), pady=5
        )
        self.outcome = tk.Text(
            result_box,
            height=5,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.outcome.grid(row=3, column=1, sticky="nsew", pady=5)
        result_box.rowconfigure(3, weight=1)

        result_actions = ttk.Frame(result_box)
        result_actions.grid(row=4, column=1, sticky=tk.W, pady=(8, 0))
        self.copy_button = ttk.Button(
            result_actions,
            text="Copy result",
            command=self._copy_result,
            state=tk.DISABLED,
        )
        self.copy_button.pack(side=tk.LEFT)
        ttk.Button(
            result_actions,
            text="Clear",
            command=self._clear_result,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._build_log_panel(container, row=10)

        ttk.Separator(container).grid(
            row=11, column=0, columnspan=2, sticky=tk.EW
        )
        ttk.Label(
            container,
            textvariable=self.status,
            anchor=tk.W,
        ).grid(
            row=12,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(10, 0),
        )

        self.claim_entry.focus_set()

    def _build_log_panel(self, container: ttk.Frame, *, row: int) -> None:
        """Scrolling step-by-step log for diagnosing a failed run."""

        log_box = ttk.LabelFrame(container, text="Log", padding=12)
        log_box.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 12),
        )
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        container.rowconfigure(row, weight=2)

        self.log_text = tk.Text(
            log_box,
            height=14,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            log_box,
            orient=tk.VERTICAL,
            command=self.log_text.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        log_actions = ttk.Frame(log_box)
        log_actions.grid(row=1, column=0, columnspan=2, sticky=tk.W,
                         pady=(8, 0))
        ttk.Button(
            log_actions,
            text="Copy log",
            command=self._copy_log,
        ).pack(side=tk.LEFT)
        ttk.Button(
            log_actions,
            text="Save log",
            command=self._save_log,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            log_actions,
            text="Clear log",
            command=self._clear_log,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            log_actions,
            text="Contains amount values — do not share outside SmartAdvisor.",
            foreground="#a03030",
        ).pack(side=tk.LEFT, padx=(12, 0))

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{stamp}] {message}\n")

        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            trim = line_count - MAX_LOG_LINES
            self.log_text.delete("1.0", f"{trim + 1}.0")

        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _copy_log(self) -> None:
        contents = self.log_text.get("1.0", tk.END).strip()
        if not contents:
            self.status.set("The log is empty.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(contents)
        self.status.set("Log copied to the clipboard.")

    def _save_log(self) -> None:
        contents = self.log_text.get("1.0", tk.END).strip()
        if not contents:
            self.status.set("The log is empty.")
            return

        directory = self._diagnostics_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = directory / f"run-log-{stamp}.txt"
            path.write_text(
                "SmartAdvisor Automation run log\n"
                "WARNING: contains charge amount values. Treat as "
                "sensitive and do not share outside SmartAdvisor.\n\n"
                + contents
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            self.status.set(f"Could not save the log: {type(exc).__name__}")
            return
        self.status.set(f"Log saved to {path}")

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _start_workflow(self) -> None:
        if self.running:
            return

        try:
            claim_id = validate_claim_id(self.claim_id.get())
            dos_from = normalize_dos(self.dos_from.get())
            expected_amount = validate_expected_amount(
                self.expected_amount.get()
            )
        except ValueError as exc:
            messagebox.showerror(
                "Invalid input",
                str(exc),
                parent=self.root,
            )
            return

        self._clear_result()
        self.cancel_event.clear()
        self._set_running(True)
        self.status.set("Starting workflow...")
        self._append_log("=" * 52)
        self._append_log("workflow started")

        worker = threading.Thread(
            target=self._workflow_worker,
            args=(claim_id, dos_from, expected_amount),
            daemon=True,
        )
        worker.start()

    def _workflow_worker(
        self,
        claim_id: str,
        dos_from: str,
        expected_amount: str,
    ) -> None:
        driver = SmartAdvisorDriver(
            log=lambda message: self.events.put(("log", message)),
        )
        workflow = NoBillOnFileWorkflow(
            driver,
            cancel_event=self.cancel_event,
            progress=lambda step, message: self.events.put(
                ("progress", (step, message))
            ),
            log=lambda message: self.events.put(("log", message)),
            diagnose_amounts=self.diagnose_amounts.get(),
        )

        try:
            result = workflow.run(claim_id, dos_from, expected_amount)
        except WorkflowCancelled:
            self.events.put(("cancelled", None))
        except AutomationError as exc:
            self.events.put(
                ("automation_error", (exc.code, exc.step, exc.diagnostics))
            )
        except Exception as exc:
            self.events.put(("unexpected_error", type(exc).__name__))
        else:
            self.events.put(("complete", result))

    def _cancel_workflow(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.status.set("Cancellation requested; waiting for the current step.")
        self._append_log("cancellation requested")

    def _start_validation(self) -> None:
        if self.running:
            return
        self._set_running(True, allow_cancel=False)
        self.status.set("Validating known selectors without clicking...")
        self._append_log("selector validation started")
        threading.Thread(
            target=self._validation_worker,
            daemon=True,
        ).start()

    def _validation_worker(self) -> None:
        try:
            report = scan_controls()
        except Exception as exc:
            self.events.put(("unexpected_error", type(exc).__name__))
        else:
            self.events.put(("validation_complete", report))

    def _poll_events(self) -> None:
        while True:
            try:
                event_name, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event_name == "progress":
                step, message = payload
                self.status.set(f"Step {step}: {message}")
                self._append_log(f"step {step}: {message}")
            elif event_name == "log":
                self._append_log(str(payload))
            elif event_name == "complete" and isinstance(
                payload, WorkflowResult
            ):
                self._workflow_complete(payload)
            elif event_name == "cancelled":
                self._set_running(False)
                self.status.set("Workflow cancelled safely.")
                self._append_log("workflow cancelled")
            elif event_name == "automation_error":
                code, step, diagnostics = payload
                self._automation_failed(code, step, diagnostics)
            elif event_name == "unexpected_error":
                self._unexpected_failed(str(payload))
            elif event_name == "validation_complete":
                self._validation_complete(payload)

        self.root.after(100, self._poll_events)

    def _workflow_complete(self, result: WorkflowResult) -> None:
        self.patient_account.set(result.patient_account or "")
        self.amount.set(result.amount)
        self.matched_row.set(
            f"row {result.row_index + 1} of {result.rows_examined} checked"
        )
        self._set_outcome(result.outcome)
        self.copy_button.configure(state=tk.NORMAL)
        self._set_running(False)
        self.status.set("Workflow complete.")
        self._append_log(
            f"workflow complete on row {result.row_index}; "
            f"{result.rows_examined} row(s) opened"
        )

    def _automation_failed(
        self,
        code: str,
        step: str | None,
        diagnostics: dict[str, object] | None,
    ) -> None:
        self._set_running(False)
        location = f" at step {step}" if step else ""
        self.status.set(f"Workflow stopped safely{location}: {code}")
        self._append_log(f"stopped{location}: {code}")

        trace_path = (
            self._save_diagnostics(diagnostics) if diagnostics else None
        )
        trace_line = (
            f"\n\nDiagnostic trace saved to:\n{trace_path}"
            if trace_path is not None
            else ""
        )
        messagebox.showerror(
            "Automation stopped",
            (
                f"The workflow stopped safely{location}.\n\n"
                f"Reason: {code}\n\n"
                "The Log panel shows the step-by-step trace, including "
                "the amounts compared."
                f"{trace_line}"
            ),
            parent=self.root,
        )

    @staticmethod
    def _diagnostics_directory() -> Path:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "SmartAdvisorAutomation" / "diagnostics"

    @classmethod
    def _save_diagnostics(
        cls, diagnostics: dict[str, object]
    ) -> Path | None:
        """Write the redacted attach trace next to the executable's data dir."""

        directory = cls._diagnostics_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "latest-attach-trace.json"
            path.write_text(
                json.dumps(diagnostics, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            return None
        return path

    def _unexpected_failed(self, error_code: str) -> None:
        self._set_running(False)
        self.status.set(f"Workflow stopped safely: {error_code}")
        self._append_log(f"unexpected failure: {error_code}")
        messagebox.showerror(
            "Automation stopped",
            f"The workflow stopped safely ({error_code}).",
            parent=self.root,
        )

    def _validation_complete(self, report: dict[str, object]) -> None:
        found = 0
        checked = 0
        for backend_result in report.get("backend_results", []):
            if not isinstance(backend_result, dict):
                continue
            controls = backend_result.get("controls", [])
            if not isinstance(controls, list):
                continue
            for control in controls:
                if not isinstance(control, dict):
                    continue
                checked += 1
                if control.get("status") == "found":
                    found += 1
                    continue
                selector = (
                    control.get("automation_id")
                    or control.get("selector_name")
                    or "?"
                )
                self._append_log(
                    f"validation {control.get('step')} {selector} "
                    f"-> {control.get('status')}"
                )

        self._set_running(False)
        self.status.set(
            f"Validation complete: {found} unique matches across "
            f"{checked} backend checks."
        )
        self._append_log(
            f"validation complete: {found}/{checked} matched"
        )

    def _set_running(
        self,
        running: bool,
        *,
        allow_cancel: bool = True,
    ) -> None:
        self.running = running
        entry_state = tk.DISABLED if running else tk.NORMAL
        button_state = tk.DISABLED if running else tk.NORMAL
        self.claim_entry.configure(state=entry_state)
        self.dos_entry.configure(state=entry_state)
        self.amount_entry.configure(state=entry_state)
        self.run_button.configure(state=button_state)
        self.validate_button.configure(state=button_state)
        self.diagnose_check.configure(state=button_state)
        self.cancel_button.configure(
            state=tk.NORMAL if running and allow_cancel else tk.DISABLED
        )

    def _set_outcome(self, value: str) -> None:
        self.outcome.configure(state=tk.NORMAL)
        self.outcome.delete("1.0", tk.END)
        self.outcome.insert("1.0", value)
        self.outcome.configure(state=tk.DISABLED)

    def _clear_result(self) -> None:
        self.patient_account.set("")
        self.amount.set("")
        self.matched_row.set("")
        self._set_outcome("")
        self.copy_button.configure(state=tk.DISABLED)

    def _copy_result(self) -> None:
        result = (
            f"Patient Account: {self.patient_account.get()}\n"
            f"Amount: {self.amount.get()}\n"
            f"Matched row: {self.matched_row.get()}\n"
            f"Outcome: {self.outcome.get('1.0', tk.END).strip()}"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        self.status.set("Result copied to the clipboard.")


def main() -> None:
    root = tk.Tk()
    AutomationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
