"""Tkinter harness for the triage engine.

This stands in for the eventual mail integration: paste a body, see exactly what
the NLP concluded and why. The correction bar at the bottom is the part that
matters long term - every saved row becomes a labelled training example.

Nothing here is required by the engine. `classify_email` is the real product.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..engine import TriageEngine
from ..render import (
    append_training_record,
    build_training_record,
    to_json,
    to_plain_text,
)
from ..types import TriageResult, TriageStatus
from . import theme as th

DATASET_PATH = Path.cwd() / "data" / "dataset.jsonl"

PLACEHOLDER = (
    "Paste the email body here.\n\n"
    "Example:\n"
    "  Hi team, can you confirm the type of bill for claim WC1234567?\n"
    "  The charge amount is $1,250.00 and the TOB shows 0111.\n"
)

SAMPLES = [
    (
        "Type of bill question - claim WC1234567",
        "Hi team,\n\nCan you confirm the type of bill for claim WC1234567? "
        "The charge amount is $1,250.00 and the TOB shows 0111, which looks "
        "incorrect for this service.\n\nThanks,\nMaria\n",
    ),
    (
        "EOR request",
        "Good morning,\n\nPlease send a copy of the explanation of review for "
        "claim ABC-00456789, date of service 03/14/2026.\n\nRegards,\nBilling Dept\n",
    ),
    (
        "Reconsideration",
        "We disagree with the reduction applied to this bill. Requesting "
        "reconsideration for claim WC7788991, billed amount $980.50, "
        "date of service 02/02/2026.\n",
    ),
    (
        "Paraphrased - no keyword present",
        "Hello,\n\nWondering how this charge should be categorized for billing "
        "purposes on claim WC5551234. We billed $430.00.\n\nThank you\n",
    ),
    (
        "Missing a required field",
        "Can you tell me the bill type for this charge? The amount is $612.75.\n",
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
        root.geometry("1360x860")
        root.minsize(1120, 720)

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
        bar = ttk.Frame(self.root, style="TFrame", padding=(22, 18, 22, 14))
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
        self.engine_label.pack(side="right", padx=(0, 12))

        ttk.Frame(self.root, style="Divider.TFrame", height=1).pack(fill="x")

    # ------------------------------------------------------------------ body

    def _build_body(self) -> None:
        wrap = ttk.Frame(self.root, style="TFrame", padding=(18, 16, 18, 8))
        wrap.pack(fill="both", expand=True)

        split = ttk.Panedwindow(wrap, orient="horizontal", style="Dark.TPanedwindow")
        split.pack(fill="both", expand=True)

        split.add(self._build_input_panel(split), weight=44)
        split.add(self._build_output_panel(split), weight=56)

    def _build_input_panel(self, parent: tk.Misc) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Surface.TFrame", padding=16)

        head = ttk.Frame(panel, style="Surface.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="INPUT", style="H2.TLabel").pack(side="left")
        ttk.Label(
            head, text="Ctrl+Enter to analyze", style="DimSurface.TLabel"
        ).pack(side="right")

        ttk.Label(panel, text="Subject (optional)", style="DimSurface.TLabel").pack(
            anchor="w", pady=(14, 5)
        )
        self.subject_var = tk.StringVar()
        ttk.Entry(
            panel, textvariable=self.subject_var, style="Dark.TEntry", font=self.fonts.body
        ).pack(fill="x")

        ttk.Label(panel, text="Email body", style="DimSurface.TLabel").pack(
            anchor="w", pady=(14, 5)
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
        actions.pack(fill="x", pady=(14, 0))
        self.analyze_btn = ttk.Button(
            actions, text="Analyze", style="Accent.TButton", command=self._analyze
        )
        self.analyze_btn.pack(side="left")
        ttk.Button(
            actions, text="Load sample", style="Ghost.TButton", command=self._load_sample
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions, text="Clear", style="Ghost.TButton", command=self._clear
        ).pack(side="left", padx=(8, 0))
        return panel

    def _build_output_panel(self, parent: tk.Misc) -> ttk.Frame:
        panel = ttk.Frame(parent, style="TFrame", padding=(14, 0, 0, 0))

        self.tabs = ttk.Notebook(panel, style="Dark.TNotebook")
        self.tabs.pack(fill="both", expand=True)

        self.tabs.add(self._build_summary_tab(self.tabs), text="  Summary  ")
        self.tabs.add(self._build_text_tab(self.tabs), text="  Plain text  ")
        self.tabs.add(self._build_json_tab(self.tabs), text="  JSON  ")
        return panel

    def _build_summary_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=18)

        # ---- concern card ------------------------------------------------
        card = ttk.Frame(tab, style="Card.TFrame", padding=18)
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

        meter_row = ttk.Frame(card, style="Card.TFrame")
        meter_row.pack(fill="x", pady=(16, 0))
        self.meter = th.Meter(meter_row, width=260, bg=th.ELEVATED)
        self.meter.pack(side="left")
        self.conf_label = ttk.Label(meter_row, text="", style="Mono.TLabel")
        self.conf_label.pack(side="left", padx=(12, 0))
        self.reason_label = ttk.Label(card, text="", style="DimCard.TLabel")
        self.reason_label.pack(anchor="w", pady=(8, 0))

        # ---- fields ------------------------------------------------------
        ttk.Label(tab, text="DATA NEEDED", style="DimSurface.TLabel").pack(
            anchor="w", pady=(20, 6)
        )
        tree_holder = ttk.Frame(tab, style="Surface.TFrame")
        tree_holder.pack(fill="both", expand=True)

        cols = ("field", "value", "req", "source")
        self.tree = ttk.Treeview(
            tree_holder, columns=cols, show="headings", style="Dark.Treeview", height=8
        )
        for key, label, width, anchor in (
            ("field", "FIELD", 170, "w"),
            ("value", "VALUE", 190, "w"),
            ("req", "REQUIRED", 90, "center"),
            ("source", "FOUND VIA", 250, "w"),
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
        self.warn_label.pack(anchor="w", pady=(10, 0))
        return tab

    def _build_text_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=12)
        self.plain_out, _ = self._readonly_text(tab)
        return tab

    def _build_json_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Surface.TFrame", padding=12)
        self.json_out, _ = self._readonly_text(tab)
        bar = ttk.Frame(tab, style="Surface.TFrame")
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(
            bar, text="Copy JSON", style="Ghost.TButton", command=self._copy_json
        ).pack(side="left")
        ttk.Label(
            bar,
            text="This shape is what a host system consumes, and what training rows embed.",
            style="DimSurface.TLabel",
        ).pack(side="left", padx=(12, 0))
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
        bar = ttk.Frame(self.root, style="TFrame", padding=(22, 12, 22, 16))
        bar.pack(fill="x")

        ttk.Label(bar, text="TEACH", style="Dim.TLabel").pack(side="left", padx=(0, 14))

        ttk.Label(bar, text="Correct concern:", style="Dim.TLabel").pack(side="left")
        self.correction_var = tk.StringVar()
        self.correction_box = ttk.Combobox(
            bar, textvariable=self.correction_var, state="readonly",
            style="Dark.TCombobox", width=24, font=self.fonts.body,
        )
        self.correction_box.pack(side="left", padx=(8, 16))

        ttk.Label(bar, text="Note:", style="Dim.TLabel").pack(side="left")
        self.note_var = tk.StringVar()
        ttk.Entry(
            bar, textvariable=self.note_var, style="Dark.TEntry",
            font=self.fonts.body, width=34,
        ).pack(side="left", padx=(8, 16))

        self.save_btn = ttk.Button(
            bar, text="Save to dataset", style="Ghost.TButton",
            command=self._save_record, state="disabled",
        )
        self.save_btn.pack(side="left")

        self.save_status = ttk.Label(bar, text="", style="Dim.TLabel")
        self.save_status.pack(side="left", padx=(14, 0))

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
            values=["(prediction is correct)", *engine.concern_ids, "__other__"]
        )
        self.correction_var.set("(prediction is correct)")

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
        for widget in (self.plain_out, self.json_out):
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
        self.reason_label.configure(
            text=f"reason: {result.explanation.reason}   |   "
                 f"margin {result.margin:+.3f}   |   "
                 f"layers: {', '.join(result.explanation.layers_used)}   |   "
                 f"{result.elapsed_ms:.0f} ms"
        )

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
        self.correction_var.set("(prediction is correct)")

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

    def _save_record(self) -> None:
        if self.result is None:
            return
        choice = self.correction_var.get()
        corrected = None if choice.startswith("(") else choice
        record = build_training_record(
            body=self._current_body(),
            subject=self.subject_var.get(),
            result=self.result,
            corrected_concern_id=corrected,
            reviewer_note=self.note_var.get().strip(),
        )
        try:
            path = append_training_record(record, DATASET_PATH)
        except OSError as exc:
            messagebox.showerror("Could not save", f"{type(exc).__name__}: {exc}")
            return
        verified = record["label"]["verified_by_human"]
        self.save_status.configure(
            text=f"saved {'verified' if verified else 'unverified'} row -> "
                 f"{path.parent.name}/{path.name}"
        )
        self.note_var.set("")


def main() -> None:
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except tk.TclError:
        pass
    TriageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
