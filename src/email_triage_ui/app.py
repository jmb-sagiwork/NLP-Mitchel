"""PySide6 harness for teaching the triage engine.

This is a teaching tool, not the product. Paste a body, see exactly what the
NLP concluded and why, then correct it - every saved row becomes a labelled
training example for the MiniLM prototypes and the keyword rules.

The engine imports nothing from this package. A host application integrates
with `email_triage.classify_email(body, subject)` and never ships this window.
"""

from __future__ import annotations

import queue
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from email_triage.engine import TriageEngine
from email_triage.render import (
    append_training_record,
    build_training_record,
    slugify_label,
    to_explanation_text,
    to_json,
    to_plain_text,
)
from email_triage.textprep import separate_transport_headers
from email_triage.types import TriageResult
from mitchel_qt.dialogs import show_message as show_error_dialog

from . import theme as th
from .paths import DATASET_PATH

# Teach-bar dropdown entries that are not concern ids.
CORRECT = "(prediction is correct)"
NO_REASON = "(no reason stated)"
NEW_CONCERN = "+ new concern..."
NEW_REASON = "+ new reason..."

PLACEHOLDER = (
    "Paste the email body here.\n\n"
    "Example:\n"
    "  Hi team, can you confirm the type of bill for claim WC1234567?\n"
    "  The charge amount is $1,250.00 and the TOB shows 0111.\n"
)

# Synthetic. Every identifier below is invented - never paste real PHI here.
SAMPLES = [
    (
        "All seven fields, fully labelled",
        "Bill status please.\n\n"
        "Claim ID: WC7788991\n"
        "DOS: 05/01/2026\n"
        "DOI: 04/02/2026\n"
        "DOB: 11/30/1979\n"
        "Prov TIN: 98-7654321\n"
        "Patient Account: PA5512399\n"
        "Expected amount: $3,410.55\n",
    ),
    (
        "Multiple bill inquiries - five DOS/amount pairs",
        "Good morning,\n\n"
        "Would you please provide claim status for Claim # ZX8042719-6 "
        "for the following dates of service?\n\n"
        "11/21/2041 billed amount $246.80\n"
        "11/24/2041 billed amount $1,357.90\n"
        "11/27/2041 billed amount $468.20\n"
        "12/01/2041 billed amount $579.30\n"
        "12/04/2041 billed amount $680.40\n\n"
        "Please send a copy of the EOB.\n",
    ),
    (
        "Bill status - completed and denied",
        "Good morning,\n\nThis bill has completed processing and was denied. "
        "Claim number ABC-00456789, date of service 02/02/2026, expected "
        "amount $1,250.00.\n\nRegards,\nBilling Dept\n",
    ),
    (
        "Bill status - not a bill on file",
        "We show not a bill on file for this one. Claim ID 100234567, "
        "DOS 01/15/2026, Prov TIN 12-3456789.\n",
    ),
    (
        "Bill status - no claim on file",
        "No claim on file; missing information. Claim ID WC5551234.\n",
    ),
    (
        "Claim information - claim number request",
        "Claim number request - we need the claim number before we can bill.\n"
        "Patient account ACCT-99213, DOI 01/09/2026, DOB 07/22/1984.\n",
    ),
    (
        "Inbound question, no reason stated",
        "Hi,\n\nChecking the status of the bill for Claim ID WC1234567, "
        "DOS 03/14/2026. Can you advise?\n\nThanks\n",
    ),
    (
        "Unlabelled date - must NOT be guessed",
        "Bill status for claim ID WC1234567. We sent this over on 03/14/2026.\n",
    ),
    (
        "Not a tracked concern",
        "Thanks, received. I'll follow up with the team next week.\n",
    ),
]


def _field_tree_rows(result: TriageResult) -> list[tuple[tuple[str, str, str, str], str]]:
    """Flatten fields into UI rows without discarding repeated inquiries."""
    rows: list[tuple[tuple[str, str, str, str], str]] = []
    for field in result.fields.values():
        if field.value is None:
            tag = "missing" if field.required else "optional_missing"
            rows.append(
                (
                    (field.display_name, "NOT FOUND", "yes" if field.required else "no", "-"),
                    tag,
                )
            )
            continue

        tag = "history" if field.from_history else "found"
        source = f"{field.strategy}  ({field.segment})"
        values = field.all_values
        total = len(values)
        for index, value in enumerate(values, start=1):
            label = (
                field.display_name
                if total == 1
                else f"{field.display_name} ({index}/{total})"
            )
            rows.append(
                ((label, value, "yes" if field.required else "no", source), tag)
            )
    return rows


def _restyle(widget: QWidget) -> None:
    """Re-apply QSS after a dynamic `cssClass` property change on a live widget."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _dim_label(text: str, fonts: th.Fonts) -> QLabel:
    label = QLabel(text)
    th.set_class(label, "dim")
    label.setFont(fonts.small)
    return label


class TriageApp(QWidget):
    TAG_COLORS = {
        "found": th.TEXT,
        "missing": th.DANGER,
        "optional_missing": th.TEXT_FAINT,
        "history": th.WARN,
    }

    def __init__(self) -> None:
        super().__init__()
        self.fonts = th.apply_theme(QApplication.instance())
        self.engine: TriageEngine | None = None
        self.result: TriageResult | None = None
        self._sample_index = 0
        self._queue: queue.Queue = queue.Queue()

        self.setWindowTitle("Email Triage - NLP Demo")
        self.resize(1320, 840)
        self.setMinimumSize(1080, 700)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._build_header(root_layout)
        self._build_body(root_layout)
        self._build_correction_bar(root_layout)

        self.body_text.setPlaceholderText(PLACEHOLDER)
        self._reset_output()

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._analyze)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear)

        self._boot_timer = QTimer(self)
        self._boot_timer.setSingleShot(True)
        self._boot_timer.timeout.connect(self._boot_engine)
        self._boot_timer.start(60)

        self._drain_timer = QTimer(self)
        self._drain_timer.timeout.connect(self._drain_queue)
        self._drain_timer.start(80)

    # ---------------------------------------------------------------- header

    def _build_header(self, root_layout: QVBoxLayout) -> None:
        bar = QFrame(self)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(18, 14, 18, 11)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("Email Triage", bar)
        title.setFont(self.fonts.h1)
        left.addWidget(title)
        subtitle = _dim_label(
            "Concern classification and field extraction  -  runs fully offline",
            self.fonts,
        )
        left.addWidget(subtitle)
        bar_layout.addLayout(left)
        bar_layout.addStretch(1)

        self.engine_label = _dim_label("loading engine...", self.fonts)
        bar_layout.addWidget(self.engine_label)
        self.engine_pill = th.Pill(bar, self.fonts, bg=th.BG)
        self.engine_pill.set("STARTING", th.NEUTRAL)
        bar_layout.addWidget(self.engine_pill)

        root_layout.addWidget(bar)

        divider = QFrame(self)
        th.set_class(divider, "divider")
        root_layout.addWidget(divider)

    # ------------------------------------------------------------------ body

    def _build_body(self, root_layout: QVBoxLayout) -> None:
        wrap = QFrame(self)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(14, 13, 14, 6)
        root_layout.addWidget(wrap, 1)

        split = QSplitter(Qt.Horizontal, wrap)
        wrap_layout.addWidget(split)

        input_panel = self._build_input_panel(split)
        output_panel = self._build_output_panel(split)
        split.addWidget(input_panel)
        split.addWidget(output_panel)
        split.setStretchFactor(0, 44)
        split.setStretchFactor(1, 56)
        split.setSizes([580, 740])

    def _build_input_panel(self, parent: QWidget) -> QWidget:
        panel = QFrame(parent)
        th.set_class(panel, "surface")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(13, 13, 13, 13)

        head = QHBoxLayout()
        head_label = QLabel("INPUT", panel)
        head_label.setFont(self.fonts.h2)
        head.addWidget(head_label)
        head.addStretch(1)
        head.addWidget(_dim_label("Ctrl+Enter to analyze", self.fonts))
        layout.addLayout(head)

        layout.addWidget(_dim_label("Subject (optional)", self.fonts))
        self.subject_edit = QLineEdit(panel)
        self.subject_edit.setFont(self.fonts.body)
        layout.addWidget(self.subject_edit)

        layout.addWidget(_dim_label("Email body", self.fonts))
        self.body_text = QPlainTextEdit(panel)
        self.body_text.setFont(self.fonts.body)
        layout.addWidget(self.body_text, 1)

        actions = QHBoxLayout()
        self.analyze_btn = QPushButton("Analyze", panel)
        th.set_class(self.analyze_btn, "accent")
        self.analyze_btn.clicked.connect(self._analyze)
        actions.addWidget(self.analyze_btn)
        sample_btn = QPushButton("Load sample", panel)
        th.set_class(sample_btn, "ghost")
        sample_btn.clicked.connect(self._load_sample)
        actions.addWidget(sample_btn)
        clear_btn = QPushButton("Clear", panel)
        th.set_class(clear_btn, "ghost")
        clear_btn.clicked.connect(self._clear)
        actions.addWidget(clear_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        return panel

    def _build_output_panel(self, parent: QWidget) -> QWidget:
        panel = QFrame(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(11, 0, 0, 0)

        self.tabs = QTabWidget(panel)
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_summary_tab(self.tabs), "  Summary  ")
        self.tabs.addTab(self._build_text_tab(self.tabs), "  Plain text  ")
        self.tabs.addTab(self._build_json_tab(self.tabs), "  JSON  ")
        self.tabs.addTab(self._build_why_tab(self.tabs), "  Why this result  ")
        return panel

    def _build_summary_tab(self, parent: QWidget) -> QWidget:
        tab = QFrame(parent)
        th.set_class(tab, "surface")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)

        # ---- concern card --------------------------------------------
        card = QFrame(tab)
        th.set_class(card, "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(card)

        row = QHBoxLayout()
        row.addWidget(_dim_label("TYPE OF CONCERN", self.fonts))
        row.addStretch(1)
        self.status_pill = th.Pill(card, self.fonts, bg=th.ELEVATED)
        row.addWidget(self.status_pill)
        card_layout.addLayout(row)

        self.concern_label = QLabel("-", card)
        self.concern_label.setFont(self.fonts.h1)
        card_layout.addWidget(self.concern_label)
        self.concern_id_label = _dim_label("", self.fonts)
        card_layout.addWidget(self.concern_id_label)

        self.reason_heading = _dim_label("REASON", self.fonts)
        card_layout.addWidget(self.reason_heading)
        self.reason_label = QLabel("-", card)
        self.reason_label.setFont(self.fonts.mono_value)
        card_layout.addWidget(self.reason_label)

        meter_row = QHBoxLayout()
        self.meter = th.Meter(card, width=208, bg=th.ELEVATED)
        meter_row.addWidget(self.meter)
        self.conf_label = QLabel("", card)
        self.conf_label.setFont(self.fonts.mono_value)
        meter_row.addWidget(self.conf_label)
        meter_row.addStretch(1)
        card_layout.addLayout(meter_row)

        self.decision_label = _dim_label("", self.fonts)
        self.decision_label.setWordWrap(True)
        card_layout.addWidget(self.decision_label)

        # ---- fields ----------------------------------------------------
        layout.addWidget(_dim_label("DATA NEEDED", self.fonts))

        self.tree = QTreeWidget(tab)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["FIELD", "VALUE", "REQUIRED", "FOUND VIA"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 170)
        self.tree.setColumnWidth(1, 180)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 210)
        self.tree.header().setStretchLastSection(True)
        layout.addWidget(self.tree, 1)

        self.warn_label = _dim_label("", self.fonts)
        self.warn_label.setWordWrap(True)
        layout.addWidget(self.warn_label)
        return tab

    def _build_text_tab(self, parent: QWidget) -> QWidget:
        tab = QFrame(parent)
        th.set_class(tab, "surface")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        self.plain_out = self._readonly_text(tab)
        layout.addWidget(self.plain_out)
        return tab

    def _build_json_tab(self, parent: QWidget) -> QWidget:
        tab = QFrame(parent)
        th.set_class(tab, "surface")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        self.json_out = self._readonly_text(tab)
        layout.addWidget(self.json_out)

        bar = QHBoxLayout()
        copy_btn = QPushButton("Copy JSON", tab)
        th.set_class(copy_btn, "ghost")
        copy_btn.clicked.connect(self._copy_json)
        bar.addWidget(copy_btn)
        bar.addWidget(_dim_label(
            "This shape is what a host system consumes, and what training rows embed.",
            self.fonts,
        ))
        bar.addStretch(1)
        layout.addLayout(bar)
        return tab

    def _build_why_tab(self, parent: QWidget) -> QWidget:
        """The narrated version of the JSON: which rule fired, and what it beat."""
        tab = QFrame(parent)
        th.set_class(tab, "surface")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        self.why_out = self._readonly_text(tab)
        layout.addWidget(self.why_out)

        bar = QHBoxLayout()
        copy_btn = QPushButton("Copy explanation", tab)
        th.set_class(copy_btn, "ghost")
        copy_btn.clicked.connect(self._copy_why)
        bar.addWidget(copy_btn)
        bar.addWidget(_dim_label(
            "Disagree with any step below? Correct it in the TEACH bar and save.",
            self.fonts,
        ))
        bar.addStretch(1)
        layout.addLayout(bar)
        return tab

    def _readonly_text(self, parent: QWidget) -> QPlainTextEdit:
        widget = QPlainTextEdit(parent)
        widget.setReadOnly(True)
        widget.setFont(self.fonts.mono)
        return widget

    # -------------------------------------------------------- correction bar

    def _build_correction_bar(self, root_layout: QVBoxLayout) -> None:
        divider = QFrame(self)
        th.set_class(divider, "divider")
        root_layout.addWidget(divider)

        wrap = QFrame(self)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(18, 8, 18, 10)
        root_layout.addWidget(wrap)

        bar = QHBoxLayout()
        wrap_layout.addLayout(bar)

        bar.addWidget(_dim_label("TEACH", self.fonts))

        bar.addWidget(_dim_label("Correct concern:", self.fonts))
        self.correction_box = QComboBox(wrap)
        self.correction_box.setFont(self.fonts.body)
        self.correction_box.setMinimumWidth(180)
        self.correction_box.currentTextChanged.connect(self._toggle_new_label_row)
        bar.addWidget(self.correction_box)

        bar.addWidget(_dim_label("Reason:", self.fonts))
        self.reason_correction_box = QComboBox(wrap)
        self.reason_correction_box.setFont(self.fonts.body)
        self.reason_correction_box.setMinimumWidth(190)
        self.reason_correction_box.addItems([CORRECT, NEW_REASON])
        self.reason_correction_box.currentTextChanged.connect(self._toggle_new_label_row)
        bar.addWidget(self.reason_correction_box)

        bar.addWidget(_dim_label("Note:", self.fonts))
        self.note_edit = QLineEdit(wrap)
        self.note_edit.setFont(self.fonts.body)
        self.note_edit.setMinimumWidth(220)
        bar.addWidget(self.note_edit)

        self.save_btn = QPushButton("Save to dataset", wrap)
        th.set_class(self.save_btn, "ghost")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_record)
        bar.addWidget(self.save_btn)

        self.save_status = _dim_label("", self.fonts)
        bar.addWidget(self.save_status)
        bar.addStretch(1)

        # ---- second row: naming something the taxonomy does not have -------
        # Hidden until a "+ new ..." entry is picked, because it is the rare
        # case and the bar is already wide.
        self.new_row = QFrame(wrap)
        new_row_layout = QHBoxLayout(self.new_row)
        new_row_layout.setContentsMargins(0, 6, 0, 0)
        wrap_layout.addWidget(self.new_row)
        self.new_row.setVisible(False)

        new_row_layout.addWidget(_dim_label("NEW", self.fonts))

        self.new_concern_lbl = _dim_label("Concern:", self.fonts)
        new_row_layout.addWidget(self.new_concern_lbl)
        self.new_concern_edit = QLineEdit(self.new_row)
        self.new_concern_edit.setFont(self.fonts.body)
        self.new_concern_edit.setMinimumWidth(180)
        self.new_concern_edit.textChanged.connect(self._refresh_id_preview)
        new_row_layout.addWidget(self.new_concern_edit)

        self.new_reason_lbl = _dim_label("Reason:", self.fonts)
        new_row_layout.addWidget(self.new_reason_lbl)
        self.new_reason_edit = QLineEdit(self.new_row)
        self.new_reason_edit.setFont(self.fonts.body)
        self.new_reason_edit.setMinimumWidth(180)
        self.new_reason_edit.textChanged.connect(self._refresh_id_preview)
        new_row_layout.addWidget(self.new_reason_edit)

        # Shows the ids these names become, so what to paste into
        # concerns.json is never a guess.
        self.new_id_preview = _dim_label("", self.fonts)
        new_row_layout.addWidget(self.new_id_preview)
        new_row_layout.addStretch(1)

    # ------------------------------------------------------------- behaviour

    def _boot_engine(self) -> None:
        """Load the model off the UI thread; a cold ORT session takes a moment."""

        def work() -> None:
            try:
                eng = TriageEngine()
                self._queue.put(("engine", eng))
            except Exception as exc:  # surfaced in the UI, not swallowed
                self._queue.put(("engine_error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "engine":
                    self._on_engine_ready(payload)
                elif kind == "engine_error":
                    self.engine_pill.set("ENGINE FAILED", th.DANGER)
                    self.engine_label.setText(payload)
                elif kind == "result":
                    self._render(payload)
        except queue.Empty:
            pass

    def _on_engine_ready(self, engine: TriageEngine) -> None:
        self.engine = engine
        if engine.embeddings_active:
            self.engine_pill.set("3 LAYERS", th.OK)
            detail = "regex + rules + MiniLM embeddings"
        else:
            self.engine_pill.set("2 LAYERS", th.WARN)
            detail = "regex + rules only - model absent, confidence capped at 70%"
        n = len(engine.concern_ids)
        self.engine_label.setText(
            f"{detail}  |  {n} concern types  |  config {engine.config.config_version}"
        )
        self.correction_box.blockSignals(True)
        self.correction_box.clear()
        self.correction_box.addItems([CORRECT, *engine.concern_ids, "__other__", NEW_CONCERN])
        self.correction_box.setCurrentText(CORRECT)
        self.correction_box.blockSignals(False)

    def _clear(self) -> None:
        self.subject_edit.clear()
        self.body_text.clear()
        self.result = None
        self.save_btn.setEnabled(False)
        self.save_status.setText("")
        self.note_edit.clear()
        self._reset_correction_inputs()
        self._reset_output()

    def _load_sample(self) -> None:
        subject, body = SAMPLES[self._sample_index % len(SAMPLES)]
        self._sample_index += 1
        self.subject_edit.setText(subject)
        self.body_text.setPlainText(body)
        self._analyze()

    def _analyze(self) -> None:
        if self.engine is None:
            self.save_status.setText("engine still loading...")
            return
        body = self.body_text.toPlainText().strip()
        if not body:
            self.save_status.setText("nothing to analyze")
            return
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("Analyzing...")
        subject, clean_body = separate_transport_headers(
            body,
            self.subject_edit.text(),
        )
        if clean_body != body:
            self.subject_edit.setText(subject)
            self.body_text.setPlainText(clean_body)
            body = clean_body

        def work() -> None:
            try:
                res = self.engine.classify(body, subject=subject)
                self._queue.put(("result", res))
            except Exception as exc:
                self._queue.put(("engine_error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- render

    def _reset_output(self) -> None:
        self.concern_label.setText("-")
        self.concern_id_label.setText("")
        self.conf_label.setText("")
        self.reason_label.setText("")
        self.reason_heading.setVisible(False)
        self.reason_label.setVisible(False)
        self.warn_label.setText("")
        self.status_pill.set("READY", th.NEUTRAL)
        self.meter.set(0.0, th.NEUTRAL)
        self.tree.clear()
        for widget in (self.plain_out, self.json_out, self.why_out):
            widget.setPlainText("")

    def _render(self, result: TriageResult) -> None:
        self.result = result
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("Analyze")
        self.save_btn.setEnabled(True)
        self.save_status.setText("")

        color = th.STATUS_COLORS.get(result.status.value, th.NEUTRAL)
        self.status_pill.set(result.status.value, color)
        self.concern_label.setText(result.display_name or "No concern identified")
        self.concern_id_label.setText(
            (result.concern_id or "-")
            + ("   |   review required" if result.needs_review else "")
        )

        accept = self.engine.config.thresholds["accept"] if self.engine else 0.55
        review = self.engine.config.thresholds["review"] if self.engine else 0.35
        self.meter.set(result.confidence, color, ticks=(review, accept))
        self.conf_label.setText(f"{result.confidence:.0%}")

        if result.reason_id:
            self.reason_heading.setVisible(True)
            self.reason_label.setVisible(True)
            self.reason_label.setText(result.reason_display_name)
        else:
            self.reason_heading.setVisible(False)
            self.reason_label.setVisible(False)

        self.decision_label.setText(
            f"decided by: {result.explanation.reason}   |   "
            f"margin {result.margin:+.3f}   |   "
            f"layers: {', '.join(result.explanation.layers_used)}   |   "
            f"{result.elapsed_ms:.0f} ms"
        )
        self._refresh_reason_options(result.concern_id)

        self.tree.clear()
        for values, tag in _field_tree_rows(result):
            item = QTreeWidgetItem(list(values))
            item.setTextAlignment(2, Qt.AlignCenter)
            color = QColor(self.TAG_COLORS.get(tag, th.TEXT))
            for column in range(4):
                item.setForeground(column, color)
            self.tree.addTopLevelItem(item)

        warns: list[str] = []
        if result.missing_fields:
            warns.append(f"Missing required: {', '.join(result.missing_fields)}")
        if result.ambiguous_fields:
            warns.append(f"Ambiguous (competing values): {', '.join(result.ambiguous_fields)}")
        if any(f.from_history for f in result.fields.values()):
            warns.append("Some values came from quoted history - verify they are current.")
        if len(result.line_items) > 1:
            warns.append(
                f"Multiple inquiries: {len(result.line_items)} paired DOS/amount row(s)."
            )
        if not self.engine or not self.engine.embeddings_active:
            warns.append("Embedding layer inactive: confidence is capped at 70%.")
        self.warn_label.setText("\n".join(warns))

        self.plain_out.setPlainText(to_plain_text(result))
        self.json_out.setPlainText(to_json(result))
        self.why_out.setPlainText(
            to_explanation_text(
                result,
                thresholds=self.engine.config.thresholds if self.engine else None,
                embeddings_active=bool(self.engine and self.engine.embeddings_active),
            )
        )
        self._reset_correction_inputs()

    def _refresh_reason_options(self, concern_id: str | None) -> None:
        """Offer only the reasons belonging to the predicted concern."""
        options = [CORRECT, NO_REASON]
        if self.engine and concern_id:
            concern = self.engine.config.concern(concern_id)
            if concern:
                options += [r.id for r in concern.reasons]
        self.reason_correction_box.blockSignals(True)
        current = self.reason_correction_box.currentText()
        self.reason_correction_box.clear()
        self.reason_correction_box.addItems([*options, NEW_REASON])
        self.reason_correction_box.setCurrentText(
            current if current in [*options, NEW_REASON] else CORRECT
        )
        self.reason_correction_box.blockSignals(False)

    # -------------------------------------------------- new-taxonomy capture

    def _toggle_new_label_row(self, _text: str = "") -> None:
        """Show the NEW row only while a '+ new ...' entry is selected."""
        want_concern = self.correction_box.currentText() == NEW_CONCERN
        want_reason = self.reason_correction_box.currentText() == NEW_REASON

        self.new_row.setVisible(want_concern or want_reason)

        for widget, wanted in (
            (self.new_concern_edit, want_concern),
            (self.new_reason_edit, want_reason),
        ):
            widget.setEnabled(wanted)
        for label, wanted in (
            (self.new_concern_lbl, want_concern),
            (self.new_reason_lbl, want_reason),
        ):
            th.set_class(label, "dim" if wanted else "faint")
            _restyle(label)

        if want_concern:
            self.new_concern_edit.setFocus()
        elif want_reason:
            self.new_reason_edit.setFocus()
        self._refresh_id_preview()

    def _refresh_id_preview(self, *_args) -> None:
        parts = []
        if self.correction_box.currentText() == NEW_CONCERN:
            slug = slugify_label(self.new_concern_edit.text())
            parts.append(f"concern id: {slug or '-'}")
        if self.reason_correction_box.currentText() == NEW_REASON:
            slug = slugify_label(self.new_reason_edit.text())
            parts.append(f"reason id: {slug or '-'}")
        self.new_id_preview.setText(
            ("   ".join(parts) + "   (add to concerns.json to make it predictable)")
            if parts
            else ""
        )

    def _reset_correction_inputs(self) -> None:
        if self.correction_box.count():
            self.correction_box.setCurrentText(CORRECT)
        self.reason_correction_box.setCurrentText(CORRECT)
        self.new_concern_edit.setText("")
        self.new_reason_edit.setText("")
        self._toggle_new_label_row()

    # ----------------------------------------------------------------- teach

    def _copy_json(self) -> None:
        if self.result is None:
            return
        QApplication.clipboard().setText(to_json(self.result))
        self.save_status.setText("JSON copied to clipboard")

    def _copy_why(self) -> None:
        if self.result is None:
            return
        QApplication.clipboard().setText(
            to_explanation_text(
                self.result,
                thresholds=self.engine.config.thresholds if self.engine else None,
                embeddings_active=bool(self.engine and self.engine.embeddings_active),
            )
        )
        self.save_status.setText("explanation copied to clipboard")

    def _save_record(self) -> None:
        if self.result is None:
            return

        choice = self.correction_box.currentText()
        corrected = None
        proposed_concern = ""
        if choice == NEW_CONCERN:
            proposed_concern = self.new_concern_edit.text().strip()
            if not proposed_concern:
                self.save_status.setText("name the new concern first")
                self.new_concern_edit.setFocus()
                return
        elif not choice.startswith("("):
            corrected = choice

        rchoice = self.reason_correction_box.currentText()
        corrected_reason = None
        proposed_reason = ""
        if rchoice == NEW_REASON:
            proposed_reason = self.new_reason_edit.text().strip()
            if not proposed_reason:
                self.save_status.setText("name the new reason first")
                self.new_reason_edit.setFocus()
                return
        elif not rchoice.startswith("("):
            corrected_reason = rchoice

        record = build_training_record(
            body=self.body_text.toPlainText(),
            subject=self.subject_edit.text(),
            result=self.result,
            corrected_concern_id=corrected,
            corrected_reason_id=corrected_reason,
            proposed_concern=proposed_concern,
            proposed_reason=proposed_reason,
            reviewer_note=self.note_edit.text().strip(),
        )
        try:
            path = append_training_record(record, DATASET_PATH)
        except OSError as exc:
            show_error_dialog(self, "Could not save", f"{type(exc).__name__}: {exc}")
            return

        label = record["label"]
        if label["is_new_taxonomy"]:
            named = " + ".join(
                p["id"] for p in (label["proposed_concern"], label["proposed_reason"]) if p
            )
            status = f"saved proposal '{named}' -> {path.parent.name}/{path.name}"
        else:
            verified = "verified" if label["verified_by_human"] else "unverified"
            status = f"saved {verified} row -> {path.parent.name}/{path.name}"
        self.save_status.setText(status)
        self.note_edit.setText("")
        self._reset_correction_inputs()


def main() -> None:
    """Open the window. Flag handling lives in __main__, which routes here."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = TriageApp()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
