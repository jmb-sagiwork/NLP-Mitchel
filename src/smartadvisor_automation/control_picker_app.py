from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from smartadvisor_automation.control_picker import (
    PickerError,
    build_report,
    find_start_window,
    walk,
)

HIGHLIGHT_REFRESH_MS = 400


class ControlPickerApp:
    """Interactive, read-only tool for identifying one exact control.

    Highlights one child at a time starting from the SmartAdvisor main
    window. The user confirms each candidate with No (next sibling), Yes
    (descend into its children - this branch is right, but not itself the
    target), or Final (this exact control is the one to click). Never
    clicks, types, or submits anything in SmartAdvisor itself.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Control Picker")
        self.root.geometry("640x320")
        self.root.minsize(560, 300)

        self.status = tk.StringVar(
            value="Open SmartAdvisor, then start the walk."
        )
        self._redraw_job: str | None = None
        self._generator: Any = None

        self._build_ui()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="SmartAdvisor Control Picker",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        ttk.Label(
            container,
            text=(
                "Read-only: highlights one control at a time starting from "
                "the SmartAdvisor main window. Confirm each one to find the "
                "exact control you click - it never clicks it for you."
            ),
            wraplength=580,
        ).grid(row=1, column=0, sticky=tk.W, pady=(8, 14))

        self.start_button = ttk.Button(
            container,
            text="Start walk",
            command=self._start_walk,
        )
        self.start_button.grid(row=2, column=0, sticky=tk.W, pady=(0, 12))

        ttk.Separator(container).grid(row=3, column=0, sticky=tk.EW)
        ttk.Label(
            container,
            textvariable=self.status,
            wraplength=580,
        ).grid(row=4, column=0, sticky=tk.W, pady=(12, 0))

    def _start_walk(self) -> None:
        self.start_button.configure(state=tk.DISABLED)
        try:
            window = find_start_window()
        except PickerError as exc:
            self._finish_with_error(exc.code)
            return

        self._generator = walk(window)
        self._advance(None)

    def _advance(self, answer: str | None) -> None:
        try:
            if answer is None:
                candidate, _siblings = next(self._generator)
            else:
                candidate, _siblings = self._generator.send(answer)
        except StopIteration as stop:
            final_candidate, siblings = stop.value
            self._save_report(build_report(final_candidate, siblings))
            return
        except PickerError as exc:
            self._finish_with_error(exc.code)
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

    def _save_report(self, report: dict[str, object]) -> None:
        self.status.set("Confirmed. Save the report to share it.")

        desktop = Path.home() / "Desktop"
        initial_directory = desktop if desktop.is_dir() else Path.home()
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save control picker report",
            initialdir=str(initial_directory),
            initialfile="SmartAdvisor-control-report.json",
            defaultextension=".json",
            filetypes=[("JSON report", "*.json")],
        )
        if not destination:
            self.status.set("Confirmed, but save was cancelled.")
            self.start_button.configure(state=tk.NORMAL)
            return

        try:
            Path(destination).write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            self._finish_with_error(type(exc).__name__)
            return

        self.status.set(f"Saved to {destination}")
        messagebox.showinfo(
            "Control report saved",
            (
                "The confirmed control and its siblings were saved.\n\n"
                f"{destination}"
            ),
            parent=self.root,
        )
        self.start_button.configure(state=tk.NORMAL)

    def _finish_with_error(self, code: str) -> None:
        self.status.set(f"Stopped safely: {code}")
        messagebox.showerror(
            "Control picker stopped",
            f"The walk stopped safely.\n\nReason: {code}",
            parent=self.root,
        )
        self.start_button.configure(state=tk.NORMAL)


def main() -> None:
    root = tk.Tk()
    ControlPickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
