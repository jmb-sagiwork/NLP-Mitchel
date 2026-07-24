from __future__ import annotations

import re
import time
from typing import Any

from smartadvisor_automation.errors import AutomationError
from smartadvisor_automation.models import ControlSpec
from smartadvisor_automation.probe import (
    SUPPORTED_BACKENDS,
    find_smartadvisor_window,
    matching_elements,
)


class SmartAdvisorDriver:
    """Small pywinauto adapter that resolves every selector before acting."""

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.backend: str | None = None
        self.process_id: int | None = None

    def attach(self, landmark: ControlSpec) -> str:
        """Select the first backend that exposes the starting landmark."""

        saw_smartadvisor_window = False

        for backend in SUPPORTED_BACKENDS:
            try:
                window = find_smartadvisor_window(backend)
            except Exception:
                continue
            if window is None:
                continue
            saw_smartadvisor_window = True

            process_id = getattr(window.element_info, "process_id", None)
            if process_id is None:
                continue

            self.backend = backend
            self.process_id = int(process_id)
            try:
                self.resolve(landmark, timeout=2.0)
            except AutomationError:
                self.backend = None
                self.process_id = None
                continue
            return backend

        code = (
            "smartadvisor_controls_not_accessible"
            if saw_smartadvisor_window
            else "smartadvisor_window_not_found"
        )
        raise AutomationError(code, step=landmark.step)

    def _windows_for_process(self) -> list[Any]:
        if self.backend is None or self.process_id is None:
            raise AutomationError("not_attached")

        from pywinauto import Desktop

        try:
            return list(
                Desktop(backend=self.backend).windows(
                    process=self.process_id,
                    visible_only=True,
                    enabled_only=False,
                )
            )
        except Exception as exc:
            raise AutomationError("window_enumeration_failed") from exc

    def _all_elements(self) -> list[Any]:
        elements: list[Any] = []
        for window in self._windows_for_process():
            elements.append(window)
            try:
                elements.extend(window.descendants())
            except Exception:
                continue
        return elements

    def resolve(
        self,
        spec: ControlSpec,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Wait for exactly one visible, enabled selector match."""

        deadline = time.monotonic() + (
            self.timeout if timeout is None else timeout
        )
        last_match_count = 0

        while time.monotonic() < deadline:
            try:
                matches = matching_elements(
                    self._all_elements(), spec.automation_id
                )
            except AutomationError:
                raise
            except Exception:
                matches = []

            actionable = [
                element
                for element, _strategy in matches
                if self._safe_state(element, "is_visible")
                and self._safe_state(element, "is_enabled")
            ]
            last_match_count = len(actionable)
            if last_match_count == 1:
                return actionable[0]

            time.sleep(self.poll_interval)

        code = (
            "selector_ambiguous"
            if last_match_count > 1
            else "selector_not_found"
        )
        raise AutomationError(code, step=spec.step)

    @staticmethod
    def _safe_state(element: Any, method_name: str) -> bool:
        try:
            return bool(getattr(element, method_name)())
        except Exception:
            return False

    def click(self, spec: ControlSpec) -> None:
        element = self.resolve(spec)
        try:
            element.set_focus()
            element.click_input()
        except Exception as exc:
            raise AutomationError("click_failed", step=spec.step) from exc

    def clear(self, spec: ControlSpec) -> None:
        element = self.resolve(spec)
        try:
            element.set_focus()
            element.click_input()
            element.type_keys("^a{BACKSPACE}", set_foreground=True)
        except Exception as exc:
            raise AutomationError("clear_failed", step=spec.step) from exc

    def input_text(self, spec: ControlSpec, value: str) -> None:
        element = self.resolve(spec)
        try:
            element.set_edit_text(value)
            return
        except Exception:
            pass

        try:
            element.set_focus()
            element.click_input()
            element.type_keys("^a{BACKSPACE}", set_foreground=True)
            element.type_keys(
                value,
                with_spaces=True,
                set_foreground=True,
            )
        except Exception as exc:
            raise AutomationError("input_failed", step=spec.step) from exc

    def read_text(self, spec: ControlSpec) -> str:
        element = self.resolve(spec)
        candidates: list[str] = []

        try:
            candidates.append(str(element.window_text() or ""))
        except Exception:
            pass

        try:
            candidates.extend(str(value or "") for value in element.texts())
        except Exception:
            pass

        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate).strip()
            if normalized:
                return normalized

        raise AutomationError("empty_extracted_value", step=spec.step)
