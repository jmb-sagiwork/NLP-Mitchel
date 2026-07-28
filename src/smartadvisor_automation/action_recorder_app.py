"""Standalone action recorder UI.

Start recording, work through SmartAdvisor by hand, stop, then save one
JSON file describing every step. The recording is the input to writing
automation code - it identifies controls and ordering, and deliberately
never captures typed characters.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from smartadvisor_automation.action_recorder import (
    ActionRecorder,
    UiaResolver,
    build_action_report,
)
from smartadvisor_automation.input_hooks import InputHookListener

DRAIN_INTERVAL_MS = 50


class ActionRecorderApp:
    """Observe an operator working in SmartAdvisor and record the steps.

    Read-only with respect to SmartAdvisor: the low-level hooks observe
    input and pass every event straight on, so nothing is clicked, typed,
    or submitted by this tool.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Action Recorder")
        self.root.geometry("760x560")
        self.root.minsize(660, 500)

        self.status = tk.StringVar(
            value="Open SmartAdvisor, then start recording."
        )
        self.listener: InputHookListener | None = None
        self.recorder = ActionRecorder(
            UiaResolver(), ignore_process_id=os.getpid()
        )
        self._drain_job: str | None = None
        self._recording = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(6, weight=1)

        ttk.Label(
            container,
            text="SmartAdvisor Action Recorder",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        ttk.Label(
            container,
            text=(
                "Records what you do in SmartAdvisor - which control you "
                "clicked, which control you typed into, and which keyboard "
                "shortcuts you used - so the workflow can be automated from "
                "it. Typed characters are never captured: a text entry is "
                "recorded only as \"this control received typing\"."
            ),
            wraplength=700,
        ).grid(row=1, column=0, sticky=tk.W, pady=(8, 12))

        button_row = ttk.Frame(container)
        button_row.grid(row=2, column=0, sticky=tk.W)

        self.record_button = ttk.Button(
            button_row, text="Start recording", command=self._start
        )
        self.record_button.pack(side=tk.LEFT)

        self.stop_button = ttk.Button(
            button_row,
            text="Stop recording",
            command=self._stop,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        self.save_button = ttk.Button(
            button_row,
            text="Save recording",
            command=self._save,
            state=tk.DISABLED,
        )
        self.save_button.pack(side=tk.LEFT, padx=(8, 0))

        edit_row = ttk.Frame(container)
        edit_row.grid(row=3, column=0, sticky=tk.W, pady=(8, 0))

        self.label_button = ttk.Button(
            edit_row,
            text="Label selected step",
            command=self._label_selected,
            state=tk.DISABLED,
        )
        self.label_button.pack(side=tk.LEFT)

        self.drop_button = ttk.Button(
            edit_row,
            text="Drop selected step",
            command=self._drop_selected,
            state=tk.DISABLED,
        )
        self.drop_button.pack(side=tk.LEFT, padx=(8, 0))

        self.clear_button = ttk.Button(
            edit_row,
            text="Discard all",
            command=self._discard_all,
            state=tk.DISABLED,
        )
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(container).grid(
            row=4, column=0, sticky=tk.EW, pady=(12, 0)
        )
        ttk.Label(
            container,
            text="Recorded steps",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=5, column=0, sticky=tk.W, pady=(12, 4))

        list_frame = ttk.Frame(container)
        list_frame.grid(row=6, column=0, sticky=tk.NSEW)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.step_list = tk.Listbox(list_frame, height=12)
        self.step_list.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.step_list.yview
        )
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.step_list.configure(yscrollcommand=scrollbar.set)

        ttk.Label(
            container, textvariable=self.status, wraplength=700
        ).grid(row=7, column=0, sticky=tk.W, pady=(12, 0))

    # -- recording -----------------------------------------------------

    def _start(self) -> None:
        self.listener = InputHookListener()
        self.listener.start()
        self._recording = True
        self.root.attributes("-topmost", True)
        self.record_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status.set(
            "Recording. Work through SmartAdvisor normally, then select "
            "Stop recording."
        )
        self._drain()

    def _drain(self) -> None:
        listener = self.listener
        if listener is None:
            return

        if listener.error_code:
            self.status.set(
                f"Recording stopped: {listener.error_code}. Input hooks "
                "were refused - the session may not allow them."
            )
            self._stop()
            return

        for event in listener.drain():
            self.recorder.handle_event(event)
        self._refresh_steps()

        self._drain_job = self.root.after(DRAIN_INTERVAL_MS, self._drain)

    def _stop(self) -> None:
        if self._drain_job is not None:
            self.root.after_cancel(self._drain_job)
            self._drain_job = None
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self._recording = False
        self.recorder.flush_pending()
        self._refresh_steps()
        self.root.attributes("-topmost", False)
        self.record_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.status.set(
            f"Stopped with {len(self.recorder.steps)} step(s). Label "
            "anything unclear, then save."
        )

    # -- step list -----------------------------------------------------

    def _refresh_steps(self) -> None:
        selection = self.step_list.curselection()
        self.step_list.delete(0, tk.END)
        for step in self.recorder.steps:
            self.step_list.insert(tk.END, self._describe_step(step))
        if selection and selection[0] < self.step_list.size():
            self.step_list.selection_set(selection[0])
        if self.recorder.steps:
            self.step_list.see(tk.END)
        self._sync_buttons()

    @staticmethod
    def _describe_step(step: dict) -> str:
        target = step.get("target") or {}
        automation_id = str(target.get("automation_id") or "") or "(no id)"
        control_type = str(target.get("control_type") or "") or "?"
        action = str(step.get("action"))
        detail = ""
        if action == "key":
            detail = f" {step.get('keys')}"
        elif action == "click" and step.get("button") != "left":
            detail = f" ({step.get('button')})"
        flags = ""
        if target.get("uniquely_resolvable") is False:
            flags += f" [AMBIGUOUS x{target.get('match_count')}]"
        if not target.get("automatable", True):
            flags += " [NO ID]"
        if step.get("opened_new_window"):
            flags += " [NEW WINDOW]"
        label = str(step.get("label") or "")
        label_part = f" - {label}" if label else ""
        return (
            f"{step['step_index']}. {action}{detail} -> {automation_id} "
            f"[{control_type}]{label_part}{flags}"
        )

    def _selected_index(self) -> int | None:
        selection = self.step_list.curselection()
        if not selection:
            return None
        position = selection[0]
        if position >= len(self.recorder.steps):
            return None
        return int(self.recorder.steps[position]["step_index"])

    def _label_selected(self) -> None:
        step_index = self._selected_index()
        if step_index is None:
            self.status.set("Select a step first.")
            return
        label = simpledialog.askstring(
            "Label step",
            (
                "Short structural label for this step, e.g. "
                '"claim id field". Optional - do not enter customer data.\n'
            ),
            parent=self.root,
        )
        if label is None:
            return
        self.recorder.label_step(step_index, label)
        self._refresh_steps()

    def _drop_selected(self) -> None:
        step_index = self._selected_index()
        if step_index is None:
            self.status.set("Select a step first.")
            return
        self.recorder.drop_step(step_index)
        self._refresh_steps()
        self.status.set(f"Dropped step {step_index}.")

    def _discard_all(self) -> None:
        if not self.recorder.steps:
            return
        if not messagebox.askyesno(
            "Discard recording",
            (
                f"Discard all {len(self.recorder.steps)} recorded step(s)? "
                "This cannot be undone."
            ),
            parent=self.root,
        ):
            return
        self.recorder.clear()
        self._refresh_steps()
        self.status.set("Recording discarded.")

    def _sync_buttons(self) -> None:
        has_steps = bool(self.recorder.steps)
        editable = has_steps and not self._recording
        self.save_button.configure(
            state=tk.NORMAL if editable else tk.DISABLED
        )
        self.label_button.configure(
            state=tk.NORMAL if editable else tk.DISABLED
        )
        self.drop_button.configure(
            state=tk.NORMAL if editable else tk.DISABLED
        )
        self.clear_button.configure(
            state=tk.NORMAL if editable else tk.DISABLED
        )

    # -- saving --------------------------------------------------------

    def _save(self) -> None:
        if not self.recorder.steps:
            self.status.set("Nothing recorded yet.")
            return

        notes = (
            simpledialog.askstring(
                "Recording notes",
                (
                    "Optional short note about what this recording covers, "
                    'e.g. "no bill on file, happy path". Do not enter '
                    "customer data.\n"
                ),
                parent=self.root,
            )
            or ""
        )

        desktop = Path.home() / "Desktop"
        initial_directory = desktop if desktop.is_dir() else Path.home()
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save action recording",
            initialdir=str(initial_directory),
            initialfile="SmartAdvisor-action-recording.json",
            defaultextension=".json",
            filetypes=[("JSON recording", "*.json")],
        )
        if not destination:
            self.status.set("Save cancelled - the recording is still held.")
            return

        report = build_action_report(
            self.recorder.steps,
            skipped=self.recorder.skipped,
            notes=notes,
        )
        try:
            Path(destination).write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            self.status.set(f"Save failed: {type(exc).__name__}")
            messagebox.showerror(
                "Save failed",
                f"The recording could not be written.\n\n"
                f"Reason: {type(exc).__name__}",
                parent=self.root,
            )
            return

        review = report["review"]
        warnings = []
        if review["steps_without_automation_id"]:
            warnings.append(
                "Steps with no AutomationId (not automatable as recorded): "
                f"{review['steps_without_automation_id']}"
            )
        if review["steps_not_uniquely_resolvable"]:
            warnings.append(
                "Steps whose AutomationId was not unique: "
                f"{review['steps_not_uniquely_resolvable']}"
            )

        self.status.set(
            f"Saved {len(self.recorder.steps)} step(s) to {destination}"
        )
        messagebox.showinfo(
            "Recording saved",
            "\n\n".join(
                [
                    f"{len(self.recorder.steps)} step(s) saved to:",
                    str(destination),
                    *warnings,
                ]
            ),
            parent=self.root,
        )

    def _on_close(self) -> None:
        if self.listener is not None:
            self.listener.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ActionRecorderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
