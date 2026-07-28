from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from smartadvisor_automation.control_picker import (
    PickerError,
    build_entry,
    build_recording_report,
    find_start_window,
    sanitize_label,
    walk,
)

HIGHLIGHT_REFRESH_MS = 400


class ControlPickerApp:
    """Interactive, read-only tool for identifying exact controls.

    Highlights one child at a time starting from the SmartAdvisor main
    window. The user confirms each candidate with No (next sibling), Yes
    (descend into its children - this branch is right, but not itself the
    target), or Final (this exact control is the one to click). Never
    clicks, types, or submits anything in SmartAdvisor itself.

    Recording keeps every confirmed control in one session, each with the
    ancestor path walked to reach it, so several controls become a single
    saved report instead of one file per control.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Control Picker")
        self.root.geometry("680x520")
        self.root.minsize(600, 480)

        self.status = tk.StringVar(
            value="Open SmartAdvisor, then record your first control."
        )
        self._redraw_job: str | None = None
        self._generator: Any = None
        self._entries: list[dict[str, object]] = []

        self._build_ui()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)

        ttk.Label(
            container,
            text="SmartAdvisor Control Picker",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        ttk.Label(
            container,
            text=(
                "Read-only: highlights one control at a time starting from "
                "the SmartAdvisor main window. Record as many controls as "
                "you need - each one keeps the path walked to reach it - "
                "then save them all as one report."
            ),
            wraplength=620,
        ).grid(row=1, column=0, sticky=tk.W, pady=(8, 14))

        button_row = ttk.Frame(container)
        button_row.grid(row=2, column=0, sticky=tk.W, pady=(0, 12))

        self.record_button = ttk.Button(
            button_row,
            text="Record a control",
            command=self._start_walk,
        )
        self.record_button.pack(side=tk.LEFT)

        self.save_button = ttk.Button(
            button_row,
            text="Save recording",
            command=self._save_recording,
            state=tk.DISABLED,
        )
        self.save_button.pack(side=tk.LEFT, padx=(8, 0))

        self.clear_button = ttk.Button(
            button_row,
            text="Discard all",
            command=self._discard_all,
            state=tk.DISABLED,
        )
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(container).grid(row=3, column=0, sticky=tk.EW)

        ttk.Label(
            container,
            text="Recorded controls",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=4, column=0, sticky=tk.W, pady=(12, 4))

        list_frame = ttk.Frame(container)
        list_frame.grid(row=5, column=0, sticky=tk.NSEW)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.entry_list = tk.Listbox(list_frame, height=8)
        self.entry_list.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.entry_list.yview
        )
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.entry_list.configure(yscrollcommand=scrollbar.set)

        ttk.Label(
            container,
            textvariable=self.status,
            wraplength=620,
        ).grid(row=6, column=0, sticky=tk.W, pady=(12, 0))

    def _start_walk(self) -> None:
        self._set_buttons(enabled=False)
        try:
            window = find_start_window()
        except PickerError as exc:
            self._stop_with_error(exc.code)
            return

        self.status.set("Walking from the SmartAdvisor main window...")
        self._generator = walk(window)
        self._advance(None)

    def _advance(self, answer: str | None) -> None:
        try:
            if answer is None:
                candidate, _siblings = next(self._generator)
            else:
                candidate, _siblings = self._generator.send(answer)
        except StopIteration as stop:
            confirmed, siblings, path = stop.value
            self._record_entry(confirmed, siblings, path)
            return
        except PickerError as exc:
            self._stop_with_error(exc.code)
            return

        self._show_confirm(candidate)

    def _show_confirm(self, candidate: Any) -> None:
        info = candidate.element_info
        automation_id = str(getattr(info, "automation_id", "") or "")
        control_type = str(getattr(info, "control_type", "") or "")
        class_name = str(getattr(info, "class_name", "") or "")

        dialog = tk.Toplevel(self.root)
        dialog.title("Confirm control")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)

        text = (
            f"AutomationId: {automation_id or '(none)'}\n"
            f"ControlType: {control_type or '(none)'}\n"
            f"ClassName: {class_name or '(none)'}\n\n"
            "Is this the control highlighted in red on your screen?"
        )
        ttk.Label(dialog, text=text, justify=tk.LEFT, padding=16).pack()

        button_frame = ttk.Frame(dialog, padding=(16, 0, 16, 16))
        button_frame.pack()

        answer_holder: dict[str, str] = {}

        def answer(value: str) -> None:
            answer_holder["value"] = value
            dialog.destroy()

        ttk.Button(
            button_frame, text="No", command=lambda: answer("no")
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            button_frame,
            text="Yes (dig deeper)",
            command=lambda: answer("yes"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            button_frame,
            text="Final (this is it)",
            command=lambda: answer("final"),
        ).pack(side=tk.LEFT, padx=4)

        def redraw() -> None:
            try:
                candidate.draw_outline(colour="red", thickness=4)
            except Exception:
                pass
            self._redraw_job = self.root.after(
                HIGHLIGHT_REFRESH_MS, redraw
            )

        dialog.protocol("WM_DELETE_WINDOW", lambda: answer("no"))
        redraw()
        dialog.grab_set()
        self.root.wait_window(dialog)

        if self._redraw_job is not None:
            self.root.after_cancel(self._redraw_job)
            self._redraw_job = None

        self.status.set("Waiting for the next candidate...")
        self._advance(answer_holder.get("value", "no"))

    def _record_entry(
        self, confirmed: Any, siblings: list[Any], path: list[Any]
    ) -> None:
        index = len(self._entries) + 1
        label = simpledialog.askstring(
            "Label this control",
            (
                "Short structural label for this control, e.g. "
                '"open bill launcher". Optional - do not enter customer '
                "data.\n"
            ),
            parent=self.root,
        )
        entry = build_entry(
            confirmed,
            siblings,
            path,
            label=sanitize_label(label),
            index=index,
        )
        self._entries.append(entry)
        self._refresh_entry_list()

        self.status.set(
            f"Recorded {index} control(s). Record another, or save the "
            "recording as one report."
        )
        self._set_buttons(enabled=True)

    def _refresh_entry_list(self) -> None:
        self.entry_list.delete(0, tk.END)
        for entry in self._entries:
            confirmed = entry["confirmed"]
            automation_id = str(confirmed.get("automation_id") or "(none)")
            control_type = str(confirmed.get("control_type") or "(none)")
            label = str(entry.get("label") or "unlabelled")
            depth = entry.get("path_depth")
            self.entry_list.insert(
                tk.END,
                f"{entry['entry_index']}. {label} - {automation_id} "
                f"[{control_type}] - depth {depth}",
            )

    def _save_recording(self) -> None:
        if not self._entries:
            self.status.set("Nothing recorded yet.")
            return

        desktop = Path.home() / "Desktop"
        initial_directory = desktop if desktop.is_dir() else Path.home()
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save control picker recording",
            initialdir=str(initial_directory),
            initialfile="SmartAdvisor-control-report.json",
            defaultextension=".json",
            filetypes=[("JSON report", "*.json")],
        )
        if not destination:
            self.status.set("Save cancelled - the recording is still held.")
            return

        report = build_recording_report(self._entries)
        try:
            Path(destination).write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            self._stop_with_error(type(exc).__name__)
            return

        self.status.set(f"Saved {len(self._entries)} control(s) to {destination}")
        messagebox.showinfo(
            "Control recording saved",
            (
                f"{len(self._entries)} confirmed control(s), each with the "
                "path walked to reach it, were saved.\n\n"
                f"{destination}"
            ),
            parent=self.root,
        )

    def _discard_all(self) -> None:
        if not self._entries:
            return
        if not messagebox.askyesno(
            "Discard recording",
            (
                f"Discard all {len(self._entries)} recorded control(s)? "
                "This cannot be undone."
            ),
            parent=self.root,
        ):
            return
        self._entries.clear()
        self._refresh_entry_list()
        self.status.set("Recording discarded.")
        self._set_buttons(enabled=True)

    def _set_buttons(self, *, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        has_entries = enabled and bool(self._entries)
        self.record_button.configure(state=state)
        self.save_button.configure(
            state=tk.NORMAL if has_entries else tk.DISABLED
        )
        self.clear_button.configure(
            state=tk.NORMAL if has_entries else tk.DISABLED
        )

    def _stop_with_error(self, code: str) -> None:
        held = len(self._entries)
        suffix = (
            f" {held} recorded control(s) are still held - you can save them."
            if held
            else ""
        )
        self.status.set(f"Stopped safely: {code}.{suffix}")
        messagebox.showerror(
            "Control picker stopped",
            f"The walk stopped safely.\n\nReason: {code}{suffix}",
            parent=self.root,
        )
        self._set_buttons(enabled=True)


def main() -> None:
    root = tk.Tk()
    ControlPickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
