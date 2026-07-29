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
)

# A scoped selector's container is looked up from the top-level windows, and
# walking every descendant of the whole application costs tens of seconds.
# Every container this workflow scopes to sits within a few levels of a
# top-level window, so cap the walk. Falls back to an unrestricted walk if
# the backend does not support a depth argument.
SCOPE_SEARCH_DEPTH = 4


def _mask_digits(value: str) -> str:
    """Log tab names without their counts, e.g. " &Lines(10)" -> Lines(##)."""

    return re.sub(r"\d", "#", value)


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

        Never pass field values here: the log is shown in the UI and can be
        saved to disk, so it carries selector metadata and outcomes only.
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
        wanted = expected_fragment.casefold()

        start = self._element_name(element)
        if wanted in start.casefold():
            self._log(
                f"tab {self._describe(spec)} already on "
                f"{_mask_digits(start)}"
            )
            return
        self._log(
            f"tab {self._describe(spec)} starts on {_mask_digits(start)}"
        )

        for attempt in ("accelerator", "click_then_arrow", "fallback_key"):
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
        self._log(f"tab after accelerator: {_mask_digits(name)}")
        return wanted in name.casefold()

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
            if wanted in before.casefold():
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
            self._log(f"tab after {key}: {_mask_digits(name)}")
            if wanted in name.casefold():
                return True
            if name == before:
                # The keystroke moved nothing, so more of them will not help.
                self._log(f"tab unchanged by {key}")
                return False

        return False

    def is_present(
        self,
        spec: ControlSpec,
        *,
        timeout: float = 1.5,
    ) -> bool:
        """Check for an optional control without failing when it is absent."""

        try:
            self.resolve(spec, timeout=timeout)
        except AutomationError:
            self._log(f"optional {self._describe(spec)} absent")
            return False
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
