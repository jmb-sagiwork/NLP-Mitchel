from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from smartadvisor_automation.models import ControlSpec, ProbeResult
from smartadvisor_automation.selectors import (
    NO_BILL_ON_FILE_CONTROLS,
    OPEN_BILL_CLIENT_AUTOMATION_ID,
    OPEN_BILL_FRAME_AUTOMATION_ID,
    OPEN_BILL_FRAME_NAME,
    OPEN_BILL_WINDOW_AUTOMATION_ID,
    OPEN_BILL_WINDOW_TITLE,
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


def _element_handle(element: Any) -> int | None:
    """Read a wrapper's native HWND without depending on one backend."""

    info = getattr(element, "element_info", None)
    handle = getattr(info, "handle", None)
    if handle is None:
        handle = getattr(element, "handle", None)

    try:
        native_handle = int(handle)
    except (TypeError, ValueError):
        return None
    return native_handle if native_handle else None


def _native_named_descendants(
    parent_handle: int,
    expected_name: str,
) -> list[int]:
    """Find visible WinForms descendants by their exact native text."""

    import win32gui

    handles: list[int] = []

    def collect(hwnd: int, _context: object) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            name = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
        except Exception:
            return True

        if (
            name.strip().casefold() == expected_name.casefold()
            and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
        ):
            handles.append(hwnd)
        return True

    win32gui.EnumChildWindows(parent_handle, collect, None)
    return handles


def is_open_bill_frame_identity(
    name: str,
    automation_id: str,
    class_name: str,
) -> bool:
    """Match the stable UIA identity supplied for the Open Bill group."""

    return (
        name.strip().casefold() == OPEN_BILL_FRAME_NAME.casefold()
        and automation_id == OPEN_BILL_FRAME_AUTOMATION_ID
        and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
    )


def _element_name(element: Any) -> str:
    info = getattr(element, "element_info", None)
    try:
        name = str(element.window_text() or "")
    except Exception:
        name = ""
    return name or str(getattr(info, "name", "") or "")


def _find_frame_in_open_bill(open_bill: Any) -> Any | None:
    """Use the narrow Open Bill subtree if native frame lookup is unavailable."""

    try:
        descendants = list(open_bill.descendants())
    except Exception:
        return None

    for element in descendants:
        info = element.element_info
        if is_open_bill_frame_identity(
            _element_name(element),
            str(getattr(info, "automation_id", "") or ""),
            str(getattr(info, "class_name", "") or ""),
        ):
            return element
    return None


def _find_open_bill_in_main(main_window: Any) -> Any | None:
    """Fall back to the supplied UIA ancestry when HWND nesting differs."""

    try:
        descendants = list(main_window.descendants(control_type="Window"))
    except Exception:
        try:
            descendants = list(main_window.descendants())
        except Exception:
            return None

    for element in descendants:
        info = element.element_info
        if (
            _element_name(element).strip().casefold()
            == OPEN_BILL_WINDOW_TITLE.casefold()
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            return element
    return None


def _find_open_bill_process_window(
    desktop: Any,
    main_window: Any,
) -> Any | None:
    """Find a separate Open Bill top-level window owned by SmartAdvisor."""

    process_id = getattr(main_window.element_info, "process_id", None)
    if process_id is None:
        return None

    try:
        windows = list(
            desktop.windows(
                process=int(process_id),
                visible_only=True,
                enabled_only=False,
            )
        )
    except Exception:
        return None

    matches = []
    for window in windows:
        info = window.element_info
        if (
            _element_name(window).strip().casefold()
            == OPEN_BILL_WINDOW_TITLE.casefold()
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            matches.append(window)

    if len(matches) == 1:
        return matches[0]

    actionable = [
        window
        for window in matches
        if _find_frame_in_open_bill(window) is not None
    ]
    return actionable[0] if len(actionable) == 1 else None


def _direct_element_children(element_info: Any) -> list[Any]:
    """Read one UIA level while preserving partial-tree reliability."""

    try:
        return list(element_info.children())
    except Exception:
        return []


def _strict_uia_open_bill_frame(
    desktop: Any,
    main_window: Any,
) -> Any | None:
    """Resolve the exact hierarchy proven by the object extractor."""

    process_id = getattr(main_window.element_info, "process_id", None)
    if process_id is None:
        return None

    try:
        process_windows = list(
            desktop.windows(
                process=int(process_id),
                visible_only=True,
                enabled_only=False,
            )
        )
    except Exception:
        return None

    open_bill_matches = []
    for window in process_windows:
        info = window.element_info
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_WINDOW_AUTOMATION_ID
            and str(getattr(info, "name", "") or "").strip().casefold()
            == OPEN_BILL_WINDOW_TITLE.casefold()
            and str(getattr(info, "control_type", "") or "") == "Window"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            open_bill_matches.append(window)

    if len(open_bill_matches) != 1:
        return None

    frame_matches = []
    for info in _direct_element_children(
        open_bill_matches[0].element_info
    ):
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_FRAME_AUTOMATION_ID
            and str(getattr(info, "name", "") or "").strip().casefold()
            == OPEN_BILL_FRAME_NAME.casefold()
            and str(getattr(info, "control_type", "") or "") == "Group"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        ):
            frame_matches.append(info)

    if len(frame_matches) != 1:
        return None
    frame_info = frame_matches[0]

    client_matches = [
        info
        for info in _direct_element_children(frame_info)
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_CLIENT_AUTOMATION_ID
            and str(getattr(info, "control_type", "") or "")
            == "ComboBox"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        )
    ]
    if len(client_matches) != 1:
        return None

    frame_handle = _safe_int_handle(
        getattr(frame_info, "handle", None)
    )
    if frame_handle is None:
        return None
    try:
        return desktop.window(handle=frame_handle)
    except Exception:
        return None


def _safe_int_handle(value: object) -> int | None:
    try:
        handle = int(value)
    except (TypeError, ValueError):
        return None
    return handle if handle else None


def find_direct_uia_control(
    backend: str,
    parent: Any,
    automation_id: str,
) -> Any | None:
    """Wrap one exact direct UIA child by its dynamic native handle."""

    if backend != "uia":
        return None
    parent_info = getattr(parent, "element_info", None)
    if parent_info is None:
        return None

    matches = [
        info
        for info in _direct_element_children(parent_info)
        if (
            str(getattr(info, "automation_id", "") or "")
            == automation_id
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        )
    ]
    if len(matches) != 1:
        return None

    handle = _safe_int_handle(getattr(matches[0], "handle", None))
    if handle is None:
        return None

    from pywinauto import Desktop

    try:
        return Desktop(backend=backend).window(handle=handle)
    except Exception:
        return None


def find_open_bill_frame(backend: str, main_window: Any) -> Any | None:
    """Handshake through Main System -> Open Bill -> Frame1."""

    from pywinauto import Desktop

    main_handle = _element_handle(main_window)
    desktop = Desktop(backend=backend)
    if backend == "uia":
        strict_frame = _strict_uia_open_bill_frame(
            desktop,
            main_window,
        )
        if strict_frame is not None:
            return strict_frame

    open_bill = _find_open_bill_process_window(desktop, main_window)

    if open_bill is None and main_handle is not None:
        open_bill_handles = _native_named_descendants(
            main_handle,
            OPEN_BILL_WINDOW_TITLE,
        )
        open_bill_handle = _preferred_native_handle(open_bill_handles)
        if open_bill_handle is not None:
            open_bill = desktop.window(handle=open_bill_handle)

    if open_bill is None:
        open_bill = _find_open_bill_in_main(main_window)
    if open_bill is None:
        return None

    open_bill_handle = _element_handle(open_bill)
    if open_bill_handle is not None:
        frame_handles = _native_named_descendants(
            open_bill_handle,
            OPEN_BILL_FRAME_NAME,
        )
        frame_handle = _preferred_native_handle(frame_handles)
        if frame_handle is not None:
            frame = desktop.window(handle=frame_handle)
            info = frame.element_info
            if is_open_bill_frame_identity(
                _element_name(frame),
                str(getattr(info, "automation_id", "") or ""),
                str(getattr(info, "class_name", "") or ""),
            ):
                return frame

    return _find_frame_in_open_bill(open_bill)


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
        "utility_version": "0.2.4",
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
