from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import SmartAdvisorJob
from .run_control import RunCancelled, RunControl

HelperProgress = Callable[[str, str], None]


class SmartAdvisorHelperError(RuntimeError):
    def __init__(self, code: str, step: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.step = step


def _helper_command() -> list[str]:
    configured = os.environ.get("MITCHEL_SMARTADVISOR_HELPER")
    if configured:
        return [configured]
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        helper = bundle / "SmartAdvisorHelper-x86.exe"
        if not helper.exists():
            raise RuntimeError("embedded_x86_helper_not_found")
        return [str(helper)]
    return [sys.executable, "-m", "mitchel_pipeline.smartadvisor_helper"]


class SmartAdvisorHelperClient:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._write_lock = threading.Lock()

    def start(self) -> None:
        if self._process is not None:
            return
        startup = subprocess.STARTUPINFO() if os.name == "nt" else None
        creationflags = 0
        if startup is not None:
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        self._process = subprocess.Popen(
            _helper_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            startupinfo=startup,
            creationflags=creationflags,
        )
        self._reader = threading.Thread(target=self._read_messages, daemon=True)
        self._reader.start()
        ready = self._next_message(timeout=15)
        if ready.get("type") != "ready" or ready.get("protocol") != 1:
            self.close()
            raise RuntimeError("smartadvisor_helper_not_ready")

    def _read_messages(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            try:
                message = json.loads(line)
                if isinstance(message, dict):
                    self._messages.put(message)
            except json.JSONDecodeError:
                self._messages.put({"type": "error", "code": "invalid_helper_json"})
        self._messages.put({"type": "eof"})

    def _send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("smartadvisor_helper_not_started")
        with self._write_lock:
            self._process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self._process.stdin.flush()

    def _next_message(self, timeout: float) -> dict[str, Any]:
        try:
            return self._messages.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError("smartadvisor_helper_timeout") from exc

    def run_job(
        self,
        job: SmartAdvisorJob,
        control: RunControl,
        progress: HelperProgress,
        *,
        leave_open: bool = True,
    ) -> dict[str, Any]:
        self.start()
        self._send({"type": "run", "job": job.to_dict(), "leave_open": leave_open})
        helper_paused = False
        while True:
            if control.cancelled:
                self._send({"type": "cancel"})
                raise RunCancelled()
            if control.paused != helper_paused:
                helper_paused = control.paused
                self._send({"type": "pause" if helper_paused else "resume"})
            try:
                message = self._messages.get(timeout=0.1)
            except queue.Empty:
                continue
            message_type = message.get("type")
            if message_type == "progress":
                progress(str(message.get("step", "")), str(message.get("message", "")))
            elif message_type == "result":
                return dict(message.get("result") or {})
            elif message_type == "error":
                raise SmartAdvisorHelperError(
                    str(message.get("code") or "smartadvisor_error"),
                    str(message["step"]) if message.get("step") is not None else None,
                )
            elif message_type in {"cancelled", "eof"}:
                raise RunCancelled() if message_type == "cancelled" else RuntimeError("helper_stopped")

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write('{"type":"quit"}\n')
                process.stdin.flush()
            process.wait(timeout=5)
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()
