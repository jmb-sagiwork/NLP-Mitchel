from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from incontact_automation import IncontactExtractor
from salesforce_automation import SalesforceLookup

from mitchel_qt.widgets import StatusDot

from . import branding, dialogs, theme
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


def _dim_label(text: str, fonts: theme.Fonts) -> QLabel:
    label = QLabel(text)
    theme.set_class(label, "dim")
    label.setFont(fonts.small)
    return label


class MitchelApp(QWidget):
    POLL_MS = 75

    dialog_requested = Signal(str, str, object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mitchel NLP")
        self.resize(500, 330)
        self.setMinimumSize(450, 330)
        self.setMaximumHeight(330)
        try:
            if branding.ICON_PATH.is_file():
                self.setWindowIcon(QIcon(str(branding.ICON_PATH)))
        except OSError:
            pass
        self.fonts = theme.apply_theme(QApplication.instance())

        self.events: queue.Queue[PipelineEvent] = queue.Queue()
        self.control: RunControl | None = None
        self.worker: threading.Thread | None = None
        self.extractor: IncontactExtractor | None = None
        self.salesforce: SalesforceLookup | None = None
        self.closing = False
        self.dialog_events: list[threading.Event] = []
        self.dialog_requested.connect(self._show_dialog_now)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- header --------------------------------------------------
        header = QFrame(self)
        theme.set_class(header, "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)
        if branding.LOGO_PATH.is_file():
            pixmap = QPixmap(str(branding.LOGO_PATH))
            if not pixmap.isNull():
                logo_label = QLabel(header)
                logo_label.setPixmap(
                    pixmap.scaledToHeight(24, Qt.SmoothTransformation)
                )
                header_layout.addWidget(logo_label)
        title_label = QLabel("Mitchel NLP", header)
        title_label.setFont(self.fonts.title)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        root_layout.addWidget(header)

        # ---- body ------------------------------------------------------
        body = QFrame(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(0)
        root_layout.addWidget(body, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = StatusDot(body)
        status_row.addWidget(self.status_dot)
        self.status_label = QLabel("Ready", body)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        body_layout.addLayout(status_row)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 8, 0, 4)
        self.progress_bar = QProgressBar(body)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        progress_row.addWidget(self.progress_bar, 1)
        self.percent_label = QLabel("0%", body)
        self.percent_label.setFixedWidth(36)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_row.addWidget(self.percent_label)
        body_layout.addLayout(progress_row)

        self.summary_label = _dim_label("Emails 0  |  Jobs 0/0  |  Skipped 0", self.fonts)
        body_layout.addWidget(self.summary_label)
        body_layout.addSpacing(7)

        # ---- options -----------------------------------------------------
        self.minilm_check = QCheckBox("Use MiniLM", body)
        self.minilm_check.setChecked(True)
        body_layout.addWidget(self.minilm_check)

        self.extracted_check = QCheckBox("Show extracted email", body)
        self.extracted_check.setChecked(True)
        self.extracted_check.toggled.connect(self._sync_popup_options)
        body_layout.addWidget(self.extracted_check)

        self.nlp_check = QCheckBox("Show NLP output", body)
        self.nlp_check.setChecked(True)
        self.nlp_check.toggled.connect(self._sync_popup_options)
        body_layout.addWidget(self.nlp_check)

        skip_row = QHBoxLayout()
        skip_row.setContentsMargins(0, 4, 0, 0)
        skip_row.addWidget(QLabel("Skip first N emails:", body))
        self.skip_count_box = QComboBox(body)
        self.skip_count_box.addItems(["0", "1", "2", "3"])
        self.skip_count_box.setFixedWidth(56)
        skip_row.addWidget(self.skip_count_box)
        skip_row.addStretch(1)
        body_layout.addLayout(skip_row)

        body_layout.addStretch(1)

        # ---- controls ------------------------------------------------
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 8, 0, 0)
        controls.addStretch(1)
        self.start_button = QPushButton("Start", body)
        theme.set_class(self.start_button, "accent")
        self.start_button.clicked.connect(self._start)
        controls.addWidget(self.start_button)
        self.pause_button = QPushButton("Pause", body)
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        controls.addWidget(self.pause_button)
        body_layout.addLayout(controls)

        self.extracted_popup_enabled = threading.Event()
        self.extracted_popup_enabled.set()
        self.nlp_popup_enabled = threading.Event()
        self.nlp_popup_enabled.set()

        self._set_run_state("idle")

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(self.POLL_MS)

    def _set_run_state(self, state: str) -> None:
        colors = {
            "idle": theme.TEXT_FAINT,
            "running": theme.ACCENT,
            "paused": theme.WARNING,
            "error": theme.DANGER,
        }
        self.status_dot.set_color(colors[state])

    def _manual_login_gate(self) -> None:
        self._blocking_messagebox(
            "NICE CXone login",
            "Complete the NICE CXone login in Chrome.\n\n"
            "When the page is fully ready, click OK to continue.",
        )

    def _manual_salesforce_login_gate(self) -> None:
        self._blocking_messagebox(
            "Salesforce login",
            "Complete the Salesforce login in Chrome.\n\n"
            "When Salesforce Home is fully ready, click OK to continue.",
        )

    def _blocking_messagebox(self, title: str, message: str) -> None:
        """Show a dialog from the worker thread and wait before continuing."""

        complete = threading.Event()
        self.dialog_events.append(complete)
        self.dialog_requested.emit(title, message, complete)
        while not complete.wait(0.1):
            if self.control is None or self.control.cancelled:
                return

    def _show_dialog_now(self, title: str, message: str, complete: threading.Event) -> None:
        if self.closing:
            complete.set()
            return
        try:
            dialogs.show_message(self, title, message)
        finally:
            complete.set()

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

    def _show_layers(self, layers_used: tuple[str, ...]) -> None:
        names = {
            "embeddings": "MiniLM (embeddings)",
            "structural": "Structural (required-field presence)",
            "rules": "Rules (keyword matching)",
        }
        lines = [f"{len(layers_used)} of 3 layers are active for this run:", ""]
        for layer in ("embeddings", "structural", "rules"):
            mark = "ON " if layer in layers_used else "OFF"
            lines.append(f"[{mark}] {names[layer]}")
        if "embeddings" not in layers_used:
            lines.append("")
            lines.append(
                "MiniLM is not active. Either 'Use MiniLM' was unchecked, or the "
                "model files could not be loaded, so results are rules-only and "
                "confidence is capped."
            )
        self._blocking_messagebox("NLP layers for this run", "\n".join(lines))

    def _sync_popup_options(self) -> None:
        if self.extracted_check.isChecked():
            self.extracted_popup_enabled.set()
        else:
            self.extracted_popup_enabled.clear()
        if self.nlp_check.isChecked():
            self.nlp_popup_enabled.set()
        else:
            self.nlp_popup_enabled.clear()

    def _start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        self.control = RunControl()
        self.progress_bar.setValue(0)
        self.percent_label.setText("0%")
        self.status_label.setText("Starting")
        self._set_run_state("running")
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.setText("Pause")
        self.minilm_check.setEnabled(False)
        self.skip_count_box.setEnabled(False)
        self.extractor = IncontactExtractor(login_gate=self._manual_login_gate)
        self.salesforce = SalesforceLookup(login_gate=self._manual_salesforce_login_gate)
        orchestrator = PipelineOrchestrator(
            self.extractor,
            enable_minilm=self.minilm_check.isChecked(),
            salesforce=self.salesforce,
            emit=self.events.put,
            on_extracted=self._show_extracted,
            on_nlp=self._show_nlp,
            on_reply=self._show_reply,
            on_layers=self._show_layers,
            skip_count=int(self.skip_count_box.currentText() or 0),
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
            self.pause_button.setText("Pause")
            self.status_label.setText("Resuming")
            self._set_run_state("running")
        else:
            self.control.pause()
            self.pause_button.setText("Resume")
            self.status_label.setText("Pausing after current action")
            self._set_run_state("paused")

    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event.message == "__worker_stopped__":
                    self._run_stopped()
                    continue
                self.progress_bar.setValue(round(event.progress))
                self.percent_label.setText(f"{round(event.progress)}%")
                if event.kind == "summary":
                    self.summary_label.setText(event.message)
                else:
                    self.status_label.setText(event.message)
                if event.kind == "error":
                    self._set_run_state("error")
                    if self.control is not None and self.control.paused:
                        self.pause_button.setText("Resume")
        except queue.Empty:
            pass
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.close()

    def _run_stopped(self) -> None:
        self._set_run_state("idle")
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Pause")
        self.start_button.setEnabled(True)
        self.minilm_check.setEnabled(True)
        self.skip_count_box.setEnabled(True)
        self.control = None
        self.extractor = None
        self.salesforce = None

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.worker is None or not self.worker.is_alive():
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        self.closing = True
        self.status_label.setText("Closing safely after current action")
        if self.control is not None:
            self.control.cancel()
        for dialog_event in self.dialog_events:
            dialog_event.set()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MitchelApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
