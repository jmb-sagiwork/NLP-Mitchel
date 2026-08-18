"""Tkinter harness for teaching the triage engine.

This is a teaching tool, not the product. Paste a body, see exactly what the
NLP concluded and why, then correct it - every saved row becomes a labelled
training example for the MiniLM prototypes and the keyword rules.

The engine imports nothing from this package. A host application integrates
with `email_triage.classify_email(body, subject)` and never ships this window.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from email_triage.engine import TriageEngine
from email_triage.render import (
    append_training_record,
    build_training_record,
    slugify_label,
    to_explanation_text,
    to_json,
    to_plain_text,
)
from email_triage.types import TriageResult

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


class TriageApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.fonts = th.apply_theme(root)
        self.engine: TriageEngine | None = None
        self.result: TriageResult | None = None
        self._sample_index = 0
        self._placeholder_showing = True
        self._queue: queue.Queue = queue.Queue()

        root.title("Email Triage - NLP Demo")
        # Widened from 1088x688 when the fonts were enlarged (SP-1.1-58): the
        # type grew ~20% and the old window clipped the teach bar and the tree.
        root.geometry("1320x840")
        root.minsize(1080, 700)

        self._build_header()
        self._build_body()
        self._build_correction_bar()

        self._show_placeholder()
        self.root.after(60, self._boot_engine)
        self.root.after(80, self._drain_queue)

        root.bind("<Control-Return>", lambda _e: self._analyze())
        root.bind("<Control-l>", lambda _e: self._clear())

    # ---------------------------------------------------------------- header

    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, style="TFrame", padding=(18, 14, 18, 11))
        bar.pack(fill="x")

        left = ttk.Frame(bar, style="TFrame")
        left.pack(side="left")
        ttk.Label(left, text="Email Triage", style="H1.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Concern classification and field extraction  -  runs fully offline",
            style="Dim.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        right = ttk.Frame(bar, style="TFrame")
        right.pack(side="right")
        self.engine_pill = th.Pill(right, self.fonts, bg=th.BG)
        self.engine_pill.pack(side="right")
        self.engine_pill.set("STARTING", th.NEUTRAL)
        self.engine_label = ttk.Label(right, text="loading engine...", style="Dim.TLabel")
        self.engine_label.pack(side="right", padx=(0, 10))

        ttk.Frame(self.root, style="Divider.TFrame", height=1).pack(fill="x")

    # ------------------------------------------------------------------ body

    def _build_body(self) -> None:
        wrap = ttk.Frame(self.root, style="TFrame", padding=(14, 13, 14, 6))
        wrap.pack(fill="both", expand=True)

        split = ttk.Panedwindow(wrap, orient="horizontal", style="Dark.TPanedwindow")
        split.pack(fill="both", expand=True)

        split.add(self._build_input_panel(split), weight=44)
        split.add(self._build_output_panel(split), weight=56)

    def _build_input_panel(self, parent: tk.Misc) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Surface.TFrame", padding=13)

        head = ttk.Frame(panel, style="Surface.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="INPUT", style="H2.TLabel").pack(side="left")
        ttk.Label(
            head, text="Ctrl+Enter to analyze", style="DimSurface.TLabel"
        ).pack(side="right")

        ttk.Label(panel, text="Subject (optional)", style="DimSurface.TLabel").pack(
            anchor="w", pady=(11, 4)
        )
        self.subject_var = tk.StringVar()
        ttk.Entry(
            panel, textvariable=self.subject_var, style="Dark.TEntry", font=self.fonts.body
        ).pack(fill="x")

        ttk.Label(panel, text="Email body", style="DimSurface.TLabel").pack(
            anchor="w", pady=(11, 4)
        )
        holder = ttk.Frame(panel, style="Surface.TFrame")
        holder.pack(fill="both", expand=True)
        self.body_text = th.text_widget(holder, self.fonts)
        sb = ttk.Scrollbar(
            holder, orient="vertical", command=self.body_text.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.body_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.body_text.pack(side="left", fill="both", expand=True)
        self.body_text.bind("<FocusIn>", self._clear_placeholder)
        self.body_text.tag_configure("placeholder", foreground=th.TEXT_FAINT)

        actions = ttk.Frame(panel, style="Surface.TFrame")
        actions.pack(fill="x", pady=(11, 0))
        self.analyze_btn = ttk.Button(
            actions, text="Analyze", style="Accent.TButton", command=self._analyze
        )
        self.analyze_btn.pack(side="left")
        ttk.Button(
            actions, text="Load sample", style="Ghost.TButton", command=self._load_sample
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            actions, text="Clear", style="Ghost.TButton", command=self._clear
        ).pack(side="left", padx=(6, 0))
        return panel

    def _build_output_panel(self, parent: tk.Misc) -> ttk.Frame:
        panel = ttk.Frame(parent, style="TFrame", padding=(11, 0, 0, 0))

        self.tabs = ttk.Notebook(panel, style="Dark.TNotebook")
        self.tabs.pack(fill="both", expand=True)

        self.tabs.add(self._build_summary_tab(self.tabs), text="  Summary  ")
        self.tabs.add(self._build_text_tab(self.tabs), text="  Plain text  ")
        self.tabs.add(self._build_json_tab(self.tabs), text="  JSON  ")
        self.tabs.add(self._build_why_tab(self.tabs), text="  Why this result  ")
        return panel

    def _build_summary_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=14)

        # ---- concern card ------------------------------------------------
        card = ttk.Frame(tab, style="Card.TFrame", padding=14)
        card.pack(fill="x")

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="TYPE OF CONCERN", style="DimCard.TLabel").pack(anchor="w")
        self.status_pill = th.Pill(row, self.fonts, bg=th.ELEVATED)
        self.status_pill.place(relx=1.0, y=0, anchor="ne")

        self.concern_label = ttk.Label(card, text="-", style="Concern.TLabel")
        self.concern_label.pack(anchor="w", pady=(4, 2))
        self.concern_id_label = ttk.Label(card, text="", style="DimCard.TLabel")
        self.concern_id_label.pack(anchor="w")

        ttk.Label(card, text="REASON", style="DimCard.TLabel").pack(anchor="w", pady=(11, 0))
        self.reason_label = ttk.Label(card, text="-", style="Mono.TLabel")
        self.reason_label.pack(anchor="w", pady=(2, 0))

        meter_row = ttk.Frame(card, style="Card.TFrame")
        meter_row.pack(fill="x", pady=(13, 0))
        self.meter = th.Meter(meter_row, width=208, bg=th.ELEVATED)
        self.meter.pack(side="left")
        self.conf_label = ttk.Label(meter_row, text="", style="Mono.TLabel")
        self.conf_label.pack(side="left", padx=(10, 0))
        self.decision_label = ttk.Label(card, text="", style="DimCard.TLabel")
        self.decision_label.pack(anchor="w", pady=(6, 0))

        # ---- fields ------------------------------------------------------
        ttk.Label(tab, text="DATA NEEDED", style="DimSurface.TLabel").pack(
            anchor="w", pady=(16, 5)
        )
        tree_holder = ttk.Frame(tab, style="Surface.TFrame")
        tree_holder.pack(fill="both", expand=True)

        cols = ("field", "value", "req", "source")
        self.tree = ttk.Treeview(
            tree_holder, columns=cols, show="headings", style="Dark.Treeview", height=8
        )
        for key, label, width, anchor in (
            # Widened alongside the font bump - "Input - Expected Amount" and
            # "label_proximity:patient account" are the two that set the floor.
            # "source" stretches into whatever slack the window has.
            ("field", "FIELD", 170, "w"),
            ("value", "VALUE", 180, "w"),
            ("req", "REQUIRED", 90, "center"),
            ("source", "FOUND VIA", 210, "w"),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "source"))
        tsb = ttk.Scrollbar(
            tree_holder, orient="vertical", command=self.tree.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.tag_configure("found", foreground=th.TEXT)
        self.tree.tag_configure("missing", foreground=th.DANGER)
        self.tree.tag_configure("optional_missing", foreground=th.TEXT_FAINT)
        self.tree.tag_configure("history", foreground=th.WARN)

        self.warn_label = ttk.Label(tab, text="", style="DimSurface.TLabel", wraplength=620)
        self.warn_label.pack(anchor="w", pady=(8, 0))
        return tab

    def _build_text_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=10)
        self.plain_out, _ = self._readonly_text(tab)
        return tab

    def _build_json_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=10)
        self.json_out, _ = self._readonly_text(tab)
        bar = ttk.Frame(tab, style="Surface.TFrame")
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(
            bar, text="Copy JSON", style="Ghost.TButton", command=self._copy_json
        ).pack(side="left")
        ttk.Label(
            bar,
            text="This shape is what a host system consumes, and what training rows embed.",
            style="DimSurface.TLabel",
        ).pack(side="left", padx=(10, 0))
        return tab

    def _build_why_tab(self, parent: tk.Misc) -> ttk.Frame:
        """The narrated version of the JSON: which rule fired, and what it beat.

        Everything shown here is already in `result.explanation`; the tab exists
        because reading a fused score off a table is not the same as being told
        why the concern won and why the reason was or was not stated.
        """
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=10)
        self.why_out, _ = self._readonly_text(tab)
        bar = ttk.Frame(tab, style="Surface.TFrame")
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(
            bar, text="Copy explanation", style="Ghost.TButton", command=self._copy_why
        ).pack(side="left")
        ttk.Label(
            bar,
            text="Disagree with any step below? Correct it in the TEACH bar and save.",
            style="DimSurface.TLabel",
        ).pack(side="left", padx=(10, 0))
        return tab

    def _readonly_text(self, parent: tk.Misc) -> tuple[tk.Text, ttk.Scrollbar]:
        holder = ttk.Frame(parent, style="Surface.TFrame")
        holder.pack(fill="both", expand=True)
        widget = th.text_widget(holder, self.fonts, mono=True)
        sb = ttk.Scrollbar(
            holder, orient="vertical", command=widget.yview,
            style="Dark.Vertical.TScrollbar",
        )
        widget.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        widget.pack(side="left", fill="both", expand=True)
        return widget, sb

    # -------------------------------------------------------- correction bar

    def _build_correction_bar(self) -> None:
        ttk.Frame(self.root, style="Divider.TFrame", height=1).pack(fill="x")
        # Tighter than a flat 0.8x of the original padding: the NEW row below
        # has to fit inside the same 688px window when it unfolds.
        wrap = ttk.Frame(self.root, style="TFrame", padding=(18, 8, 18, 10))
        wrap.pack(fill="x")

        bar = ttk.Frame(wrap, style="TFrame")
        bar.pack(fill="x")

        ttk.Label(bar, text="TEACH", style="Dim.TLabel").pack(side="left", padx=(0, 11))

        ttk.Label(bar, text="Correct concern:", style="Dim.TLabel").pack(side="left")
        self.correction_var = tk.StringVar()
        self.correction_box = ttk.Combobox(
            bar, textvariable=self.correction_var, state="readonly",
            style="Dark.TCombobox", width=22, font=self.fonts.body,
        )
        self.correction_box.pack(side="left", padx=(6, 13))
        self.correction_box.bind("<<ComboboxSelected>>", self._toggle_new_label_row)

        ttk.Label(bar, text="Reason:", style="Dim.TLabel").pack(side="left")
        self.reason_correction_var = tk.StringVar()
        self.reason_correction_box = ttk.Combobox(
            bar, textvariable=self.reason_correction_var, state="readonly",
            style="Dark.TCombobox", width=24, font=self.fonts.body,
        )
        self.reason_correction_box.pack(side="left", padx=(6, 13))
        self.reason_correction_box.bind("<<ComboboxSelected>>", self._toggle_new_label_row)
        self.reason_correction_box.configure(values=[CORRECT, NEW_REASON])
        self.reason_correction_var.set(CORRECT)

        ttk.Label(bar, text="Note:", style="Dim.TLabel").pack(side="left")
        self.note_var = tk.StringVar()
        ttk.Entry(
            bar, textvariable=self.note_var, style="Dark.TEntry",
            font=self.fonts.body, width=28,
        ).pack(side="left", padx=(6, 13))

        self.save_btn = ttk.Button(
            bar, text="Save to dataset", style="Ghost.TButton",
            command=self._save_record, state="disabled",
        )
        self.save_btn.pack(side="left")

        self.save_status = ttk.Label(bar, text="", style="Dim.TLabel")
        self.save_status.pack(side="left", padx=(11, 0))

        # ---- second row: naming something the taxonomy does not have -------
        # Hidden until a "+ new ..." entry is picked, because it is the rare
        # case and the bar is already wide.
        self.new_row = ttk.Frame(wrap, style="TFrame")

        ttk.Label(self.new_row, text="NEW", style="Dim.TLabel").pack(
            side="left", padx=(0, 11)
        )

        self.new_concern_lbl = ttk.Label(self.new_row, text="Concern:", style="Dim.TLabel")
        self.new_concern_lbl.pack(side="left")
        self.new_concern_var = tk.StringVar()
        self.new_concern_entry = ttk.Entry(
            self.new_row, textvariable=self.new_concern_var, style="Dark.TEntry",
            font=self.fonts.body, width=24,
        )
        self.new_concern_entry.pack(side="left", padx=(6, 6))

        self.new_reason_lbl = ttk.Label(self.new_row, text="Reason:", style="Dim.TLabel")
        self.new_reason_lbl.pack(side="left", padx=(11, 0))
        self.new_reason_var = tk.StringVar()
        self.new_reason_entry = ttk.Entry(
            self.new_row, textvariable=self.new_reason_var, style="Dark.TEntry",
            font=self.fonts.body, width=24,
        )
        self.new_reason_entry.pack(side="left", padx=(6, 13))

        # Shows the ids these names become, so what to paste into
        # concerns.json is never a guess.
        self.new_id_preview = ttk.Label(self.new_row, text="", style="Dim.TLabel")
        self.new_id_preview.pack(side="left")
        self.new_concern_var.trace_add("write", self._refresh_id_preview)
        self.new_reason_var.trace_add("write", self._refresh_id_preview)

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
                    self.engine_label.configure(text=payload)
                elif kind == "result":
                    self._render(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_queue)

    def _on_engine_ready(self, engine: TriageEngine) -> None:
        self.engine = engine
        if engine.embeddings_active:
            self.engine_pill.set("3 LAYERS", th.OK)
            detail = "regex + rules + MiniLM embeddings"
        else:
            self.engine_pill.set("2 LAYERS", th.WARN)
            detail = "regex + rules only - model absent, confidence capped at 70%"
        n = len(engine.concern_ids)
        self.engine_label.configure(
            text=f"{detail}  |  {n} concern types  |  config {engine.config.config_version}"
        )
        self.correction_box.configure(
            values=[CORRECT, *engine.concern_ids, "__other__", NEW_CONCERN]
        )
        self.correction_var.set(CORRECT)

    def _show_placeholder(self) -> None:
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", PLACEHOLDER, "placeholder")
        self._placeholder_showing = True

    def _clear_placeholder(self, _event=None) -> None:
        if self._placeholder_showing:
            self.body_text.delete("1.0", "end")
            self._placeholder_showing = False

    def _current_body(self) -> str:
        if self._placeholder_showing:
            return ""
        return self.body_text.get("1.0", "end-1c")

    def _clear(self) -> None:
        self.subject_var.set("")
        self._show_placeholder()
        self.result = None
        self.save_btn.configure(state="disabled")
        self.save_status.configure(text="")
        self.note_var.set("")
        self._reset_correction_inputs()
        self._reset_output()

    def _load_sample(self) -> None:
        subject, body = SAMPLES[self._sample_index % len(SAMPLES)]
        self._sample_index += 1
        self.subject_var.set(subject)
        self._placeholder_showing = False
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", body)
        self._analyze()

    def _analyze(self) -> None:
        if self.engine is None:
            self.save_status.configure(text="engine still loading...")
            return
        body = self._current_body().strip()
        if not body:
            self.save_status.configure(text="nothing to analyze")
            return
        self.analyze_btn.configure(state="disabled", text="Analyzing...")
        subject = self.subject_var.get()

        def work() -> None:
            try:
                res = self.engine.classify(body, subject=subject)
                self._queue.put(("result", res))
            except Exception as exc:
                self._queue.put(("engine_error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- render

    def _reset_output(self) -> None:
        self.concern_label.configure(text="-")
        self.concern_id_label.configure(text="")
        self.conf_label.configure(text="")
        self.reason_label.configure(text="")
        self.warn_label.configure(text="")
        self.status_pill.set("READY", th.NEUTRAL)
        self.meter.set(0.0, th.NEUTRAL)
        self.tree.delete(*self.tree.get_children())
        for widget in (self.plain_out, self.json_out, self.why_out):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")

    def _render(self, result: TriageResult) -> None:
        self.result = result
        self.analyze_btn.configure(state="normal", text="Analyze")
        self.save_btn.configure(state="normal")
        self.save_status.configure(text="")

        color = th.STATUS_COLORS.get(result.status.value, th.NEUTRAL)
        self.status_pill.set(result.status.value, color)
        self.concern_label.configure(text=result.display_name or "No concern identified")
        self.concern_id_label.configure(
            text=(result.concern_id or "-")
            + ("   |   review required" if result.needs_review else "")
        )

        accept = self.engine.config.thresholds["accept"] if self.engine else 0.55
        review = self.engine.config.thresholds["review"] if self.engine else 0.35
        self.meter.set(result.confidence, color, ticks=(review, accept))
        self.conf_label.configure(text=f"{result.confidence:.0%}")

        if result.reason_id:
            self.reason_label.configure(text=result.reason_display_name)
        else:
            self.reason_label.configure(text="(none stated in this email)")

        self.decision_label.configure(
            text=f"decided by: {result.explanation.reason}   |   "
                 f"margin {result.margin:+.3f}   |   "
                 f"layers: {', '.join(result.explanation.layers_used)}   |   "
                 f"{result.elapsed_ms:.0f} ms"
        )
        self._refresh_reason_options(result.concern_id)

        self.tree.delete(*self.tree.get_children())
        for f in result.fields.values():
            if f.value is None:
                tag = "missing" if f.required else "optional_missing"
                value, source = "NOT FOUND", "-"
            else:
                tag = "history" if f.from_history else "found"
                value = f.value
                source = f"{f.strategy}  ({f.segment})"
            self.tree.insert(
                "", "end",
                values=(f.display_name, value, "yes" if f.required else "no", source),
                tags=(tag,),
            )

        warns: list[str] = []
        if result.missing_fields:
            warns.append(f"Missing required: {', '.join(result.missing_fields)}")
        if result.ambiguous_fields:
            warns.append(f"Ambiguous (competing values): {', '.join(result.ambiguous_fields)}")
        if any(f.from_history for f in result.fields.values()):
            warns.append("Some values came from quoted history - verify they are current.")
        if not self.engine or not self.engine.embeddings_active:
            warns.append("Embedding layer inactive: confidence is capped at 70%.")
        self.warn_label.configure(text="\n".join(warns))

        self._fill(self.plain_out, to_plain_text(result))
        self._fill(self.json_out, to_json(result))
        self._fill(
            self.why_out,
            to_explanation_text(
                result,
                thresholds=self.engine.config.thresholds if self.engine else None,
                embeddings_active=bool(self.engine and self.engine.embeddings_active),
            ),
        )
        self._reset_correction_inputs()

    def _refresh_reason_options(self, concern_id: str | None) -> None:
        """Offer only the reasons belonging to the predicted concern."""
        options = [CORRECT, NO_REASON]
        if self.engine and concern_id:
            concern = self.engine.config.concern(concern_id)
            if concern:
                options += [r.id for r in concern.reasons]
        self.reason_correction_box.configure(values=[*options, NEW_REASON])

    # -------------------------------------------------- new-taxonomy capture

    def _toggle_new_label_row(self, _event=None) -> None:
        """Show the NEW row only while a '+ new ...' entry is selected."""
        want_concern = self.correction_var.get() == NEW_CONCERN
        want_reason = self.reason_correction_var.get() == NEW_REASON

        if want_concern or want_reason:
            if not self.new_row.winfo_ismapped():
                self.new_row.pack(fill="x", pady=(6, 0))
        else:
            self.new_row.pack_forget()

        for widget, wanted in (
            (self.new_concern_entry, want_concern),
            (self.new_reason_entry, want_reason),
        ):
            widget.configure(state="normal" if wanted else "disabled")
        for label, wanted in (
            (self.new_concern_lbl, want_concern),
            (self.new_reason_lbl, want_reason),
        ):
            label.configure(style="Dim.TLabel" if wanted else "Faint.TLabel")

        if want_concern:
            self.new_concern_entry.focus_set()
        elif want_reason:
            self.new_reason_entry.focus_set()
        self._refresh_id_preview()

    def _refresh_id_preview(self, *_args) -> None:
        parts = []
        if self.correction_var.get() == NEW_CONCERN:
            slug = slugify_label(self.new_concern_var.get())
            parts.append(f"concern id: {slug or '-'}")
        if self.reason_correction_var.get() == NEW_REASON:
            slug = slugify_label(self.new_reason_var.get())
            parts.append(f"reason id: {slug or '-'}")
        self.new_id_preview.configure(
            text=("   ".join(parts) + "   (add to concerns.json to make it predictable)")
            if parts
            else ""
        )

    def _reset_correction_inputs(self) -> None:
        self.correction_var.set(CORRECT)
        self.reason_correction_var.set(CORRECT)
        self.new_concern_var.set("")
        self.new_reason_var.set("")
        self._toggle_new_label_row()

    def _fill(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # ----------------------------------------------------------------- teach

    def _copy_json(self) -> None:
        if self.result is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(to_json(self.result))
        self.save_status.configure(text="JSON copied to clipboard")

    def _copy_why(self) -> None:
        if self.result is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(
            to_explanation_text(
                self.result,
                thresholds=self.engine.config.thresholds if self.engine else None,
                embeddings_active=bool(self.engine and self.engine.embeddings_active),
            )
        )
        self.save_status.configure(text="explanation copied to clipboard")

    def _save_record(self) -> None:
        if self.result is None:
            return

        choice = self.correction_var.get()
        corrected = None
        proposed_concern = ""
        if choice == NEW_CONCERN:
            proposed_concern = self.new_concern_var.get().strip()
            if not proposed_concern:
                self.save_status.configure(text="name the new concern first")
                self.new_concern_entry.focus_set()
                return
        elif not choice.startswith("("):
            corrected = choice

        rchoice = self.reason_correction_var.get()
        corrected_reason = None
        proposed_reason = ""
        if rchoice == NEW_REASON:
            proposed_reason = self.new_reason_var.get().strip()
            if not proposed_reason:
                self.save_status.configure(text="name the new reason first")
                self.new_reason_entry.focus_set()
                return
        elif not rchoice.startswith("("):
            corrected_reason = rchoice

        record = build_training_record(
            body=self._current_body(),
            subject=self.subject_var.get(),
            result=self.result,
            corrected_concern_id=corrected,
            corrected_reason_id=corrected_reason,
            proposed_concern=proposed_concern,
            proposed_reason=proposed_reason,
            reviewer_note=self.note_var.get().strip(),
        )
        try:
            path = append_training_record(record, DATASET_PATH)
        except OSError as exc:
            messagebox.showerror("Could not save", f"{type(exc).__name__}: {exc}")
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
        self.save_status.configure(text=status)
        self.note_var.set("")
        self._reset_correction_inputs()


def main() -> None:
    """Open the window. Flag handling lives in __main__, which routes here."""
    root = tk.Tk()
    try:
        # Left at 1.0 deliberately. Text size is set by the point sizes in
        # theme.Fonts; scaling here would also inflate every padding value.
        root.tk.call("tk", "scaling", 1.0)
    except tk.TclError:
        pass
    TriageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
