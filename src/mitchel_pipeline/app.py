from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk

from incontact_automation import IncontactExtractor

from .models import ExtractedEmail, PipelineEvent
from .orchestrator import PipelineOrchestrator
from .run_control import RunControl


_NLP_STATUS_LABELS = {
    "CLASSIFIED": "Classified",
    "AMBIGUOUS": "Needs review",
    "UNCLASSIFIED": "Not classified",
    "ERROR": "Error",
}

_NLP_FIELD_LABELS = {
    "claim_id": "Claim number",
    "date_of_service": "Date of service",
    "expected_amount": "Billed amount",
    "patient_account": "Patient account",
    "provider_tin": "Provider TIN",
    "date_of_injury": "Date of injury",
    "date_of_birth": "Date of birth",
}


def _friendly_nlp_value(field_name: str, value: object) -> str:
    text = str(value).strip()
    if field_name == "expected_amount":
        try:
            return f"${Decimal(text):,.2f}"
        except (InvalidOperation, ValueError):
            return text
    if field_name.startswith("date_"):
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%m/%d/%Y")
        except ValueError:
            return text
    return text


def format_nlp_output(result: dict[str, object]) -> str:
    """Render the NLP callback as an operator-friendly summary, never JSON."""

    status = str(result.get("status") or "").upper()
    if status == "ERROR":
        error_code = str(result.get("error_code") or "Unknown error")
        return (
            "The email could not be analyzed.\n\n"
            "Status: Error\n"
            "Manual review required: Yes\n"
            f"Error: {error_code}"
        )

    lines = [
        "Email analysis complete",
        "",
        f"Concern: {result.get('display_name') or 'Not identified'}",
        f"Status: {_NLP_STATUS_LABELS.get(status, status.title() or 'Unknown')}",
    ]
    confidence = result.get("confidence")
    if isinstance(confidence, (int, float)):
        lines.append(f"Confidence: {confidence:.0%}")
    lines.append(
        "Manual review required: "
        + ("Yes" if bool(result.get("needs_review")) else "No")
    )
    reason = result.get("reason_display_name")
    if reason:
        lines.append(f"Reason: {reason}")

    extracted: list[str] = []
    field_labels: dict[str, str] = {}
    fields = result.get("fields")
    if isinstance(fields, dict):
        for field_name, raw_field in fields.items():
            name = str(field_name)
            if not isinstance(raw_field, dict):
                continue
            label = str(
                raw_field.get("display_name")
                or _NLP_FIELD_LABELS.get(name)
                or name.replace("_", " ").title()
            )
            field_labels[name] = label
            raw_values = raw_field.get("values")
            values = (
                list(raw_values)
                if isinstance(raw_values, (list, tuple))
                else []
            )
            if not values and raw_field.get("value") not in (None, ""):
                values = [raw_field["value"]]
            clean_values = [
                _friendly_nlp_value(name, value)
                for value in values
                if value not in (None, "")
            ]
            if clean_values:
                extracted.append(f"{label}: {', '.join(clean_values)}")

    lines.extend(["", "Extracted information:"])
    lines.extend(extracted or ["No information was extracted."])

    missing = result.get("missing_fields")
    if isinstance(missing, (list, tuple)) and missing:
        labels = [
            field_labels.get(str(name), _NLP_FIELD_LABELS.get(str(name), str(name)))
            for name in missing
        ]
        lines.extend(["", f"Missing required information: {', '.join(labels)}"])

    ambiguous = result.get("ambiguous_fields")
    if isinstance(ambiguous, (list, tuple)) and ambiguous:
        labels = [
            field_labels.get(str(name), _NLP_FIELD_LABELS.get(str(name), str(name)))
            for name in ambiguous
        ]
        lines.extend(["", f"Please verify: {', '.join(labels)}"])

    return "\n".join(lines)


class MitchelApp:
    POLL_MS = 75

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Mitchel NLP")
        self.root.geometry("500x250")
        self.root.minsize(450, 235)
        self.root.resizable(True, False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.events: queue.Queue[PipelineEvent] = queue.Queue()
        self.control: RunControl | None = None
        self.worker: threading.Thread | None = None
        self.extractor: IncontactExtractor | None = None
        self.closing = False
        self.dialog_events: list[threading.Event] = []

        self.status = tk.StringVar(value="Ready")
        self.summary = tk.StringVar(value="Emails 0  |  Jobs 0/0  |  Skipped 0")
        self.progress = tk.DoubleVar(value=0)
        self.percent = tk.StringVar(value="0%")
        self.use_minilm = tk.BooleanVar(value=True)
        self.show_extracted_email = tk.BooleanVar(value=True)
        self.show_nlp_output = tk.BooleanVar(value=True)
        self.extracted_popup_enabled = threading.Event()
        self.extracted_popup_enabled.set()
        self.nlp_popup_enabled = threading.Event()
        self.nlp_popup_enabled.set()

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, textvariable=self.status).pack(anchor="w")
        progress_row = ttk.Frame(frame)
        progress_row.pack(fill="x", pady=(8, 4))
        ttk.Progressbar(progress_row, variable=self.progress, maximum=100).pack(
            side="left", fill="x", expand=True
        )
        ttk.Label(progress_row, textvariable=self.percent, width=5, anchor="e").pack(side="right")
        ttk.Label(frame, textvariable=self.summary).pack(anchor="w", pady=(0, 7))

        options = ttk.Frame(frame)
        options.pack(fill="x")
        self.minilm_check = ttk.Checkbutton(
            options, text="Use MiniLM", variable=self.use_minilm
        )
        self.minilm_check.pack(anchor="w")
        self.extracted_check = ttk.Checkbutton(
            options,
            text="Show extracted email",
            variable=self.show_extracted_email,
            command=self._sync_popup_options,
        )
        self.extracted_check.pack(anchor="w")
        self.nlp_check = ttk.Checkbutton(
            options,
            text="Show NLP output",
            variable=self.show_nlp_output,
            command=self._sync_popup_options,
        )
        self.nlp_check.pack(anchor="w")

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(8, 0))
        self.pause_button = ttk.Button(
            controls, text="Pause", command=self._toggle_pause, state="disabled"
        )
        self.pause_button.pack(side="right")
        self.start_button = ttk.Button(controls, text="Start", command=self._start)
        self.start_button.pack(side="right", padx=(0, 8))
        self.root.after(self.POLL_MS, self._poll)

    def _manual_login_gate(self) -> None:
        self._blocking_messagebox(
            "NICE CXone login",
            "Complete the NICE CXone login in Chrome.\n\n"
            "When the page is fully ready, click OK to continue.",
        )

    def _blocking_messagebox(self, title: str, message: str) -> None:
        """Show a Tk dialog from the worker and wait before continuing."""

        complete = threading.Event()
        self.dialog_events.append(complete)

        def show() -> None:
            if self.closing:
                complete.set()
                return
            try:
                messagebox.showinfo(title, message, parent=self.root)
            finally:
                complete.set()

        self.root.after(0, show)
        while not complete.wait(0.1):
            if self.control is None or self.control.cancelled:
                return

    def _show_extracted(self, email: ExtractedEmail) -> None:
        if not self.extracted_popup_enabled.is_set():
            return
        self._blocking_messagebox(
            "Extracted email",
            f"Subject: {email.subject or '(no subject)'}\n"
            f"Saved: {email.saved_path}\n\n{email.body}",
        )

    def _show_nlp(self, result: dict[str, object]) -> None:
        if not self.nlp_popup_enabled.is_set():
            return
        self._blocking_messagebox(
            "NLP output",
            format_nlp_output(result),
        )

    def _show_reply(self, reply: str) -> None:
        self._blocking_messagebox("Simulated email reply", reply)

    def _sync_popup_options(self) -> None:
        if self.show_extracted_email.get():
            self.extracted_popup_enabled.set()
        else:
            self.extracted_popup_enabled.clear()
        if self.show_nlp_output.get():
            self.nlp_popup_enabled.set()
        else:
            self.nlp_popup_enabled.clear()

    def _start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        self.control = RunControl()
        self.progress.set(0)
        self.percent.set("0%")
        self.status.set("Starting")
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="Pause")
        self.minilm_check.configure(state="disabled")
        self.extractor = IncontactExtractor(login_gate=self._manual_login_gate)
        orchestrator = PipelineOrchestrator(
            self.extractor,
            enable_minilm=self.use_minilm.get(),
            emit=self.events.put,
            on_extracted=self._show_extracted,
            on_nlp=self._show_nlp,
            on_reply=self._show_reply,
        )

        def run() -> None:
            try:
                orchestrator.run(self.control)  # type: ignore[arg-type]
            except Exception as exc:
                self.events.put(
                    PipelineEvent("error", f"Run stopped: {type(exc).__name__}", 0)
                )
            finally:
                self.events.put(PipelineEvent("status", "__worker_stopped__", 0))

        self.worker = threading.Thread(target=run, name="mitchel-pipeline", daemon=True)
        self.worker.start()

    def _toggle_pause(self) -> None:
        if self.control is None:
            return
        if self.control.paused:
            self.control.resume()
            self.pause_button.configure(text="Pause")
            self.status.set("Resuming")
        else:
            self.control.pause()
            self.pause_button.configure(text="Resume")
            self.status.set("Pausing after current action")

    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event.message == "__worker_stopped__":
                    self._run_stopped()
                    continue
                self.progress.set(event.progress)
                self.percent.set(f"{round(event.progress)}%")
                if event.kind == "summary":
                    self.summary.set(event.message)
                else:
                    self.status.set(event.message)
                if event.kind == "error" and self.control is not None and self.control.paused:
                    self.pause_button.configure(text="Resume")
        except queue.Empty:
            pass
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
            return
        self.root.after(self.POLL_MS, self._poll)

    def _run_stopped(self) -> None:
        self.pause_button.configure(state="disabled", text="Pause")
        self.start_button.configure(state="normal")
        self.minilm_check.configure(state="normal")
        self.control = None
        self.extractor = None

    def _close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.status.set("Closing safely after current action")
        if self.control is not None:
            self.control.cancel()
        for dialog_event in self.dialog_events:
            dialog_event.set()
        if self.worker is None or not self.worker.is_alive():
            self.root.destroy()


def main() -> int:
    root = tk.Tk()
    MitchelApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
