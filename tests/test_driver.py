from types import SimpleNamespace

import pytest

from smartadvisor_automation.driver import (
    SmartAdvisorDriver,
    open_bill_keyless,
)
from smartadvisor_automation.errors import AutomationError
from smartadvisor_automation.selectors import CONTROLS_BY_STEP


def test_attach_reports_window_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: None,
    )
    driver = SmartAdvisorDriver()

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.05)

    assert captured.value.code == "smartadvisor_window_not_found"
    assert captured.value.diagnostics is not None


def test_attach_reports_open_bill_frame_not_accessible(monkeypatch) -> None:
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234)
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window, **_kwargs: None,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.open_bill_keyless",
        lambda: None,
    )
    driver = SmartAdvisorDriver()

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.05)

    assert (
        captured.value.code
        == "smartadvisor_open_bill_frame_not_accessible"
    )
    assert captured.value.diagnostics is not None


def test_attach_reports_inaccessible_controls(monkeypatch) -> None:
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234)
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window, **_kwargs: SimpleNamespace(),
    )
    driver = SmartAdvisorDriver()

    def fail_resolve(_spec, *, timeout=None):
        raise AutomationError("selector_not_found")

    monkeypatch.setattr(driver, "resolve", fail_resolve)

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.05)

    assert captured.value.code == "smartadvisor_controls_not_accessible"


def test_attach_resolves_landmark_only_inside_open_bill_frame(
    monkeypatch,
) -> None:
    landmark = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="cboClient"),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )
    frame = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="Frame1"),
        descendants=lambda: [landmark],
    )
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234)
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window, **_kwargs: frame,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_direct_uia_control",
        lambda _backend, _parent, _automation_id: landmark,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.open_bill_keyless",
        lambda: None,
    )
    driver = SmartAdvisorDriver()

    assert driver.attach(CONTROLS_BY_STEP["1"]) == "uia"
    assert driver.resolve(CONTROLS_BY_STEP["1"], timeout=0.1) is landmark

    search_button = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="_cmdSearch_1"),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )
    later_window = SimpleNamespace(
        element_info=SimpleNamespace(automation_id=""),
        descendants=lambda: [search_button],
    )
    monkeypatch.setattr(
        driver,
        "_windows_for_process",
        lambda: [later_window],
    )

    assert (
        driver.resolve(CONTROLS_BY_STEP["2"], timeout=0.1)
        is search_button
    )


def test_attach_retries_while_open_bill_still_renders(monkeypatch) -> None:
    """Open Bill can take a moment to register; attach should poll for it."""

    landmark = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="cboClient"),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )
    frame = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="Frame1"),
        descendants=lambda: [landmark],
    )
    window = SimpleNamespace(element_info=SimpleNamespace(process_id=1234))

    attempts = {"count": 0}

    def flaky_find_open_bill_frame(_backend, _window, **_kwargs):
        attempts["count"] += 1
        return frame if attempts["count"] >= 3 else None

    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        flaky_find_open_bill_frame,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_direct_uia_control",
        lambda _backend, _parent, _automation_id: landmark,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.open_bill_keyless",
        lambda: None,
    )
    driver = SmartAdvisorDriver(poll_interval=0.01)

    assert driver.attach(CONTROLS_BY_STEP["1"], timeout=1.0) == "uia"
    assert attempts["count"] >= 3


def test_open_bill_keyless_invokes_legacy_default_action(
    monkeypatch,
) -> None:
    events: list[object] = []

    legacy = SimpleNamespace(
        DoDefaultAction=lambda: events.append("default_action")
    )
    button_wrapper = SimpleNamespace(iface_legacy_iaccessible=legacy)
    button = SimpleNamespace(
        wait=lambda state, timeout: events.append(
            ("button_wait", state, timeout)
        ),
        wrapper_object=lambda: button_wrapper,
    )

    def toolbar_child_window(**criteria):
        events.append(("button", criteria))
        return button

    toolbar = SimpleNamespace(
        wait=lambda state, timeout: events.append(
            ("toolbar_wait", state, timeout)
        ),
        child_window=toolbar_child_window,
    )

    def main_child_window(**criteria):
        events.append(("toolbar", criteria))
        return toolbar

    main = SimpleNamespace(
        wait=lambda state, timeout: events.append(
            ("main_wait", state, timeout)
        ),
        child_window=main_child_window,
    )
    dialog = SimpleNamespace(
        wait=lambda state, timeout: events.append(
            ("dialog_wait", state, timeout)
        )
    )

    def desktop_window(**criteria):
        events.append(("window", criteria))
        if criteria["auto_id"] == "bilMain":
            return main
        return dialog

    desktop = SimpleNamespace(window=desktop_window)
    monkeypatch.setattr(
        "pywinauto.Desktop",
        lambda backend: (
            events.append(("desktop", backend)) or desktop
        ),
    )

    open_bill_keyless()

    assert events == [
        ("desktop", "uia"),
        (
            "window",
            {"auto_id": "bilMain", "control_type": "Window"},
        ),
        ("main_wait", "exists visible enabled", 15),
        (
            "toolbar",
            {"auto_id": "Toolbar1", "control_type": "ToolBar"},
        ),
        ("toolbar_wait", "exists visible enabled", 10),
        ("button", {"title": "_Toolbar1_Button2"}),
        ("button_wait", "exists visible enabled", 10),
        "default_action",
        (
            "window",
            {"auto_id": "frmBillOpen", "control_type": "Window"},
        ),
        ("dialog_wait", "exists visible enabled", 5),
    ]


def test_attach_invokes_keyless_open_bill_only_once(
    monkeypatch,
) -> None:
    calls: list[str] = []
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234),
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window, **_kwargs: None,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.open_bill_keyless",
        lambda: calls.append("legacy_default_action"),
    )
    driver = SmartAdvisorDriver(poll_interval=0.01)

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.3)

    assert calls == ["legacy_default_action"]
    launch_steps = [
        step
        for step in captured.value.diagnostics["steps"]
        if step["stage"] == "open_bill_launch"
    ]
    assert [step["outcome"] for step in launch_steps] == [
        "legacy_default_action_completed",
    ]


def test_attach_records_keyless_open_bill_failure(monkeypatch) -> None:
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234),
    )

    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window, **_kwargs: None,
    )

    calls: list[str] = []

    def fail_keyless_action():
        calls.append("legacy_default_action")
        raise RuntimeError("Open Bill did not appear")

    monkeypatch.setattr(
        "smartadvisor_automation.driver.open_bill_keyless",
        fail_keyless_action,
    )
    driver = SmartAdvisorDriver(poll_interval=0.01)

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.3)

    assert calls == ["legacy_default_action"]
    launch_steps = [
        step
        for step in captured.value.diagnostics["steps"]
        if step["stage"] == "open_bill_launch"
    ]
    assert [step["outcome"] for step in launch_steps] == [
        "legacy_default_action_failed",
    ]
    assert launch_steps[0]["exception"] == "RuntimeError"
