from dataclasses import dataclass
from types import SimpleNamespace

from smartadvisor_automation.probe import (
    _native_smartadvisor_handles,
    _preferred_native_handle,
    is_smartadvisor_window_identity,
    selector_match_strategy,
)


@dataclass
class FakeElementInfo:
    automation_id: str = ""
    control_id: int | None = None


def test_named_automation_id_matches_exactly() -> None:
    info = FakeElementInfo(automation_id="cboClient", control_id=10)

    assert selector_match_strategy(info, "cboClient") == "automation_id"


def test_numeric_automation_id_can_match_control_id() -> None:
    info = FakeElementInfo(automation_id="", control_id=263892)

    assert selector_match_strategy(info, "263892") == "control_id"


def test_selector_does_not_match_partial_values() -> None:
    info = FakeElementInfo(automation_id="cboClientOther", control_id=263892)

    assert selector_match_strategy(info, "cboClient") is None


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

