from dataclasses import dataclass
from types import SimpleNamespace

from smartadvisor_automation.models import ControlSpec
from smartadvisor_automation.probe import (
    _native_smartadvisor_handles,
    _preferred_native_handle,
    find_bill_search_frame,
    find_direct_uia_control,
    find_open_bill_frame,
    is_bill_search_frame_identity,
    is_open_bill_frame_identity,
    is_smartadvisor_window_identity,
    selector_match_strategy,
    spec_match_strategy,
)


@dataclass
class FakeElementInfo:
    automation_id: str = ""
    control_id: int | None = None
    name: str = ""
    control_type: str = ""


def test_named_automation_id_matches_exactly() -> None:
    info = FakeElementInfo(automation_id="cboClient", control_id=10)

    assert selector_match_strategy(info, "cboClient") == "automation_id"


def test_numeric_automation_id_can_match_control_id() -> None:
    info = FakeElementInfo(automation_id="", control_id=263892)

    assert selector_match_strategy(info, "263892") == "control_id"


def test_selector_does_not_match_partial_values() -> None:
    info = FakeElementInfo(automation_id="cboClientOther", control_id=263892)

    assert selector_match_strategy(info, "cboClient") is None


def test_automation_ids_are_case_sensitive() -> None:
    """cmdOK and cmdOk are different buttons in different windows."""

    info = FakeElementInfo(automation_id="cmdOk")

    assert selector_match_strategy(info, "cmdOk") == "automation_id"
    assert selector_match_strategy(info, "cmdOK") is None


def test_spec_requires_name_to_agree_when_both_are_given() -> None:
    """A generic framework id is pinned down by also matching the Name."""

    spec = ControlSpec(
        step="7.3",
        automation_id="radButton1",
        label="Pended bill warning",
        action="click",
        name="&OK",
    )

    assert (
        spec_match_strategy(
            FakeElementInfo(automation_id="radButton1", name="&OK"), spec
        )
        == "automation_id"
    )
    assert (
        spec_match_strategy(
            FakeElementInfo(automation_id="radButton1", name="&Cancel"), spec
        )
        is None
    )


def test_spec_matches_on_name_when_there_is_no_automation_id() -> None:
    spec = ControlSpec(
        step="7.6",
        automation_id="",
        label="Close the bill window",
        action="close",
        name="Close",
        control_type="Button",
    )

    assert (
        spec_match_strategy(
            FakeElementInfo(name="Close", control_type="Button"), spec
        )
        == "name_and_control_type"
    )
    assert (
        spec_match_strategy(
            FakeElementInfo(name="Close", control_type="MenuItem"), spec
        )
        is None
    )


def test_smartadvisor_identity_matches_exact_winforms_window() -> None:
    assert is_smartadvisor_window_identity(
        "SmartAdvisor Main System",
        "WindowsForms10.Window.8.app.0.2bf8098_r17_ad1",
    )


def test_smartadvisor_identity_rejects_unrelated_title_and_class() -> None:
    assert not is_smartadvisor_window_identity(
        "Welcome - SmartAdvisor - Visual Studio Code",
        "Chrome_WidgetWin_1",
    )
    assert not is_smartadvisor_window_identity(
        "SmartAdvisor Main System",
        "Transparent Windows Client",
    )


def test_open_bill_frame_identity_matches_supplied_parent() -> None:
    assert is_open_bill_frame_identity(
        "Enter Bill To Edit",
        "Frame1",
        "WindowsForms10.Window.8.app.0.dynamic_ad1",
    )
    assert not is_open_bill_frame_identity(
        "Enter Bill To Edit",
        "OtherFrame",
        "WindowsForms10.Window.8.app.0.dynamic_ad1",
    )


def test_bill_search_frame_identity_matches_supplied_parent() -> None:
    assert is_bill_search_frame_identity(
        "Bill Records",
        "Frame1",
        "WindowsForms10.Window.8.app.0.dynamic_ad1",
    )
    assert not is_bill_search_frame_identity(
        "Enter Bill To Edit",
        "Frame1",
        "WindowsForms10.Window.8.app.0.dynamic_ad1",
    )


def test_find_bill_search_frame_follows_supplied_hierarchy(
    monkeypatch,
) -> None:
    winforms_class = "WindowsForms10.Window.8.app.0.dynamic_ad1"
    frame = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="Frame1",
            class_name=winforms_class,
            name="Bill Records",
        ),
        window_text=lambda: "Bill Records",
    )
    bill_search = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="frmBillSearch",
            class_name=winforms_class,
            control_type="Window",
            name="Bill Search",
        ),
    )
    root = SimpleNamespace(descendants=lambda: [bill_search])

    monkeypatch.setattr(
        "smartadvisor_automation.probe.find_direct_uia_control",
        lambda _backend, parent, automation_id: (
            frame
            if parent is bill_search and automation_id == "Frame1"
            else None
        ),
    )

    assert find_bill_search_frame("uia", [root]) is frame


def test_find_open_bill_frame_follows_native_parent_chain(
    monkeypatch,
) -> None:
    winforms_class = "WindowsForms10.Window.8.app.0.dynamic_ad1"
    windows = {
        200: (True, "Open Bill", winforms_class),
        300: (True, "Enter Bill To Edit", winforms_class),
    }
    children = {100: [200], 200: [300]}
    fake_win32gui = SimpleNamespace(
        EnumChildWindows=lambda parent, callback, context: [
            callback(hwnd, context) for hwnd in children.get(parent, [])
        ],
        IsWindowVisible=lambda hwnd: windows[hwnd][0],
        GetWindowText=lambda hwnd: windows[hwnd][1],
        GetClassName=lambda hwnd: windows[hwnd][2],
        GetForegroundWindow=lambda: 0,
        GetWindowRect=lambda hwnd: (0, 0, hwnd, hwnd),
    )

    open_bill = SimpleNamespace(
        element_info=SimpleNamespace(
            handle=200,
            automation_id="",
            class_name=winforms_class,
            name="Open Bill",
        ),
        window_text=lambda: "Open Bill",
    )
    frame = SimpleNamespace(
        element_info=SimpleNamespace(
            handle=300,
            automation_id="Frame1",
            class_name=winforms_class,
            name="Enter Bill To Edit",
        ),
        window_text=lambda: "Enter Bill To Edit",
    )
    wrappers = {200: open_bill, 300: frame}
    fake_pywinauto = SimpleNamespace(
        Desktop=lambda backend: SimpleNamespace(
            window=lambda *, handle: wrappers[handle]
        )
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "win32gui",
        fake_win32gui,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "pywinauto",
        fake_pywinauto,
    )
    main_window = SimpleNamespace(
        element_info=SimpleNamespace(handle=100)
    )

    assert find_open_bill_frame("uia", main_window) is frame


def test_find_open_bill_frame_searches_process_top_level_windows(
    monkeypatch,
) -> None:
    winforms_class = "WindowsForms10.Window.8.app.0.dynamic_ad1"
    frame = SimpleNamespace(
        element_info=SimpleNamespace(
            handle=300,
            automation_id="Frame1",
            class_name=winforms_class,
            name="Enter Bill To Edit",
        ),
        window_text=lambda: "Enter Bill To Edit",
    )
    open_bill = SimpleNamespace(
        element_info=SimpleNamespace(
            handle=200,
            automation_id="",
            class_name=winforms_class,
            name="Open Bill",
        ),
        window_text=lambda: "Open Bill",
        descendants=lambda: [frame],
    )
    main_window = SimpleNamespace(
        element_info=SimpleNamespace(handle=100, process_id=1234),
    )

    class FakeDesktop:
        def windows(self):
            return [main_window, open_bill]

    fake_pywinauto = SimpleNamespace(
        Desktop=lambda backend: FakeDesktop(),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "pywinauto",
        fake_pywinauto,
    )

    assert find_open_bill_frame("uia", main_window) is frame


def test_find_open_bill_frame_matches_open_bill_on_different_process(
    monkeypatch,
) -> None:
    """A Citrix-hosted modal may not share the main window's process ID."""

    winforms_class = "WindowsForms10.Window.8.app.0.dynamic_ad1"
    frame = SimpleNamespace(
        element_info=SimpleNamespace(
            handle=300,
            automation_id="Frame1",
            class_name=winforms_class,
            name="Enter Bill To Edit",
        ),
        window_text=lambda: "Enter Bill To Edit",
    )
    open_bill = SimpleNamespace(
        element_info=SimpleNamespace(
            handle=200,
            automation_id="",
            class_name=winforms_class,
            name="Open Bill",
            process_id=9999,
        ),
        window_text=lambda: "Open Bill",
        descendants=lambda: [frame],
    )
    main_window = SimpleNamespace(
        element_info=SimpleNamespace(handle=100, process_id=1234),
    )

    class FakeDesktop:
        def windows(self):
            return [main_window, open_bill]

    fake_pywinauto = SimpleNamespace(
        Desktop=lambda backend: FakeDesktop(),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "pywinauto",
        fake_pywinauto,
    )

    assert find_open_bill_frame("uia", main_window) is frame


def test_find_open_bill_frame_uses_extractor_proven_uia_chain(
    monkeypatch,
) -> None:
    winforms_class = "WindowsForms10.Window.8.app.0.dynamic_ad1"
    action_info = SimpleNamespace(
        automation_id="_cmdSearch_1",
        name="",
        control_type="Button",
        class_name=winforms_class,
        handle=400,
        children=lambda: [],
    )
    frame_info = SimpleNamespace(
        automation_id="Frame1",
        name="Enter Bill To Edit",
        control_type="Group",
        class_name=winforms_class,
        handle=300,
        children=lambda: [action_info],
    )
    open_bill_info = SimpleNamespace(
        automation_id="frmBillOpen",
        name="Open Bill",
        control_type="Window",
        class_name=winforms_class,
        handle=200,
        process_id=1234,
        children=lambda: [frame_info],
    )
    main_window = SimpleNamespace(
        element_info=SimpleNamespace(handle=100, process_id=1234)
    )
    open_bill = SimpleNamespace(element_info=open_bill_info)
    frame = SimpleNamespace(element_info=frame_info)
    action = SimpleNamespace(element_info=action_info)

    class FakeDesktop:
        def windows(self):
            return [main_window, open_bill]

        def window(self, **criteria):
            assert criteria["handle"] in {300, 400}
            return frame if criteria["handle"] == 300 else action

    fake_pywinauto = SimpleNamespace(
        Desktop=lambda backend: FakeDesktop()
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "pywinauto",
        fake_pywinauto,
    )

    assert find_open_bill_frame("uia", main_window) is frame
    assert (
        find_direct_uia_control("uia", frame, "_cmdSearch_1")
        is action
    )


def test_native_enumeration_filters_by_title_class_and_visibility(
    monkeypatch,
) -> None:
    windows = {
        10: (
            True,
            "SmartAdvisor Main System",
            "WindowsForms10.Window.8.app.0.dynamic_ad1",
        ),
        20: (
            True,
            "Welcome - SmartAdvisor - Visual Studio Code",
            "Chrome_WidgetWin_1",
        ),
        30: (
            False,
            "SmartAdvisor Main System",
            "WindowsForms10.Window.8.app.0.hidden_ad1",
        ),
    }

    fake_win32gui = SimpleNamespace(
        EnumWindows=lambda callback, context: [
            callback(hwnd, context) for hwnd in windows
        ],
        IsWindowVisible=lambda hwnd: windows[hwnd][0],
        GetWindowText=lambda hwnd: windows[hwnd][1],
        GetClassName=lambda hwnd: windows[hwnd][2],
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "win32gui",
        fake_win32gui,
    )

    assert _native_smartadvisor_handles() == [10]


def test_native_handle_prefers_foreground_match(monkeypatch) -> None:
    fake_win32gui = SimpleNamespace(
        GetForegroundWindow=lambda: 20,
        GetWindowRect=lambda hwnd: (0, 0, hwnd, hwnd),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "win32gui",
        fake_win32gui,
    )

    assert _preferred_native_handle([10, 20]) == 20

