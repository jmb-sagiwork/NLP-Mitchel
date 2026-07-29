from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from smartadvisor_automation.diagnostics import DiagnosticTrace
from smartadvisor_automation.models import ControlSpec, ProbeResult
from smartadvisor_automation.selectors import (
    BILL_SEARCH_FRAME_AUTOMATION_ID,
    BILL_SEARCH_FRAME_NAME,
    BILL_SEARCH_WINDOW_AUTOMATION_ID,
    BILL_SEARCH_WINDOW_TITLE,
    NO_BILL_ON_FILE_CONTROLS,
    OPEN_BILL_ACTION_AUTOMATION_ID,
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


def name_match_strategy(
    element_info: Any,
    name: str | None,
    control_type: str | None,
) -> str | None:
    """Match a control that publishes no AutomationId at all.

    Non-client title bar buttons expose only a Name and a ControlType, so
    those are the whole selector. Always use this scoped to one container:
    every window in the process owns a "Close" button.
    """

    if not name:
        return None

    actual_name = str(getattr(element_info, "name", "") or "").strip()
    if actual_name != name:
        return None

    if control_type:
        actual_control_type = str(
            getattr(element_info, "control_type", "") or ""
        )
        if actual_control_type != control_type:
            return None

    return "name_and_control_type"


def spec_match_strategy(element_info: Any, spec: ControlSpec) -> str | None:
    """Match one element against a spec.

    AutomationId identifies the control when there is one. A spec may also
    carry a Name alongside it, in which case both must agree — that is how
    a generic framework id such as `radButton1` is pinned down to one
    button. With no AutomationId, Name plus ControlType is the whole
    selector.
    """

    if not spec.automation_id:
        return name_match_strategy(element_info, spec.name, spec.control_type)

    strategy = selector_match_strategy(element_info, spec.automation_id)
    if strategy is None:
        return None

    if spec.name and (
        name_match_strategy(element_info, spec.name, spec.control_type)
        is None
    ):
        return None

    return strategy


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


def matching_spec_elements(
    descendants: Iterable[Any], spec: ControlSpec
) -> list[tuple[Any, str]]:
    """Match by AutomationId, or by Name/ControlType when there is none."""

    matches: list[tuple[Any, str]] = []
    for element in descendants:
        strategy = spec_match_strategy(element.element_info, spec)
        if strategy:
            matches.append((element, strategy))
    return matches


def _probe_control(
    backend: str, descendants: list[Any], spec: ControlSpec
) -> ProbeResult:
    matches = matching_spec_elements(descendants, spec)

    if not matches:
        return ProbeResult(
            backend=backend,
            step=spec.step,
            automation_id=spec.automation_id,
            label=spec.label,
            intended_action=spec.action,
            status="not_found",
            selector_name=spec.name,
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
        selector_name=spec.name,
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


def is_bill_search_frame_identity(
    name: str,
    automation_id: str,
    class_name: str,
) -> bool:
    """Match the stable UIA identity supplied for Bill Records."""

    return (
        name.strip().casefold() == BILL_SEARCH_FRAME_NAME.casefold()
        and automation_id == BILL_SEARCH_FRAME_AUTOMATION_ID
        and class_name.startswith(SMARTADVISOR_WINDOW_CLASS_PREFIX)
    )


def _element_name(element: Any) -> str:
    info = getattr(element, "element_info", None)
    try:
        name = str(element.window_text() or "")
    except Exception:
        name = ""
    return name or str(getattr(info, "name", "") or "")


def _find_frame_in_open_bill(
    open_bill: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Use the narrow Open Bill subtree if native frame lookup is unavailable."""

    try:
        descendants = list(open_bill.descendants())
    except Exception as exc:
        if trace:
            trace.record(
                "descendant_frame_search",
                "any",
                "descendant_scan_failed",
                exception=type(exc).__name__,
            )
        return None

    for element in descendants:
        info = element.element_info
        if is_open_bill_frame_identity(
            _element_name(element),
            str(getattr(info, "automation_id", "") or ""),
            str(getattr(info, "class_name", "") or ""),
        ):
            if trace:
                trace.record(
                    "descendant_frame_search", "any", "resolved"
                )
            return element
    if trace:
        trace.record(
            "descendant_frame_search",
            "any",
            "not_found",
            descendant_count=len(descendants),
        )
    return None


def _find_open_bill_in_main(
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Fall back to the supplied UIA ancestry when HWND nesting differs."""

    try:
        descendants = list(main_window.descendants(control_type="Window"))
    except Exception:
        try:
            descendants = list(main_window.descendants())
        except Exception as exc:
            if trace:
                trace.record(
                    "open_bill_in_main_descendants",
                    "uia",
                    "descendant_scan_failed",
                    exception=type(exc).__name__,
                )
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
            if trace:
                trace.record(
                    "open_bill_in_main_descendants", "uia", "resolved"
                )
            return element
    if trace:
        trace.record(
            "open_bill_in_main_descendants",
            "uia",
            "not_found",
            descendant_count=len(descendants),
        )
    return None


def _find_open_bill_process_window(
    desktop: Any,
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Find Open Bill by its own exact identity, independent of any
    assumption that it shares the main window's process ID.

    A Citrix-hosted modal is not guaranteed to report the same process ID
    as its logical parent, so this scans every top-level window rather than
    pre-filtering by `main_window`'s process, the same way the main window
    itself is found by identity alone.
    """

    stage = "process_window_title_search"
    main_process_id = getattr(main_window.element_info, "process_id", None)

    try:
        windows = list(desktop.windows())
    except Exception as exc:
        if trace:
            trace.record(
                stage,
                "any",
                "window_enumeration_failed",
                exception=type(exc).__name__,
            )
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
        if trace:
            matched_process_id = getattr(
                matches[0].element_info, "process_id", None
            )
            trace.record(
                stage,
                "any",
                "resolved",
                window_count=len(windows),
                same_process=(
                    main_process_id is not None
                    and matched_process_id == main_process_id
                ),
            )
        return matches[0]

    actionable = [
        window
        for window in matches
        if _find_frame_in_open_bill(window, trace=trace) is not None
    ]
    if len(actionable) == 1:
        if trace:
            trace.record(
                stage,
                "any",
                "resolved_by_actionable_frame",
                title_match_count=len(matches),
            )
        return actionable[0]

    if trace:
        trace.record(
            stage,
            "any",
            "title_not_uniquely_matched",
            window_count=len(windows),
            title_match_count=len(matches),
        )
    return None


def _direct_element_children(element_info: Any) -> list[Any]:
    """Read one UIA level while preserving partial-tree reliability."""

    try:
        return list(element_info.children())
    except Exception:
        return []


def _strict_uia_open_bill_frame(
    desktop: Any,
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Resolve the exact hierarchy proven by the object extractor.

    Open Bill is matched by its own exact identity across every top-level
    UIA window, not pre-filtered to `main_window`'s process ID - a
    Citrix-hosted modal is not guaranteed to report the same process as its
    logical parent.
    """

    stage = "strict_uia_hierarchy"
    main_process_id = getattr(main_window.element_info, "process_id", None)

    try:
        all_windows = list(desktop.windows())
    except Exception as exc:
        if trace:
            trace.record(
                stage,
                "uia",
                "window_enumeration_failed",
                exception=type(exc).__name__,
            )
        return None

    open_bill_matches = []
    for window in all_windows:
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
        if trace:
            trace.record(
                stage,
                "uia",
                "open_bill_not_uniquely_matched",
                window_count=len(all_windows),
                open_bill_match_count=len(open_bill_matches),
            )
        return None

    if trace:
        matched_process_id = getattr(
            open_bill_matches[0].element_info, "process_id", None
        )
        trace.record(
            stage,
            "uia",
            "open_bill_matched",
            same_process=(
                main_process_id is not None
                and matched_process_id == main_process_id
            ),
        )

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
        if trace:
            trace.record(
                stage,
                "uia",
                "frame_not_uniquely_matched",
                direct_child_count=len(
                    _direct_element_children(open_bill_matches[0].element_info)
                ),
                frame_match_count=len(frame_matches),
            )
        return None
    frame_info = frame_matches[0]

    frame_children = _direct_element_children(frame_info)
    action_matches = [
        info
        for info in frame_children
        if (
            str(getattr(info, "automation_id", "") or "")
            == OPEN_BILL_ACTION_AUTOMATION_ID
            and str(getattr(info, "control_type", "") or "")
            == "Button"
            and str(getattr(info, "class_name", "") or "").startswith(
                SMARTADVISOR_WINDOW_CLASS_PREFIX
            )
        )
    ]
    if len(action_matches) != 1:
        if trace:
            trace.record(
                stage,
                "uia",
                "action_not_uniquely_matched",
                frame_direct_child_count=len(frame_children),
                action_match_count=len(action_matches),
            )
        return None

    frame_handle = _safe_int_handle(
        getattr(frame_info, "handle", None)
    )
    if frame_handle is None:
        if trace:
            trace.record(stage, "uia", "frame_handle_missing")
        return None
    try:
        wrapped = desktop.window(handle=frame_handle)
    except Exception as exc:
        if trace:
            trace.record(
                stage,
                "uia",
                "frame_handle_wrap_failed",
                exception=type(exc).__name__,
            )
        return None

    if trace:
        trace.record(stage, "uia", "resolved")
    return wrapped


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


def find_bill_search_frame(
    backend: str,
    roots: Iterable[Any],
) -> Any | None:
    """Resolve frmBillSearch -> Frame1/Bill Records from visible roots."""

    if backend != "uia":
        return None

    bill_search_matches: list[Any] = []
    for root in roots:
        candidates = [root]
        try:
            candidates.extend(root.descendants())
        except Exception:
            pass

        for element in candidates:
            info = getattr(element, "element_info", None)
            if info is None:
                continue
            if (
                str(getattr(info, "automation_id", "") or "")
                == BILL_SEARCH_WINDOW_AUTOMATION_ID
                and str(getattr(info, "name", "") or "").strip().casefold()
                == BILL_SEARCH_WINDOW_TITLE.casefold()
                and str(getattr(info, "control_type", "") or "") == "Window"
                and str(getattr(info, "class_name", "") or "").startswith(
                    SMARTADVISOR_WINDOW_CLASS_PREFIX
                )
            ):
                bill_search_matches.append(element)

    if len(bill_search_matches) != 1:
        return None

    frame = find_direct_uia_control(
        backend,
        bill_search_matches[0],
        BILL_SEARCH_FRAME_AUTOMATION_ID,
    )
    if frame is None:
        return None

    info = getattr(frame, "element_info", None)
    if info is None or not is_bill_search_frame_identity(
        _element_name(frame),
        str(getattr(info, "automation_id", "") or ""),
        str(getattr(info, "class_name", "") or ""),
    ):
        return None
    return frame


def find_open_bill_frame(
    backend: str,
    main_window: Any,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Handshake through Main System -> Open Bill -> Frame1."""

    from pywinauto import Desktop

    main_handle = _element_handle(main_window)
    desktop = Desktop(backend=backend)
    if backend == "uia":
        strict_frame = _strict_uia_open_bill_frame(
            desktop,
            main_window,
            trace=trace,
        )
        if strict_frame is not None:
            return strict_frame

    open_bill = _find_open_bill_process_window(
        desktop, main_window, trace=trace
    )

    if open_bill is None and main_handle is not None:
        open_bill_handles = _native_named_descendants(
            main_handle,
            OPEN_BILL_WINDOW_TITLE,
        )
        open_bill_handle = _preferred_native_handle(open_bill_handles)
        if trace:
            trace.record(
                "native_child_search",
                backend,
                "resolved" if open_bill_handle is not None else "not_found",
                candidate_count=len(open_bill_handles),
            )
        if open_bill_handle is not None:
            open_bill = desktop.window(handle=open_bill_handle)

    if open_bill is None:
        open_bill = _find_open_bill_in_main(main_window, trace=trace)
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
                if trace:
                    trace.record(
                        "native_frame_search", backend, "resolved"
                    )
                return frame
        if trace:
            trace.record(
                "native_frame_search",
                backend,
                "not_found",
                candidate_count=len(frame_handles),
            )

    return _find_frame_in_open_bill(open_bill, trace=trace)


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


def find_smartadvisor_window(
    backend: str,
    *,
    trace: DiagnosticTrace | None = None,
) -> Any | None:
    """Find SmartAdvisor by exact native HWND, with a strict UIA fallback."""

    from pywinauto import Desktop

    desktop = Desktop(backend=backend)

    native_handles = _native_smartadvisor_handles()
    native_handle = _preferred_native_handle(native_handles)
    if native_handle is not None:
        try:
            window = desktop.window(handle=native_handle)
        except Exception as exc:
            if trace:
                trace.record(
                    "main_window_native_handle",
                    backend,
                    "wrap_failed",
                    exception=type(exc).__name__,
                    candidate_count=len(native_handles),
                )
        else:
            if trace:
                trace.record(
                    "main_window_native_handle",
                    backend,
                    "resolved",
                    candidate_count=len(native_handles),
                )
            return window

    for window in desktop.windows():
        title, class_name = _element_identity(window)
        if is_smartadvisor_window_identity(title, class_name):
            if trace:
                trace.record(
                    "main_window_uia_fallback", backend, "resolved"
                )
            return window

    if trace:
        trace.record(
            "main_window_uia_fallback",
            backend,
            "not_found",
            native_candidate_count=len(native_handles),
        )
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
        "utility_version": "0.4.3",
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
