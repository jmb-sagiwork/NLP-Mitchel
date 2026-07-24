from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any, Callable

from smartadvisor_automation.probe import (
    SUPPORTED_BACKENDS,
    _native_smartadvisor_handles,
    _preferred_native_handle,
    _safe_rectangle,
)
from smartadvisor_automation.selectors import (
    OPEN_BILL_FRAME_NAME,
    OPEN_BILL_WINDOW_TITLE,
    SMARTADVISOR_WINDOW_TITLE,
)

EXTRACTOR_VERSION = "0.1.0"
MAX_TREE_NODES = 5000
SAFE_STRUCTURAL_NAMES = frozenset(
    {
        SMARTADVISOR_WINDOW_TITLE.casefold(),
        OPEN_BILL_WINDOW_TITLE.casefold(),
        OPEN_BILL_FRAME_NAME.casefold(),
    }
)


def sanitize_name(value: object) -> dict[str, object]:
    """Retain only known structural names and redact every other value."""

    normalized = " ".join(str(value or "").split())
    if not normalized:
        return {"status": "empty"}
    if normalized.casefold() in SAFE_STRUCTURAL_NAMES:
        return {"status": "allowlisted", "value": normalized}
    return {"status": "redacted"}


def _error_code(exc: BaseException) -> str:
    return type(exc).__name__


def _safe_attr(value: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(value, name)
    except Exception:
        return default


def _safe_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_runtime_id(value: object) -> list[int] | None:
    try:
        values = [_safe_int(item) for item in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return None
    if any(item is None for item in values):
        return None
    return [int(item) for item in values if item is not None]


def _uia_node(
    backend: str,
    info: Any,
    *,
    node_id: str,
    parent_id: str | None,
    depth: int,
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "parent_id": parent_id,
        "depth": depth,
        "backend": backend,
        "name": sanitize_name(_safe_attr(info, "name", "")),
        "automation_id": str(
            _safe_attr(info, "automation_id", "") or ""
        ),
        "control_id": _safe_int(_safe_attr(info, "control_id")),
        "control_type": str(
            _safe_attr(info, "control_type", "") or ""
        ),
        "class_name": str(_safe_attr(info, "class_name", "") or ""),
        "framework_id": str(
            _safe_attr(info, "framework_id", "") or ""
        ),
        "handle": _safe_int(_safe_attr(info, "handle")),
        "process_id": _safe_int(_safe_attr(info, "process_id")),
        "runtime_id": _safe_runtime_id(_safe_attr(info, "runtime_id")),
        "visible": _safe_attr(info, "visible"),
        "enabled": _safe_attr(info, "enabled"),
        "rectangle": _safe_rectangle(info),
    }


def extract_backend_tree(
    backend: str,
    root_handle: int,
    *,
    max_nodes: int = MAX_TREE_NODES,
    desktop_factory: Callable[..., Any] | None = None,
) -> dict[str, object]:
    """Walk a backend tree one node at a time and retain partial results."""

    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported backend: {backend}")

    if desktop_factory is None:
        from pywinauto import Desktop

        desktop_factory = Desktop

    result: dict[str, object] = {
        "backend": backend,
        "status": "ok",
        "root_handle": root_handle,
        "node_count": 0,
        "truncated": False,
        "nodes": [],
        "errors": [],
    }
    nodes = result["nodes"]
    errors = result["errors"]
    assert isinstance(nodes, list)
    assert isinstance(errors, list)

    try:
        root = desktop_factory(backend=backend).window(
            handle=root_handle
        ).element_info
    except Exception as exc:
        result["status"] = "root_error"
        errors.append(
            {
                "operation": "resolve_root",
                "error_code": _error_code(exc),
            }
        )
        return result

    pending: deque[tuple[Any, str | None, int]] = deque(
        [(root, None, 0)]
    )
    sequence = 0

    while pending and sequence < max_nodes:
        info, parent_id, depth = pending.popleft()
        sequence += 1
        node_id = f"{backend}:{sequence:05d}"
        nodes.append(
            _uia_node(
                backend,
                info,
                node_id=node_id,
                parent_id=parent_id,
                depth=depth,
            )
        )

        try:
            children = list(info.children())
        except Exception as exc:
            errors.append(
                {
                    "node_id": node_id,
                    "operation": "children",
                    "error_code": _error_code(exc),
                }
            )
            continue

        pending.extend(
            (child, node_id, depth + 1) for child in children
        )

    result["node_count"] = len(nodes)
    if pending:
        result["truncated"] = True
        result["status"] = "truncated"
    elif errors:
        result["status"] = "partial"
    return result


def _native_call(
    errors: list[dict[str, object]],
    hwnd: int,
    operation: str,
    callback: Callable[[], Any],
    default: Any = None,
) -> Any:
    try:
        return callback()
    except Exception as exc:
        errors.append(
            {
                "handle": hwnd,
                "operation": operation,
                "error_code": _error_code(exc),
            }
        )
        return default


def extract_native_tree(
    root_handle: int,
    *,
    max_nodes: int = MAX_TREE_NODES,
) -> dict[str, object]:
    """Extract the native HWND hierarchy without using UI Automation."""

    import win32gui
    import win32process

    errors: list[dict[str, object]] = []
    handles: list[int] = [root_handle]

    try:
        win32gui.EnumChildWindows(
            root_handle,
            lambda hwnd, _context: handles.append(hwnd) or True,
            None,
        )
    except Exception as exc:
        errors.append(
            {
                "handle": root_handle,
                "operation": "enumerate_children",
                "error_code": _error_code(exc),
            }
        )

    handles = list(dict.fromkeys(handles))
    truncated = len(handles) > max_nodes
    handles = handles[:max_nodes]
    handle_set = set(handles)
    parents: dict[int, int | None] = {}

    for hwnd in handles:
        if hwnd == root_handle:
            parents[hwnd] = None
            continue
        parent = _native_call(
            errors,
            hwnd,
            "get_parent",
            lambda hwnd=hwnd: win32gui.GetParent(hwnd),
        )
        parents[hwnd] = (
            int(parent) if parent and int(parent) in handle_set else None
        )

    def depth_for(hwnd: int) -> int:
        depth = 0
        current = parents.get(hwnd)
        visited = {hwnd}
        while current is not None and current not in visited:
            visited.add(current)
            depth += 1
            current = parents.get(current)
        return depth

    nodes: list[dict[str, object]] = []
    for hwnd in handles:
        title = _native_call(
            errors,
            hwnd,
            "get_text",
            lambda hwnd=hwnd: win32gui.GetWindowText(hwnd),
            "",
        )
        rectangle = _native_call(
            errors,
            hwnd,
            "get_rectangle",
            lambda hwnd=hwnd: win32gui.GetWindowRect(hwnd),
        )
        thread_process = _native_call(
            errors,
            hwnd,
            "get_process",
            lambda hwnd=hwnd: win32process.GetWindowThreadProcessId(hwnd),
        )
        nodes.append(
            {
                "node_id": f"native:0x{hwnd:08X}",
                "parent_id": (
                    f"native:0x{parents[hwnd]:08X}"
                    if parents[hwnd] is not None
                    else None
                ),
                "depth": depth_for(hwnd),
                "handle": hwnd,
                "name": sanitize_name(title),
                "class_name": str(
                    _native_call(
                        errors,
                        hwnd,
                        "get_class",
                        lambda hwnd=hwnd: win32gui.GetClassName(hwnd),
                        "",
                    )
                    or ""
                ),
                "control_id": _safe_int(
                    _native_call(
                        errors,
                        hwnd,
                        "get_control_id",
                        lambda hwnd=hwnd: win32gui.GetDlgCtrlID(hwnd),
                    )
                ),
                "visible": _native_call(
                    errors,
                    hwnd,
                    "is_visible",
                    lambda hwnd=hwnd: bool(
                        win32gui.IsWindowVisible(hwnd)
                    ),
                ),
                "enabled": _native_call(
                    errors,
                    hwnd,
                    "is_enabled",
                    lambda hwnd=hwnd: bool(
                        win32gui.IsWindowEnabled(hwnd)
                    ),
                ),
                "rectangle": (
                    {
                        "left": int(rectangle[0]),
                        "top": int(rectangle[1]),
                        "right": int(rectangle[2]),
                        "bottom": int(rectangle[3]),
                    }
                    if rectangle is not None
                    else None
                ),
                "thread_id": (
                    _safe_int(thread_process[0])
                    if thread_process is not None
                    else None
                ),
                "process_id": (
                    _safe_int(thread_process[1])
                    if thread_process is not None
                    else None
                ),
            }
        )

    status = "truncated" if truncated else ("partial" if errors else "ok")
    return {
        "backend": "native",
        "status": status,
        "root_handle": root_handle,
        "node_count": len(nodes),
        "truncated": truncated,
        "nodes": nodes,
        "errors": errors,
    }


def native_process_windows(
    root_handle: int,
) -> tuple[int | None, list[int], str | None]:
    """Find every top-level HWND owned by the SmartAdvisor process."""

    import win32gui
    import win32process

    try:
        _, process_id = win32process.GetWindowThreadProcessId(root_handle)
        process_id = int(process_id)
    except Exception as exc:
        return None, [root_handle], _error_code(exc)

    handles: list[int] = []

    def collect(hwnd: int, _context: object) -> bool:
        try:
            _, candidate_process_id = (
                win32process.GetWindowThreadProcessId(hwnd)
            )
        except Exception:
            return True
        if int(candidate_process_id) == process_id:
            handles.append(hwnd)
        return True

    try:
        win32gui.EnumWindows(collect, None)
    except Exception as exc:
        return process_id, [root_handle], _error_code(exc)

    if root_handle not in handles:
        handles.insert(0, root_handle)
    return process_id, list(dict.fromkeys(handles)), None


def extract_smartadvisor_objects(
    *,
    backends: tuple[str, ...] = SUPPORTED_BACKENDS,
    max_nodes: int = MAX_TREE_NODES,
) -> dict[str, object]:
    """Return a read-only, privacy-safe SmartAdvisor object report."""

    try:
        handles = _native_smartadvisor_handles()
        selected_handle = _preferred_native_handle(handles)
    except Exception as exc:
        handles = []
        selected_handle = None
        discovery_error = _error_code(exc)
    else:
        discovery_error = None

    report: dict[str, object] = {
        "schema_version": 1,
        "extractor_version": EXTRACTOR_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "privacy": {
            "read_only": True,
            "includes_field_values": False,
            "includes_unknown_names": False,
            "name_policy": "structural_allowlist_otherwise_redacted",
        },
        "discovery": {
            "status": (
                "found"
                if selected_handle is not None
                else "not_found"
            ),
            "error_code": discovery_error,
            "matching_window_count": len(handles),
            "selected_handle": selected_handle,
            "process_id": None,
            "process_window_count": 0,
            "process_window_error_code": None,
        },
        "native_trees": [],
        "backend_trees": [],
    }

    if selected_handle is None:
        return report

    process_id, process_handles, process_error = native_process_windows(
        selected_handle
    )
    discovery = report["discovery"]
    assert isinstance(discovery, dict)
    discovery["process_id"] = process_id
    discovery["process_window_count"] = len(process_handles)
    discovery["process_window_error_code"] = process_error

    native_trees = report["native_trees"]
    assert isinstance(native_trees, list)
    for process_handle in process_handles:
        native_trees.append(
            extract_native_tree(
                process_handle,
                max_nodes=max_nodes,
            )
        )

    backend_trees = report["backend_trees"]
    assert isinstance(backend_trees, list)
    for backend in backends:
        for process_handle in process_handles:
            backend_trees.append(
                extract_backend_tree(
                    backend,
                    process_handle,
                    max_nodes=max_nodes,
                )
            )
    return report
