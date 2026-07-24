from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from smartadvisor_discovery.probe import scan_controls


class DiscoveryApp:
    """Tkinter front end for the read-only selector probe."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SmartAdvisor Control Discovery")
        self.root.geometry("1080x620")
        self.root.minsize(860, 480)
        self.report: dict[str, object] | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.status = tk.StringVar(
            value="Open and sign in to SmartAdvisor, then scan the current screen."
        )

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            container,
            text="SmartAdvisor Control Discovery",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor=tk.W)

        privacy = ttk.Label(
            container,
            text=(
                "Read-only validation: no clicks, inputs, field values, "
                "window titles, or credentials are captured."
            ),
        )
        privacy.pack(anchor=tk.W, pady=(4, 12))

        toolbar = ttk.Frame(container)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        self.scan_button = ttk.Button(
            toolbar, text="Scan controls", command=self._start_scan
        )
        self.scan_button.pack(side=tk.LEFT)

        self.save_button = ttk.Button(
            toolbar,
            text="Save sanitized report",
            command=self._save_report,
            state=tk.DISABLED,
        )
        self.save_button.pack(side=tk.LEFT, padx=(8, 0))

        columns = (
            "backend",
            "step",
            "automation_id",
            "label",
            "action",
            "status",
            "strategy",
            "control_type",
            "class_name",
        )
        table = ttk.Frame(container)
        table.pack(fill=tk.BOTH, expand=True)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table, columns=columns, show="headings", selectmode="browse"
        )

        headings = {
            "backend": "Backend",
            "step": "Step",
            "automation_id": "Automation ID",
            "label": "Purpose",
            "action": "Action",
            "status": "Status",
            "strategy": "Match",
            "control_type": "Control type",
            "class_name": "Class",
        }
        widths = {
            "backend": 70,
            "step": 55,
            "automation_id": 130,
            "label": 210,
            "action": 80,
            "status": 90,
            "strategy": 110,
            "control_type": 120,
            "class_name": 150,
        }

        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor=tk.W)

        vertical = ttk.Scrollbar(
            table, orient=tk.VERTICAL, command=self.tree.yview
        )
        horizontal = ttk.Scrollbar(
            table, orient=tk.HORIZONTAL, command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        status_bar = ttk.Label(
            self.root,
            textvariable=self.status,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(8, 4),
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _start_scan(self) -> None:
        self.scan_button.configure(state=tk.DISABLED)
        self.save_button.configure(state=tk.DISABLED)
        self.status.set("Scanning SmartAdvisor controls with UIA and Win32...")
        self._clear_rows()

        worker = threading.Thread(target=self._scan_worker, daemon=True)
        worker.start()

    def _scan_worker(self) -> None:
        try:
            report = scan_controls()
        except Exception as exc:
            self.events.put(("failed", type(exc).__name__))
            return

        self.events.put(("complete", report))

    def _poll_events(self) -> None:
        while True:
            try:
                event_name, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event_name == "complete" and isinstance(payload, dict):
                self._scan_complete(payload)
            elif event_name == "failed":
                self._scan_failed(str(payload))

        self.root.after(100, self._poll_events)

    def _scan_failed(self, error_code: str) -> None:
        self.report = None
        self.scan_button.configure(state=tk.NORMAL)
        self.status.set(f"Scan failed safely: {error_code}")
        messagebox.showerror(
            "Scan failed",
            f"The read-only scan failed safely ({error_code}).",
            parent=self.root,
        )

    def _scan_complete(self, report: dict[str, object]) -> None:
        self.report = report
        self._render_report(report)
        self.scan_button.configure(state=tk.NORMAL)
        self.save_button.configure(state=tk.NORMAL)

        found, expected = self._count_matches(report)
        self.status.set(
            f"Scan complete: {found} unique matches out of {expected} checks."
        )

    def _render_report(self, report: dict[str, object]) -> None:
        for backend_result in report.get("backend_results", []):
            if not isinstance(backend_result, dict):
                continue

            backend = str(backend_result.get("backend", ""))
            window_status = str(
                backend_result.get("window_status", "unknown")
            )
            controls = backend_result.get("controls", [])

            if window_status != "found":
                self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        backend,
                        "-",
                        "-",
                        "SmartAdvisor window",
                        "scan",
                        window_status,
                        "",
                        "",
                        "",
                    ),
                )
                continue

            if not isinstance(controls, list):
                continue
            for control in controls:
                if not isinstance(control, dict):
                    continue
                self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        backend,
                        control.get("step", ""),
                        control.get("automation_id", ""),
                        control.get("label", ""),
                        control.get("intended_action", ""),
                        control.get("status", ""),
                        control.get("match_strategy", ""),
                        control.get("control_type", ""),
                        control.get("class_name", ""),
                    ),
                )

    @staticmethod
    def _count_matches(report: dict[str, object]) -> tuple[int, int]:
        found = 0
        expected = 0
        for backend_result in report.get("backend_results", []):
            if not isinstance(backend_result, dict):
                continue
            controls = backend_result.get("controls", [])
            if not isinstance(controls, list):
                continue
            for control in controls:
                if not isinstance(control, dict):
                    continue
                expected += 1
                if control.get("status") == "found":
                    found += 1
        return found, expected

    def _save_report(self) -> None:
        if self.report is None:
            return

        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save sanitized control report",
            defaultextension=".json",
            filetypes=[("JSON report", "*.json")],
            initialfile="smartadvisor-control-report.json",
        )
        if not destination:
            return

        try:
            Path(destination).write_text(
                json.dumps(self.report, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showerror(
                "Save failed",
                f"Could not save the report ({type(exc).__name__}).",
                parent=self.root,
            )
            return

        self.status.set("Sanitized report saved.")

    def _clear_rows(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)


def main() -> None:
    root = tk.Tk()
    DiscoveryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
