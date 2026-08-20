from __future__ import annotations

import threading


class RunCancelled(RuntimeError):
    """Raised at a cooperative checkpoint after cancellation."""


class RunControl:
    """Thread-safe pause, resume, and cancellation state."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._running = threading.Event()
        self._running.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set() and not self.cancelled

    def pause(self) -> None:
        if not self.cancelled:
            self._running.clear()

    def resume(self) -> None:
        if not self.cancelled:
            self._running.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._running.set()

    def checkpoint(self, timeout: float = 0.1) -> None:
        """Wait while paused, then raise if cancellation was requested."""

        while not self._running.wait(timeout):
            if self.cancelled:
                raise RunCancelled()
        if self.cancelled:
            raise RunCancelled()

    def wait_for_resume(self) -> None:
        self.checkpoint()


class WorkflowCancelAdapter:
    """Adapt RunControl to SmartAdvisor's threading.Event-like contract."""

    def __init__(self, control: RunControl) -> None:
        self.control = control

    def is_set(self) -> bool:
        try:
            self.control.checkpoint()
        except RunCancelled:
            return True
        return False
