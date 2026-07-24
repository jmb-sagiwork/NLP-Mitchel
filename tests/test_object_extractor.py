import json
import sys
from types import SimpleNamespace

from smartadvisor_automation.object_extractor import (
    extract_backend_tree,
    extract_native_tree,
    extract_smartadvisor_objects,
    sanitize_name,
)


def test_sanitize_name_allows_only_structural_names() -> None:
    assert sanitize_name("Open Bill") == {
        "status": "allowlisted",
        "value": "Open Bill",
    }
    assert sanitize_name("SENSITIVE-FIELD-VALUE") == {
        "status": "redacted"
    }
    assert sanitize_name("") == {"status": "empty"}


def test_backend_tree_retains_partial_results_after_child_error() -> None:
    child = SimpleNamespace(
        name="SENSITIVE-FIELD-VALUE",
        automation_id="cboClient",
        control_id=123,
        control_type="ComboBox",
        class_name="WindowsForms10.COMBOBOX.app.test",
        framework_id="WinForm",
        handle=300,
        process_id=42,
        runtime_id=(1, 2, 3),
        visible=True,
        enabled=True,
        rectangle=None,
        children=lambda: (_ for _ in ()).throw(RuntimeError()),
    )
    root = SimpleNamespace(
        name="SmartAdvisor Main System",
        automation_id="",
        control_id=0,
        control_type="Window",
        class_name="WindowsForms10.Window.app.test",
        framework_id="WinForm",
        handle=100,
        process_id=42,
        runtime_id=(1,),
        visible=True,
        enabled=True,
        rectangle=None,
        children=lambda: [child],
    )
    desktop_factory = lambda **_kwargs: SimpleNamespace(
        window=lambda **_criteria: SimpleNamespace(element_info=root)
    )

    report = extract_backend_tree(
        "uia",
        100,
        desktop_factory=desktop_factory,
    )

    assert report["status"] == "partial"
    assert report["node_count"] == 2
    assert report["nodes"][1]["automation_id"] == "cboClient"
    assert report["nodes"][1]["name"] == {"status": "redacted"}
    assert report["errors"] == [
        {
            "node_id": "uia:00002",
            "operation": "children",
            "error_code": "RuntimeError",
        }
    ]
    assert "SENSITIVE-FIELD-VALUE" not in json.dumps(report)


def test_backend_tree_caps_runaway_trees() -> None:
    leaf = SimpleNamespace(
        name="",
        automation_id="",
        control_id=0,
        control_type="Pane",
        class_name="",
        framework_id="",
        handle=0,
        process_id=42,
        runtime_id=(),
        visible=True,
        enabled=True,
        rectangle=None,
        children=lambda: [],
    )
    root = SimpleNamespace(**vars(leaf))
    root.children = lambda: [leaf, leaf, leaf]
    desktop_factory = lambda **_kwargs: SimpleNamespace(
        window=lambda **_criteria: SimpleNamespace(element_info=root)
    )

    report = extract_backend_tree(
        "win32",
        100,
        max_nodes=2,
        desktop_factory=desktop_factory,
    )

    assert report["status"] == "truncated"
    assert report["truncated"] is True
    assert report["node_count"] == 2


def test_native_tree_preserves_parents_and_redacts_values(
    monkeypatch,
) -> None:
    children = [200, 300, 400]
    parents = {200: 100, 300: 200, 400: 300}
    names = {
        100: "SmartAdvisor Main System",
        200: "Open Bill",
        300: "Enter Bill To Edit",
        400: "SENSITIVE-FIELD-VALUE",
    }
    fake_win32gui = SimpleNamespace(
        EnumChildWindows=lambda _root, callback, context: [
            callback(hwnd, context) for hwnd in children
        ],
        GetParent=lambda hwnd: parents[hwnd],
        GetWindowText=lambda hwnd: names[hwnd],
        GetWindowRect=lambda hwnd: (hwnd, hwnd, hwnd + 10, hwnd + 10),
        GetClassName=lambda _hwnd: "WindowsForms10.Window.app.test",
        GetDlgCtrlID=lambda hwnd: hwnd + 1000,
        IsWindowVisible=lambda _hwnd: True,
        IsWindowEnabled=lambda _hwnd: True,
    )
    fake_win32process = SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (77, 42)
    )
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)
    monkeypatch.setitem(sys.modules, "win32process", fake_win32process)

    report = extract_native_tree(100)

    assert report["status"] == "ok"
    assert report["node_count"] == 4
    assert report["nodes"][2]["parent_id"] == "native:0x000000C8"
    assert report["nodes"][2]["depth"] == 2
    assert report["nodes"][3]["name"] == {"status": "redacted"}
    assert "SENSITIVE-FIELD-VALUE" not in json.dumps(report)


def test_object_report_scans_each_process_window(monkeypatch) -> None:
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor."
        "_native_smartadvisor_handles",
        lambda: [100],
    )
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor."
        "_preferred_native_handle",
        lambda _handles: 100,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor."
        "native_process_windows",
        lambda _root: (42, [100, 200], None),
    )
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor.extract_native_tree",
        lambda handle, **_kwargs: {
            "root_handle": handle,
            "node_count": 1,
        },
    )
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor.extract_backend_tree",
        lambda backend, handle, **_kwargs: {
            "backend": backend,
            "root_handle": handle,
            "node_count": 1,
        },
    )

    report = extract_smartadvisor_objects()

    assert report["discovery"]["process_id"] == 42
    assert report["discovery"]["process_window_count"] == 2
    assert [tree["root_handle"] for tree in report["native_trees"]] == [
        100,
        200,
    ]
    assert len(report["backend_trees"]) == 4
