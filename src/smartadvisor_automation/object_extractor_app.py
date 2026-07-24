from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from smartadvisor_automation.object_extractor import (
    extract_smartadvisor_objects,
)


class ObjectExtractorApp:
    """Small read-only UI for exporting the SmartAdvisor object trees."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Object Extractor")
        self.root.geometry("640x360")
        self.root.minsize(560, 320)

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.status = tk.StringVar(
            value="Open SmartAdvisor and its Open Bill window first."
        )
        self.running = False

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="SmartAdvisor Object Extractor",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        ttk.Label(
            container,
            text=(
                "Read-only diagnostic: walks the native, UIA, and Win32 "
                "object trees without clicking or typing."
            ),
            wraplength=580,
        ).grid(row=1, column=0, sticky=tk.W, pady=(8, 14))

        privacy = ttk.LabelFrame(container, text="Privacy", padding=12)
        privacy.grid(row=2, column=0, sticky=tk.EW)
        ttk.Label(
            privacy,
            text=(
                "Field values and unknown control names are excluded. "
                "Only known structural names, IDs, classes, handles, "
                "bounds, and traversal errors are saved."
            ),
            wraplength=550,
        ).pack(anchor=tk.W)

        self.extract_button = ttk.Button(
            container,
            text="Extract objects and save JSON",
            command=self._start_extraction,
        )
        self.extract_button.grid(row=3, column=0, sticky=tk.W, pady=(18, 12))

        ttk.Separator(container).grid(row=4, column=0, sticky=tk.EW)
        ttk.Label(
            container,
            textvariable=self.status,
            wraplength=580,
        ).grid(row=5, column=0, sticky=tk.W, pady=(12, 0))

    def _start_extraction(self) -> None:
        if self.running:
            return
        self.running = True
        self.extract_button.configure(state=tk.DISABLED)
        self.status.set("Extracting SmartAdvisor object trees...")
        threading.Thread(
            target=self._extract_worker,
            daemon=True,
        ).start()

    def _extract_worker(self) -> None:
        try:
            report = extract_smartadvisor_objects()
        except Exception as exc:
            self.events.put(("error", type(exc).__name__))
        else:
            self.events.put(("complete", report))

    def _poll_events(self) -> None:
        while True:
            try:
                event_name, payload = self.events.get_nowait()
            except queue.Empty:
                break

            self.running = False
            self.extract_button.configure(state=tk.NORMAL)
            if event_name == "error":
                self._show_error(str(payload))
            elif event_name == "complete" and isinstance(payload, dict):
                self._save_report(payload)

        self.root.after(100, self._poll_events)

    def _save_report(self, report: dict[str, object]) -> None:
        discovery = report.get("discovery", {})
        if not isinstance(discovery, dict):
            discovery = {}
        if discovery.get("status") != "found":
            self._show_error("smartadvisor_window_not_found")
            return

        desktop = Path.home() / "Desktop"
        initial_directory = desktop if desktop.is_dir() else Path.home()
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save SmartAdvisor object report",
            initialdir=str(initial_directory),
            initialfile="SmartAdvisor-object-report.json",
            defaultextension=".json",
            filetypes=[("JSON report", "*.json")],
        )
        if not destination:
            self.status.set("Extraction complete; save was cancelled.")
            return

        try:
            Path(destination).write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            self._show_error(type(exc).__name__)
            return

        native_count = 0
        for tree in report.get("native_trees", []):
            if isinstance(tree, dict):
                native_count += int(tree.get("node_count", 0))
        backend_count = 0
        for tree in report.get("backend_trees", []):
            if isinstance(tree, dict):
                backend_count += int(tree.get("node_count", 0))
        self.status.set(
            f"Saved {native_count} native and {backend_count} backend "
            f"objects to {destination}"
        )
        messagebox.showinfo(
            "Object report saved",
            (
                "The privacy-safe object report was saved successfully.\n\n"
                f"{destination}"
            ),
            parent=self.root,
        )

    def _show_error(self, code: str) -> None:
        self.status.set(f"Extraction stopped safely: {code}")
        messagebox.showerror(
            "Extraction stopped",
            f"The read-only extraction stopped safely.\n\nReason: {code}",
            parent=self.root,
        )


def main() -> None:
    root = tk.Tk()
    ObjectExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
