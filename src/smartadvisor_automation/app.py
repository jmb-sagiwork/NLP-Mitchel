from __future__ import annotations

import queue
import threading
import tkinter as tk
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
)


class AutomationApp:
    """Tkinter front end for the attended No Bill on File workflow."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Automation")
        self.root.geometry("720x620")
        self.root.minsize(640, 560)

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False

        self.claim_id = tk.StringVar()
        self.dos_from = tk.StringVar()
        self.patient_account = tk.StringVar()
        self.amount = tk.StringVar()
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

        actions = ttk.Frame(container)
        actions.grid(
            row=5,
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

        result_box = ttk.LabelFrame(container, text="Result", padding=12)
        result_box.grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 12),
        )
        result_box.columnconfigure(1, weight=1)
        container.rowconfigure(6, weight=1)

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

        ttk.Label(result_box, text="Outcome").grid(
            row=2, column=0, sticky=tk.NW, padx=(0, 12), pady=5
        )
        self.outcome = tk.Text(
            result_box,
            height=6,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.outcome.grid(row=2, column=1, sticky="nsew", pady=5)
        result_box.rowconfigure(2, weight=1)

        result_actions = ttk.Frame(result_box)
        result_actions.grid(row=3, column=1, sticky=tk.W, pady=(8, 0))
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

        ttk.Separator(container).grid(
            row=7, column=0, columnspan=2, sticky=tk.EW
        )
        ttk.Label(
            container,
            textvariable=self.status,
            anchor=tk.W,
        ).grid(
            row=8,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(10, 0),
        )

        self.claim_entry.focus_set()

    def _start_workflow(self) -> None:
        if self.running:
            return

        try:
            claim_id = validate_claim_id(self.claim_id.get())
            dos_from = normalize_dos(self.dos_from.get())
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

        worker = threading.Thread(
            target=self._workflow_worker,
            args=(claim_id, dos_from),
            daemon=True,
        )
        worker.start()

    def _workflow_worker(self, claim_id: str, dos_from: str) -> None:
        driver = SmartAdvisorDriver()
        workflow = NoBillOnFileWorkflow(
            driver,
            cancel_event=self.cancel_event,
            progress=lambda step, message: self.events.put(
                ("progress", (step, message))
            ),
        )

        try:
            result = workflow.run(claim_id, dos_from)
        except WorkflowCancelled:
            self.events.put(("cancelled", None))
        except AutomationError as exc:
            self.events.put(
                ("automation_error", (exc.code, exc.step))
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

    def _start_validation(self) -> None:
        if self.running:
            return
        self._set_running(True, allow_cancel=False)
        self.status.set("Validating known selectors without clicking...")
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
            elif event_name == "complete" and isinstance(
                payload, WorkflowResult
            ):
                self._workflow_complete(payload)
            elif event_name == "cancelled":
                self._set_running(False)
                self.status.set("Workflow cancelled safely.")
            elif event_name == "automation_error":
                code, step = payload
                self._automation_failed(code, step)
            elif event_name == "unexpected_error":
                self._unexpected_failed(str(payload))
            elif event_name == "validation_complete":
                self._validation_complete(payload)

        self.root.after(100, self._poll_events)

    def _workflow_complete(self, result: WorkflowResult) -> None:
        self.patient_account.set(result.patient_account)
        self.amount.set(result.amount)
        self._set_outcome(result.outcome)
        self.copy_button.configure(state=tk.NORMAL)
        self._set_running(False)
        self.status.set("Workflow complete.")

    def _automation_failed(
        self, code: str, step: str | None
    ) -> None:
        self._set_running(False)
        location = f" at step {step}" if step else ""
        self.status.set(f"Workflow stopped safely{location}: {code}")
        messagebox.showerror(
            "Automation stopped",
            (
                f"The workflow stopped safely{location}.\n\n"
                f"Reason: {code}\n\n"
                "No input or extracted values were written to logs."
            ),
            parent=self.root,
        )

    def _unexpected_failed(self, error_code: str) -> None:
        self._set_running(False)
        self.status.set(f"Workflow stopped safely: {error_code}")
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

        self._set_running(False)
        self.status.set(
            f"Validation complete: {found} unique matches across "
            f"{checked} backend checks."
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
        self.run_button.configure(state=button_state)
        self.validate_button.configure(state=button_state)
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
        self._set_outcome("")
        self.copy_button.configure(state=tk.DISABLED)

    def _copy_result(self) -> None:
        result = (
            f"Patient Account: {self.patient_account.get()}\n"
            f"Amount: {self.amount.get()}\n"
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

