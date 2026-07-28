from __future__ import annotations

import re
import time
from typing import Any

from smartadvisor_automation.diagnostics import DiagnosticTrace
from smartadvisor_automation.errors import AutomationError
from smartadvisor_automation.models import ControlSpec
from smartadvisor_automation.probe import (
    SUPPORTED_BACKENDS,
    find_direct_uia_control,
    find_open_bill_frame,
    find_smartadvisor_window,
    matching_elements,
)
from smartadvisor_automation.selectors import (
    MAIN_TOOLBAR_AUTOMATION_ID,
    OPEN_BILL_TOOLBAR_BUTTON_TITLE,
    OPEN_BILL_WINDOW_AUTOMATION_ID,
    SMARTADVISOR_WINDOW_AUTOMATION_ID,
)


def open_bill_keyless() -> None:
    """Open the Open Bill dialog through its legacy accessible action."""

    from pywinauto import Desktop

    desktop = Desktop(backend="uia")

    main = desktop.window(
        auto_id=SMARTADVISOR_WINDOW_AUTOMATION_ID,
        control_type="Window",
    )
    main.wait("exists visible enabled", timeout=15)

    toolbar = main.child_window(
        auto_id=MAIN_TOOLBAR_AUTOMATION_ID,
        control_type="ToolBar",
    )
    toolbar.wait("exists visible enabled", timeout=10)

    button = toolbar.child_window(
        title=OPEN_BILL_TOOLBAR_BUTTON_TITLE,
    )
    button.wait("exists visible enabled", timeout=10)

    button_wrapper = button.wrapper_object()
    button_wrapper.iface_legacy_iaccessible.DoDefaultAction()

    dialog = desktop.window(
        auto_id=OPEN_BILL_WINDOW_AUTOMATION_ID,
        control_type="Window",
    )
    try:
        dialog.wait("exists visible enabled", timeout=5)
    except Exception as exc:
        raise RuntimeError(
            "MSAA default action ran, but the Open Bill dialog did not appear."
        ) from exc


class SmartAdvisorDriver:
    """Small pywinauto adapter that resolves every selector before acting."""

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        poll_interval: float = 0.25,
        attach_timeout: float = 6.0,
    ) -> None:
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.attach_timeout = attach_timeout
        self.backend: str | None = None
        self.process_id: int | None = None
        self._landmark_scope: Any | None = None
        self._landmark_automation_id: str | None = None

    def attach(
        self,
        landmark: ControlSpec,
        *,
        timeout: float | None = None,
    ) -> str:
        """Handshake through Open Bill/Frame1, retrying while it renders.

        Open Bill can take a moment to become enumerable (Citrix window
        registration lag) after the user opens it, so this polls the same
        way `resolve()` does rather than giving up after one pass.
        """

        trace = DiagnosticTrace()
        deadline = time.monotonic() + (
            self.attach_timeout if timeout is None else timeout
        )
        saw_smartadvisor_window = False
        saw_open_bill_frame = False
        launch_stage = 0
        attempt = 0

        while True:
            attempt += 1
            if attempt > 1:
                trace.record("attach_attempt", "", "retry", attempt=attempt)

            for backend in SUPPORTED_BACKENDS:
                try:
                    window = find_smartadvisor_window(backend, trace=trace)
                except Exception as exc:
                    trace.record(
                        "main_window_lookup",
                        backend,
                        "raised",
                        exception=type(exc).__name__,
                    )
                    continue
                if window is None:
                    continue
                saw_smartadvisor_window = True

                process_id = getattr(
                    window.element_info, "process_id", None
                )
                if process_id is None:
                    trace.record(
                        "main_window_lookup", backend, "no_process_id"
                    )
                    continue

                try:
                    landmark_scope = find_open_bill_frame(
                        backend, window, trace=trace
                    )
                except Exception as exc:
                    trace.record(
                        "open_bill_frame_lookup",
                        backend,
                        "raised",
                        exception=type(exc).__name__,
                    )
                    continue
                if landmark_scope is None:
                    if backend == "uia":
                        launch_stage = self._try_launch_open_bill(
                            window, launch_stage, trace=trace
                        )
                    continue
                saw_open_bill_frame = True

                direct_landmark = find_direct_uia_control(
                    backend,
                    landmark_scope,
                    landmark.automation_id,
                )
                if direct_landmark is not None:
                    landmark_scope = direct_landmark

                self.backend = backend
                self.process_id = int(process_id)
                self._landmark_scope = landmark_scope
                self._landmark_automation_id = landmark.automation_id
                try:
                    self.resolve(landmark, timeout=2.0)
                except AutomationError as exc:
                    trace.record(
                        "landmark_resolve",
                        backend,
                        "failed",
                        error_code=exc.code,
                    )
                    self.backend = None
                    self.process_id = None
                    self._landmark_scope = None
                    self._landmark_automation_id = None
                    continue
                return backend

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.poll_interval, remaining))

        if not saw_smartadvisor_window:
            code = "smartadvisor_window_not_found"
        elif not saw_open_bill_frame:
            code = "smartadvisor_open_bill_frame_not_accessible"
        else:
            code = "smartadvisor_controls_not_accessible"
        raise AutomationError(
            code, step=landmark.step, diagnostics=trace.to_report()
        )

    def _try_launch_open_bill(
        self,
        main_window: Any,
        launch_stage: int,
        *,
        trace: DiagnosticTrace,
    ) -> int:
        """Try the keyless Open Bill action once, then only poll.

        Repeating the default action while the first dialog is still
        rendering could open a second, ambiguous Open Bill window.
        """

        if launch_stage == 0:
            self._invoke_open_bill_default_action(trace=trace)
            return 1
        return launch_stage

    @staticmethod
    def _invoke_open_bill_default_action(
        *, trace: DiagnosticTrace
    ) -> None:
        """Invoke Open Bill without moving the mouse or typing."""

        stage = "open_bill_launch"
        try:
            open_bill_keyless()
        except Exception as exc:
            trace.record(
                stage,
                "uia",
                "legacy_default_action_failed",
                exception=type(exc).__name__,
            )
            return

        trace.record(stage, "uia", "legacy_default_action_completed")

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

    @staticmethod
    def _elements_in_scope(scope: Any) -> list[Any]:
        elements = [scope]
        try:
            elements.extend(scope.descendants())
        except Exception:
            pass
        return elements

    def _all_elements(self, spec: ControlSpec) -> list[Any]:
        if (
            self._landmark_scope is not None
            and spec.automation_id == self._landmark_automation_id
        ):
            return self._elements_in_scope(self._landmark_scope)

        elements: list[Any] = []
        for window in self._windows_for_process():
            elements.extend(self._elements_in_scope(window))
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
                    self._all_elements(spec), spec.automation_id
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
