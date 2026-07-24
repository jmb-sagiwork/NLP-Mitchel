from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from smartadvisor_automation.models import ControlSpec, ProbeResult
from smartadvisor_automation.selectors import (
    NO_BILL_ON_FILE_CONTROLS,
    SMARTADVISOR_WINDOW_CLASS_PREFIX,
    SMARTADVISOR_WINDOW_TITLE,
    WORKFLOW_NAME,
)

SUPPORTED_BACKENDS = ("uia", "win32")


def selector_match_strategy(element_info: Any, automation_id: str) -> str | None:
    """Return the stable selector strategy matching an element, if any."""

    actual_automation_id = str(
        getattr(element_info, "automation_id", "") or ""
    )
    if actual_automation_id == automation_id:
        return "automation_id"

    if automation_id.isdecimal():
        control_id = getattr(element_info, "control_id", None)
        if control_id is not None and str(control_id) == automation_id:
            return "control_id"

    return None


def _safe_rectangle(element_info: Any) -> dict[str, int] | None:
    rectangle = getattr(element_info, "rectangle", None)
    if rectangle is None:
        return None

    try:
        return {
            "left": int(rectangle.left),
            "top": int(rectangle.top),
            "right": int(rectangle.right),
            "bottom": int(rectangle.bottom),
        }
    except (AttributeError, TypeError, ValueError):
        return None


def _safe_bool(wrapper: Any, method_name: str) -> bool | None:
    try:
        return bool(getattr(wrapper, method_name)())
    except Exception:
        return None


def matching_elements(
    descendants: Iterable[Any], automation_id: str
) -> list[tuple[Any, str]]:
    matches: list[tuple[Any, str]] = []
    for element in descendants:
        strategy = selector_match_strategy(element.element_info, automation_id)
        if strategy:
            matches.append((element, strategy))
    return matches


def _probe_control(
    backend: str, descendants: list[Any], spec: ControlSpec
) -> ProbeResult:
    matches = matching_elements(descendants, spec.automation_id)

    if not matches:
        return ProbeResult(
            backend=backend,
            step=spec.step,
            automation_id=spec.automation_id,
            label=spec.label,
            intended_action=spec.action,
            status="not_found",
        )

    element, strategy = matches[0]
    info = element.element_info
    status = "found" if len(matches) == 1 else "ambiguous"

    return ProbeResult(
        backend=backend,
        step=spec.step,
        automation_id=spec.automation_id,
        label=spec.label,
        intended_action=spec.action,
        status=status,
        match_strategy=strategy,
        match_count=len(matches),
        control_type=str(getattr(info, "control_type", "") or "") or None,
        class_name=str(getattr(info, "class_name", "") or "") or None,
        visible=_safe_bool(element, "is_visible"),
        enabled=_safe_bool(element, "is_enabled"),
        rectangle=_safe_rectangle(info),
    )


def is_smartadvisor_window_identity(title: str, class_name: str) -> bool:
    """Match the exact SmartAdvisor WinForms top-level window identity."""

    return (
        title.strip().casefold() == SMARTADVISOR_WINDOW_TITLE.casefold()
        and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
    )


def _native_smartadvisor_handles() -> list[int]:
    """Enumerate live SmartAdvisor HWNDs without relying on UIA text."""

    import win32gui

    handles: list[int] = []

    def collect(hwnd: int, _context: object) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
        except Exception:
            return True

        if is_smartadvisor_window_identity(title, class_name):
            handles.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)
    return handles


def _window_area(hwnd: int) -> int:
    import win32gui

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return 0
    return max(0, right - left) * max(0, bottom - top)


def _preferred_native_handle(handles: list[int]) -> int | None:
    """Prefer the foreground match, then the largest visible window."""

    if not handles:
        return None

    import win32gui

    try:
        foreground = win32gui.GetForegroundWindow()
    except Exception:
        foreground = None
    if foreground in handles:
        return foreground

    return max(handles, key=_window_area)


def _element_identity(window: Any) -> tuple[str, str]:
    """Read only static top-level identity properties."""

    info = window.element_info
    title = ""
    class_name = str(getattr(info, "class_name", "") or "")

    try:
        title = str(window.window_text() or "")
    except Exception:
        title = str(getattr(info, "name", "") or "")

    return title, class_name


def find_smartadvisor_window(backend: str) -> Any | None:
    """Find SmartAdvisor by exact native HWND, with a strict UIA fallback."""

    from pywinauto import Desktop

    desktop = Desktop(backend=backend)

    native_handle = _preferred_native_handle(
        _native_smartadvisor_handles()
    )
    if native_handle is not None:
        try:
            return desktop.window(handle=native_handle)
        except Exception:
            pass

    for window in desktop.windows():
        title, class_name = _element_identity(window)
        if is_smartadvisor_window_identity(title, class_name):
            return window

    return None


def probe_backend(
    backend: str,
    controls: tuple[ControlSpec, ...] = NO_BILL_ON_FILE_CONTROLS,
) -> dict[str, object]:
    """Probe one backend without clicking or reading control values."""

    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported backend: {backend}")

    try:
        window = find_smartadvisor_window(backend)
    except Exception as exc:
        return {
            "backend": backend,
            "window_status": "backend_error",
            "error_code": type(exc).__name__,
            "controls": [],
        }

    if window is None:
        return {
            "backend": backend,
            "window_status": "not_found",
            "error_code": None,
            "controls": [],
        }

    try:
        descendants = [window, *window.descendants()]
    except Exception as exc:
        return {
            "backend": backend,
            "window_status": "descendant_scan_error",
            "error_code": type(exc).__name__,
            "controls": [],
        }

    results = [
        _probe_control(backend, descendants, spec).to_public_dict()
        for spec in controls
    ]
    return {
        "backend": backend,
        "window_status": "found",
        "error_code": None,
        "controls": results,
    }


def scan_controls(
    backends: tuple[str, ...] = SUPPORTED_BACKENDS,
) -> dict[str, object]:
    """Return a PII-safe control validation report."""

    return {
        "schema_version": 1,
        "utility_version": "0.2.1",
        "workflow": WORKFLOW_NAME,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "privacy": {
            "includes_control_text": False,
            "includes_field_values": False,
            "includes_window_titles": False,
            "includes_credentials": False,
        },
        "backend_results": [probe_backend(backend) for backend in backends],
    }
