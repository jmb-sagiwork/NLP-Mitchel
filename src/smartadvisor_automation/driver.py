from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from smartadvisor_automation.diagnostics import DiagnosticTrace
from smartadvisor_automation.errors import AutomationError
from smartadvisor_automation.models import ControlSpec
from smartadvisor_automation.probe import (
    SUPPORTED_BACKENDS,
    find_bill_search_frame,
    find_direct_uia_control,
    find_open_bill_frame,
    find_smartadvisor_window,
    matching_elements,
    matching_spec_elements,
)
from smartadvisor_automation.selectors import (
    BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS,
    GRID_FIRST_ROW_CLICK_Y,
    GRID_ROW_CLICK_X,
    GRID_ROW_HEIGHT,
    PRINT_EOR_DUPLICATE_NO_KEY,
    PRINT_EOR_DUPLICATE_SELECTION_TEXT,
    RAD_MESSAGEBOX_AUTOMATION_ID,
    SAVE_AS_OVERWRITE_TEXTS,
    SAVE_AS_OVERWRITE_YES_KEY,
    SMARTADVISOR_EXCEPTION_CONTINUE_BUTTON_NAME,
    SMARTADVISOR_UNHANDLED_EXCEPTION_TEXT,
)

# A scoped selector's container is looked up from the top-level windows.
# Keep this as shallow as the containers allow: a live run resolved
# frmBillEntry in 28s having scanned only 64 elements, so the cost is per
# element -- roughly 440ms for one COM property read over Citrix -- not tree
# size. frmBillEntry sits two levels below the main window (an anonymous pane
# in between), so two is enough. Falls back to an unrestricted walk if the
# backend does not support a depth argument.
SCOPE_SEARCH_DEPTH = 2


def _write_clipboard_text(value: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(value)
    finally:
        win32clipboard.CloseClipboard()


class SmartAdvisorDriver:
    """Small pywinauto adapter that resolves every selector before acting."""

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        poll_interval: float = 0.25,
        attach_timeout: float = 6.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.attach_timeout = attach_timeout
        self.backend: str | None = None
        self.process_id: int | None = None
        self._landmark_scope: Any | None = None
        self._landmark_automation_id: str | None = None
        self._log_callback = log
        self._scope_cache: dict[str, Any] = {}

    def _log(self, message: str) -> None:
        """Record a selector-level debug line.

        Driver lines carry selector metadata and outcomes. The workflow also
        logs amount values by decision, so a saved log is sensitive; see the
        privacy note in `recentconvo.md`.
        """

        if self._log_callback is not None:
            self._log_callback(message)

    @staticmethod
    def _describe(spec: ControlSpec) -> str:
        if spec.automation_id:
            described = spec.automation_id
        else:
            described = f"name={spec.name!r}"
        if spec.scope_automation_id:
            described = f"{spec.scope_automation_id}/{described}"
        return described

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
        """Send Ctrl+O once, then only poll for the modal Open Bill window."""

        if launch_stage == 0:
            self._send_open_bill_shortcut(main_window, trace=trace)
            return 1
        return launch_stage

    @staticmethod
    def _send_open_bill_shortcut(
        main_window: Any, *, trace: DiagnosticTrace
    ) -> None:
        """Send the application's Ctrl+O Open Bill accelerator once."""

        stage = "open_bill_launch"
        try:
            main_window.set_focus()
            main_window.type_keys("^o")
        except Exception as exc:
            trace.record(
                stage,
                "uia",
                "shortcut_failed",
                exception=type(exc).__name__,
            )
            return

        trace.record(stage, "uia", "shortcut_sent")

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

    def _desktop_windows(self) -> list[Any]:
        if self.backend is None:
            raise AutomationError("not_attached")

        from pywinauto import Desktop

        try:
            return list(
                Desktop(backend=self.backend).windows(
                    visible_only=True,
                    enabled_only=False,
                )
            )
        except Exception as exc:
            raise AutomationError("window_enumeration_failed") from exc

    def _find_window_by_title(
        self,
        title: str,
        *,
        timeout: float,
    ) -> Any | None:
        expected = title.strip().casefold()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            matches = []
            for window in self._desktop_windows():
                name = self._element_name(window).strip().casefold()
                if name == expected:
                    matches.append(window)

            visible_matches = [
                window
                for window in matches
                if self._safe_state(window, "is_visible")
            ]
            if visible_matches:
                enabled_matches = [
                    window
                    for window in visible_matches
                    if self._safe_state(window, "is_enabled")
                ]
                return (enabled_matches or visible_matches)[0]

            time.sleep(self.poll_interval)

        return None

    def wait_for_window_title(self, title: str, *, timeout: float) -> bool:
        started = time.perf_counter()
        window = self._find_window_by_title(title, timeout=timeout)
        if window is None:
            self._log(
                f"global window {title!r} absent "
                f"elapsed={time.perf_counter() - started:.3f}s"
            )
            return False
        self._log(
            f"global window {title!r} present "
            f"elapsed={time.perf_counter() - started:.3f}s"
        )
        return True

    def focus_window_title(self, title: str, *, timeout: float) -> None:
        started = time.perf_counter()
        window = self._find_window_by_title(title, timeout=timeout)
        if window is None:
            raise AutomationError("window_not_found")
        try:
            window.set_focus()
        except Exception as exc:
            raise AutomationError("focus_failed") from exc
        self._log(
            f"focus-window {title!r} "
            f"elapsed={time.perf_counter() - started:.3f}s"
        )

    def click_child_in_window_title(
        self,
        title: str,
        spec: ControlSpec,
        *,
        timeout: float,
    ) -> None:
        started = time.perf_counter()
        window = self._find_window_by_title(title, timeout=timeout)
        if window is None:
            raise AutomationError("window_not_found", step=spec.step)

        candidates = self._elements_in_scope(
            window,
            depth=spec.search_depth,
        )
        matches = matching_spec_elements(candidates, spec)
        actionable = [
            element
            for element, _strategy in matches
            if self._safe_state(element, "is_visible")
            and self._safe_state(element, "is_enabled")
        ]
        if len(actionable) != 1:
            code = (
                "selector_ambiguous"
                if len(actionable) > 1
                else "selector_not_found"
            )
            self._log(
                f"resolve {title!r}/{self._describe(spec)} -> {code} "
                f"(matches={len(actionable)})"
            )
            raise AutomationError(code, step=spec.step)

        element = actionable[0]
        try:
            try:
                window.set_focus()
            except Exception:
                pass
            element.click_input()
        except Exception as exc:
            raise AutomationError("click_failed", step=spec.step) from exc
        self._log(
            f"click-window-child {title!r}/{self._describe(spec)} "
            f"elapsed={time.perf_counter() - started:.3f}s"
        )

    @staticmethod
    def _elements_in_scope(
        scope: Any, *, depth: int | None = None
    ) -> list[Any]:
        elements = [scope]
        if depth is not None:
            try:
                elements.extend(scope.descendants(depth=depth))
                return elements
            except Exception:
                # Backend without depth support; fall through to a full walk.
                pass

        try:
            elements.extend(scope.descendants())
        except Exception:
            pass
        return elements

    def invalidate_scopes(self) -> None:
        """Forget cached containers.

        Each candidate row opens a fresh bill window, so a cached handle from
        the previous row must not be reused.
        """

        self._scope_cache.clear()

    def _find_scope(self, scope_automation_id: str) -> Any | None:
        """Resolve the single container a scoped selector searches inside.

        Cached, because resolving a container means walking top-level window
        subtrees and the same container is used by several steps in a row.
        """

        cached = self._scope_cache.get(scope_automation_id)
        if cached is not None and self._safe_state(cached, "is_visible"):
            return cached

        started = time.monotonic()
        candidates: list[Any] = []
        for window in self._windows_for_process():
            candidates.extend(
                self._elements_in_scope(window, depth=SCOPE_SEARCH_DEPTH)
            )

        matches = matching_elements(candidates, scope_automation_id)
        actionable = [
            element
            for element, _strategy in matches
            if self._safe_state(element, "is_visible")
        ]
        elapsed = time.monotonic() - started
        if len(actionable) != 1:
            self._scope_cache.pop(scope_automation_id, None)
            self._log(
                f"scope {scope_automation_id} not resolved in {elapsed:.1f}s "
                f"(matches={len(actionable)}, scanned={len(candidates)})"
            )
            return None

        self._scope_cache[scope_automation_id] = actionable[0]
        self._log(
            f"scope {scope_automation_id} resolved in {elapsed:.1f}s "
            f"(scanned={len(candidates)})"
        )
        return actionable[0]

    def _all_elements(self, spec: ControlSpec) -> list[Any]:
        if (
            self._landmark_scope is not None
            and spec.automation_id
            and spec.automation_id == self._landmark_automation_id
        ):
            return self._elements_in_scope(self._landmark_scope)

        if spec.scope_automation_id:
            scope = self._find_scope(spec.scope_automation_id)
            if scope is None:
                return []
            return self._elements_in_scope(scope)

        if spec.automation_id in BILL_SEARCH_FRAME_CONTROL_AUTOMATION_IDS:
            frame = find_bill_search_frame(
                self.backend or "",
                self._windows_for_process(),
            )
            if frame is None:
                return []
            return self._elements_in_scope(frame)

        elements: list[Any] = []
        for window in self._windows_for_process():
            elements.extend(
                self._elements_in_scope(window, depth=spec.search_depth)
            )
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
                matches = matching_spec_elements(
                    self._all_elements(spec), spec
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
        self._log(
            f"resolve {self._describe(spec)} -> {code} "
            f"(matches={last_match_count})"
        )
        raise AutomationError(code, step=spec.step)

    def resolve_visible(
        self,
        spec: ControlSpec,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Resolve one visible control even when SmartAdvisor disables it."""

        deadline = time.monotonic() + (
            self.timeout if timeout is None else timeout
        )
        last_match_count = 0
        while time.monotonic() < deadline:
            try:
                matches = matching_spec_elements(self._all_elements(spec), spec)
            except AutomationError:
                raise
            except Exception:
                matches = []

            actionable = [
                element
                for element, _strategy in matches
                if self._safe_state(element, "is_visible")
            ]
            last_match_count = len(actionable)
            if last_match_count == 1:
                return actionable[0]
            time.sleep(self.poll_interval)

        code = "selector_ambiguous" if last_match_count > 1 else "selector_not_found"
        self._log(
            f"resolve-visible {self._describe(spec)} -> {code} "
            f"(matches={last_match_count})"
        )
        raise AutomationError(code, step=spec.step)

    @staticmethod
    def _safe_state(element: Any, method_name: str) -> bool:
        try:
            return bool(getattr(element, method_name)())
        except Exception:
            return False

    @staticmethod
    def _clamp_control_x(element: Any, x: int) -> int:
        try:
            rect = element.rectangle()
            width = int(rect.right - rect.left)
        except Exception:
            return max(1, x)
        if width <= 2:
            return max(1, x)
        return max(1, min(int(x), width - 2))

    def click(self, spec: ControlSpec) -> None:
        element = self.resolve(spec)
        try:
            element.set_focus()
            element.click_input()
        except Exception as exc:
            raise AutomationError("click_failed", step=spec.step) from exc
        self._log(f"click {self._describe(spec)}")

    def focus_grid(self, spec: ControlSpec) -> None:
        """Put keyboard focus inside the owner-drawn results grid.

        Arrow navigation only works once focus is genuinely inside the pane,
        and a real click is the only reliable way in. Where the click lands
        does not matter: the caller's calibration nudge normalises the
        selection onto the topmost row afterwards.
        """

        element = self.resolve(spec)
        try:
            element.set_focus()
        except Exception:
            # click_input() can still put focus inside an unfocused pane.
            pass

        try:
            element.click_input()
        except Exception as exc:
            raise AutomationError("focus_failed", step=spec.step) from exc
        self._log(f"focus {self._describe(spec)}")

    def click_grid_row(
        self,
        spec: ControlSpec,
        row_index: int,
        *,
        first_row_y: int = GRID_FIRST_ROW_CLICK_Y,
    ) -> None:
        """Select a FarPoint search-result row with a real mouse click."""

        element = self.resolve(spec)
        row_y = first_row_y + (GRID_ROW_HEIGHT * row_index)
        try:
            element.set_focus()
        except Exception:
            pass
        click_x = self._clamp_control_x(element, GRID_ROW_CLICK_X)
        try:
            element.click_input(coords=(click_x, row_y))
        except Exception as exc:
            raise AutomationError("row_click_failed", step=spec.step) from exc
        self.acknowledge_smartadvisor_exception_popup(timeout=0.5)
        self._log(
            f"click-row {self._describe(spec)} row={row_index} "
            f"coords=({click_x},{row_y})"
        )

    def click_at(self, spec: ControlSpec, *, x: int, y: int) -> None:
        """Click a fixed point inside an owner-drawn SmartAdvisor control."""

        element = self.resolve(spec)
        try:
            element.set_focus()
        except Exception:
            pass
        click_x = self._clamp_control_x(element, x)
        try:
            element.click_input(coords=(click_x, y))
        except Exception as exc:
            raise AutomationError("click_at_failed", step=spec.step) from exc
        self.acknowledge_smartadvisor_exception_popup(timeout=0.5)
        self._log(f"click-at {self._describe(spec)} coords=({click_x},{y})")

    def acknowledge_smartadvisor_exception_popup(
        self,
        *,
        timeout: float = 1.0,
    ) -> bool:
        """Click Continue on SmartAdvisor's .NET exception dialog."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                windows = self._windows_for_process()
            except AutomationError:
                return False

            for window in windows:
                elements = self._elements_in_scope(window, depth=5)
                has_exception_text = any(
                    SMARTADVISOR_UNHANDLED_EXCEPTION_TEXT.casefold()
                    in self._element_name(element).casefold()
                    for element in elements
                )
                if not has_exception_text:
                    continue

                for element in elements:
                    info = getattr(element, "element_info", None)
                    control_type = str(
                        getattr(info, "control_type", "") or ""
                    ).casefold()
                    name = self._element_name(element).strip().replace("&", "")
                    if (
                        control_type == "button"
                        and name.casefold()
                        == SMARTADVISOR_EXCEPTION_CONTINUE_BUTTON_NAME.casefold()
                    ):
                        try:
                            element.click_input()
                        except Exception as exc:
                            raise AutomationError(
                                "smartadvisor_exception_continue_failed"
                            ) from exc
                        self._log(
                            "acknowledged SmartAdvisor exception popup with Continue"
                        )
                        return True

                try:
                    window.set_focus()
                    window.type_keys("{ENTER}", set_foreground=True)
                except Exception as exc:
                    raise AutomationError(
                        "smartadvisor_exception_continue_failed"
                    ) from exc
                self._log("acknowledged SmartAdvisor exception popup with Enter")
                return True

            time.sleep(self.poll_interval)
        return False

    def acknowledge_duplicate_selection_popup(
        self,
        *,
        timeout: float = 2.0,
    ) -> bool:
        """Answer No when Print EOR says the bill is already selected."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for window in self._windows_for_process():
                elements = self._elements_in_scope(window, depth=4)
                message_boxes = [
                    element
                    for element in elements
                    if str(
                        getattr(element.element_info, "automation_id", "") or ""
                    )
                    == RAD_MESSAGEBOX_AUTOMATION_ID
                ]
                for message_box in message_boxes:
                    message_elements = self._elements_in_scope(
                        message_box, depth=3
                    )
                    has_duplicate_text = any(
                        PRINT_EOR_DUPLICATE_SELECTION_TEXT.casefold()
                        in self._element_name(element).casefold()
                        for element in message_elements
                    )
                    if not has_duplicate_text:
                        continue

                    for element in message_elements:
                        info = element.element_info
                        control_type = str(
                            getattr(info, "control_type", "") or ""
                        ).casefold()
                        name = self._element_name(element).replace("&", "")
                        if control_type == "button" and name == "No":
                            try:
                                element.click_input()
                            except Exception as exc:
                                raise AutomationError(
                                    "duplicate_selection_ack_failed",
                                    step="8.3",
                                ) from exc
                            self._log(
                                "acknowledged duplicate selection popup with No"
                            )
                            return True

                    self.send_focused_keys(
                        PRINT_EOR_DUPLICATE_NO_KEY,
                        step="8.3",
                    )
                    self._log(
                        "acknowledged duplicate selection popup with Alt+N"
                    )
                    return True

            time.sleep(self.poll_interval)

        return False

    def acknowledge_save_as_overwrite_popup(
        self,
        *,
        timeout: float = 3.0,
    ) -> bool:
        """Answer Yes when Windows asks to overwrite an existing PDF."""

        from pywinauto import Desktop

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            windows: list[Any] = []
            try:
                windows.extend(self._windows_for_process())
            except AutomationError:
                pass
            try:
                windows.extend(
                    Desktop(backend=self.backend).windows(
                        visible_only=True,
                        enabled_only=False,
                    )
                )
            except Exception:
                pass

            seen_handles: set[int] = set()
            for window in windows:
                try:
                    handle = int(window.handle)
                except Exception:
                    handle = 0
                if handle and handle in seen_handles:
                    continue
                if handle:
                    seen_handles.add(handle)

                elements = self._elements_in_scope(window, depth=4)
                text = " ".join(
                    self._element_name(element)
                    for element in elements
                    if self._element_name(element)
                ).casefold()
                if not any(
                    phrase.casefold() in text
                    for phrase in SAVE_AS_OVERWRITE_TEXTS
                ):
                    continue

                for element in elements:
                    info = element.element_info
                    control_type = str(
                        getattr(info, "control_type", "") or ""
                    ).casefold()
                    name = self._element_name(element).replace("&", "")
                    if control_type == "button" and name.casefold() == "yes":
                        try:
                            element.click_input()
                        except Exception as exc:
                            raise AutomationError(
                                "save_as_overwrite_ack_failed",
                                step="9.1",
                            ) from exc
                        self._log(
                            "acknowledged existing PDF overwrite with Yes"
                        )
                        return True

                self.send_focused_keys(
                    SAVE_AS_OVERWRITE_YES_KEY,
                    step="9.1",
                )
                self._log(
                    "acknowledged existing PDF overwrite with Alt+Y"
                )
                return True

            time.sleep(self.poll_interval)

        return False

    def send_keys(self, spec: ControlSpec, keys: str) -> None:
        """Type into an already-focused control without re-clicking it."""

        if not keys:
            return

        element = self.resolve(spec)
        try:
            element.type_keys(keys, set_foreground=True)
        except Exception as exc:
            raise AutomationError("send_keys_failed", step=spec.step) from exc
        self._log(f"keys {self._describe(spec)} {keys}")

    def send_focused_keys(self, keys: str, *, step: str) -> None:
        """Type into whichever SmartAdvisor control currently owns focus."""

        if not keys:
            return
        try:
            from pywinauto.keyboard import send_keys

            send_keys(keys)
        except Exception as exc:
            raise AutomationError("send_keys_failed", step=step) from exc
        self._log(f"keys focused {keys}")

    def paste_focused_text(self, value: str, *, step: str) -> None:
        """Paste literal text into the focused control via the clipboard."""

        if not value:
            return

        started = time.perf_counter()
        try:
            _write_clipboard_text(value)
            from pywinauto.keyboard import send_keys

            send_keys("^v")
        except Exception as exc:
            raise AutomationError("paste_failed", step=step) from exc
        self._log(
            f"paste focused text len={len(value)} "
            f"elapsed={time.perf_counter() - started:.3f}s"
        )

    @staticmethod
    def _element_name(element: Any) -> str:
        try:
            return str(element.window_text() or "").strip()
        except Exception:
            return ""

    def _wait_for_tab_name(
        self,
        element: Any,
        *,
        wanted: str,
        differs_from: str,
        timeout: float,
    ) -> str:
        """Poll the tab control's Name until it changes or the wait expires.

        The Name is read live from the provider, so it is a reliable signal —
        but the app needs time to repaint, and over Citrix that is not
        instant. Reading immediately after a keystroke sees the old page and
        makes a working keystroke look like a no-op.
        """

        deadline = time.monotonic() + timeout
        name = self._element_name(element)
        while True:
            if wanted in name.casefold() or name != differs_from:
                return name
            if time.monotonic() >= deadline:
                return name
            time.sleep(self.poll_interval)
            name = self._element_name(element)

    def _click_tab_strip(self, element: Any) -> bool:
        """Click the tab strip so arrow keys reach it.

        The strip band is derived from the control's own rectangle and its
        page's rectangle rather than hardcoded, then the leftmost tab is
        clicked. Selecting whichever tab is leftmost is harmless: the caller
        arrows on from wherever it lands and verifies by Name.
        """

        try:
            rect = element.rectangle()
            strip_height = 24
            children = element.children()
            if children:
                page_top = children[0].rectangle().top
                derived = page_top - rect.top
                if 8 <= derived <= 80:
                    strip_height = derived
            element.click_input(coords=(30, max(4, strip_height // 2)))
        except Exception:
            return False
        return True

    def select_tab(
        self,
        spec: ControlSpec,
        *,
        expected_fragment: str,
        accelerator: str,
        next_key: str,
        fallback_key: str,
        max_presses: int,
        settle_timeout: float,
    ) -> None:
        """Bring a tab page to the front, verifying by the control's Name.

        This control publishes only the selected page's children, so the
        wanted controls do not exist until the switch has actually happened —
        an unverified keystroke is worthless here.

        Which mechanism works has not been pinned down: the "&L" in the tab
        text is a rendered underline and the control reports no AccessKey,
        yet the accelerator appears to do something; arrowing needs the strip
        to hold focus, which it may not after a dialog. So each mechanism is
        tried in turn and the one that worked is logged, rather than assumed.
        """

        element = self.resolve(spec)
        wanted = self._normalize_tab_name(expected_fragment)

        start = self._element_name(element)
        if wanted in self._normalize_tab_name(start):
            self._log(
                f"tab {self._describe(spec)} already on "
                f"{start}"
            )
            return
        self._log(
            f"tab {self._describe(spec)} starts on {start}"
        )

        for attempt in (
            "accelerator",
            "click_then_arrow",
            "scan_clicks",
            "fallback_key",
        ):
            if attempt == "accelerator":
                worked = self._tab_by_accelerator(
                    element,
                    accelerator=accelerator,
                    wanted=wanted,
                    settle_timeout=settle_timeout,
                )
            elif attempt == "click_then_arrow":
                worked = self._tab_by_keypresses(
                    element,
                    key=next_key,
                    wanted=wanted,
                    max_presses=max_presses,
                    settle_timeout=settle_timeout,
                    click_strip_first=True,
                )
            elif attempt == "scan_clicks":
                worked = self._tab_by_scan_clicks(
                    element,
                    wanted=wanted,
                    settle_timeout=settle_timeout,
                )
            else:
                worked = self._tab_by_keypresses(
                    element,
                    key=fallback_key,
                    wanted=wanted,
                    max_presses=max_presses,
                    settle_timeout=settle_timeout,
                    click_strip_first=False,
                )

            if worked:
                self._log(f"tab reached via {attempt}")
                return
            self._log(f"tab {attempt} did not reach {expected_fragment!r}")

        raise AutomationError("tab_not_found", step=spec.step)

    @staticmethod
    def _normalize_tab_name(name: str) -> str:
        return re.sub(r"[&\s]+", "", name).casefold()

    def _tab_by_accelerator(
        self,
        element: Any,
        *,
        accelerator: str,
        wanted: str,
        settle_timeout: float,
    ) -> bool:
        before = self._element_name(element)
        try:
            element.type_keys(accelerator, set_foreground=True)
        except Exception:
            return False

        name = self._wait_for_tab_name(
            element,
            wanted=wanted,
            differs_from=before,
            timeout=settle_timeout,
        )
        self._log(f"tab after accelerator: {name}")
        return wanted in self._normalize_tab_name(name)

    def _tab_by_keypresses(
        self,
        element: Any,
        *,
        key: str,
        wanted: str,
        max_presses: int,
        settle_timeout: float,
        click_strip_first: bool,
    ) -> bool:
        if click_strip_first and not self._click_tab_strip(element):
            self._log("tab strip click failed")
            return False

        try:
            element.set_focus()
        except Exception:
            # The strip may already hold focus; the click above also grants it.
            pass

        seen: set[str] = set()
        for _press in range(max_presses):
            before = self._element_name(element)
            if wanted in self._normalize_tab_name(before):
                return True
            if before and before in seen:
                self._log(f"tab strip cycled using {key}")
                return False
            seen.add(before)

            try:
                element.type_keys(key, set_foreground=True)
            except Exception:
                return False

            name = self._wait_for_tab_name(
                element,
                wanted=wanted,
                differs_from=before,
                timeout=settle_timeout,
            )
            self._log(f"tab after {key}: {name}")
            if wanted in self._normalize_tab_name(name):
                return True
            if name == before:
                # The keystroke moved nothing, so more of them will not help.
                self._log(f"tab unchanged by {key}")
                return False

        return False

    def _tab_by_scan_clicks(
        self,
        element: Any,
        *,
        wanted: str,
        settle_timeout: float,
    ) -> bool:
        """Click across the visible tab strip and verify the selected page.

        Some SmartAdvisor/Citrix sessions stop honoring RIGHT/CTRL+TAB after a
        tab page loads, even though the target tab is visibly present. The tab
        control does not expose individual tab items, so scanning the strip
        with relative coordinates is the most stable fallback that still
        verifies success from the control's own Name.
        """

        try:
            rect = element.rectangle()
            strip_height = 24
            children = element.children()
            if children:
                page_top = children[0].rectangle().top
                derived = page_top - rect.top
                if 8 <= derived <= 80:
                    strip_height = derived
            width = max(0, rect.right - rect.left)
        except Exception:
            return False

        if width < 80:
            return False

        y = max(4, strip_height // 2)
        max_x = max(40, min(width - 20, 1050))
        candidates = list(range(35, max_x + 1, 55))
        if max_x not in candidates:
            candidates.append(max_x)

        before = self._element_name(element)
        for x in candidates:
            try:
                element.click_input(coords=(x, y))
            except Exception:
                continue

            name = self._wait_for_tab_name(
                element,
                wanted=wanted,
                differs_from=before,
                timeout=max(settle_timeout, 1.5),
            )
            self._log(f"tab after scan click x={x}: {name}")
            if wanted in self._normalize_tab_name(name):
                return True
            before = name

        return False

    def is_present(
        self,
        spec: ControlSpec,
        *,
        timeout: float = 1.5,
    ) -> bool:
        """Check for an optional control without failing when it is absent."""

        try:
            element = self.resolve(spec, timeout=timeout)
        except AutomationError:
            self._log(f"optional {self._describe(spec)} absent")
            return False
        if (
            spec.automation_id
            and str(spec.control_type or "").casefold() == "window"
        ):
            self._scope_cache[spec.automation_id] = element
        self._log(f"optional {self._describe(spec)} present")
        return True

    def invoke(self, spec: ControlSpec) -> None:
        """Invoke a UIA control without moving the mouse."""

        element = self.resolve(spec)
        try:
            element.iface_invoke.Invoke()
        except Exception as exc:
            raise AutomationError("invoke_failed", step=spec.step) from exc

    def click_with_invoke_fallback(
        self,
        spec: ControlSpec,
        confirmation_spec: ControlSpec,
        *,
        confirmation_timeout: float = 2.0,
    ) -> None:
        """Click with real mouse input, then invoke if no result appears."""

        element = self.resolve(spec)
        try:
            element.set_focus()
        except Exception:
            # click_input() can still activate an unfocused control.
            pass

        try:
            element.click_input()
        except Exception:
            pass
        else:
            try:
                self.resolve(
                    confirmation_spec,
                    timeout=confirmation_timeout,
                )
                return
            except AutomationError:
                # The click completed but did not expose the expected control.
                pass

        try:
            element.iface_invoke.Invoke()
        except Exception as exc:
            raise AutomationError(
                "click_and_invoke_failed",
                step=spec.step,
            ) from exc

    def clear(self, spec: ControlSpec) -> None:
        element = self.resolve(spec)
        try:
            element.set_edit_text("")
            return
        except Exception:
            pass

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

    def input_child_edit_text(self, spec: ControlSpec, value: str) -> None:
        """Type into an edit's inner WinForms EDIT child when one exists."""

        parent = self.resolve(spec)
        target = parent
        try:
            children = parent.descendants(depth=1)
        except Exception:
            try:
                children = parent.children()
            except Exception:
                children = []

        for child in children:
            info = getattr(child, "element_info", None)
            control_type = str(
                getattr(info, "control_type", "") or ""
            ).casefold()
            if (
                control_type == "edit"
                and self._safe_state(child, "is_visible")
                and self._safe_state(child, "is_enabled")
            ):
                target = child
                break

        try:
            target.set_focus()
            target.click_input()
        except Exception:
            pass

        try:
            target.set_edit_text(value)
            self._log(f"input-child {self._describe(spec)} {value}")
            return
        except Exception:
            pass

        try:
            target.type_keys("^a{BACKSPACE}", set_foreground=True)
            target.type_keys(
                value,
                with_spaces=True,
                set_foreground=True,
            )
        except Exception as exc:
            raise AutomationError("input_child_failed", step=spec.step) from exc
        self._log(f"keys-child {self._describe(spec)} {value}")

    def scan_texts(
        self,
        scope_automation_id: str,
        prefix: str,
    ) -> list[tuple[str, str]]:
        """Read every control in a scope whose AutomationId starts with prefix.

        Diagnostic only, and slow: it touches every element in the subtree at
        Citrix COM latency. Used to find which control-array index actually
        holds a wanted value when the index turns out to be positional.
        """

        scope = self._find_scope(scope_automation_id)
        if scope is None:
            return []

        started = time.monotonic()
        found: list[tuple[str, str]] = []
        for element in self._elements_in_scope(scope):
            info = getattr(element, "element_info", None)
            if info is None:
                continue
            automation_id = str(getattr(info, "automation_id", "") or "")
            if not automation_id.startswith(prefix):
                continue
            try:
                text = str(element.window_text() or "")
            except Exception:
                continue
            found.append((automation_id, text))

        elapsed = time.monotonic() - started
        self._log(
            f"scan {prefix}* in {scope_automation_id}: "
            f"{len(found)} control(s) in {elapsed:.1f}s"
        )
        return found

    def read_text(
        self,
        spec: ControlSpec,
        *,
        timeout: float | None = None,
    ) -> str:
        try:
            element = self.resolve(spec, timeout=timeout)
        except AutomationError:
            if spec.action != "extract":
                raise
            element = self.resolve_visible(spec, timeout=timeout)
        candidates: list[str] = []

        try:
            candidates.append(str(element.get_value() or ""))
        except Exception:
            pass

        try:
            candidates.append(str(element.iface_value.CurrentValue or ""))
        except Exception:
            pass

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
