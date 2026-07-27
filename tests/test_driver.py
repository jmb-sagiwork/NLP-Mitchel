from types import SimpleNamespace

import pytest

from smartadvisor_automation.driver import SmartAdvisorDriver
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
    driver = SmartAdvisorDriver(poll_interval=0.01)

    assert driver.attach(CONTROLS_BY_STEP["1"], timeout=1.0) == "uia"
    assert attempts["count"] >= 3


def test_attach_sends_ctrl_o_when_open_bill_not_open(monkeypatch) -> None:
    """If Open Bill isn't open yet, attach should send Ctrl+O to the main
    window (the app's own accelerator for opening it), then keep polling
    for it to render."""

    calls = {"set_focus": 0, "type_keys": []}
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234),
        set_focus=lambda: calls.__setitem__(
            "set_focus", calls["set_focus"] + 1
        ),
        type_keys=lambda keys: calls["type_keys"].append(keys),
    )

    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend, **_kwargs: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window, **_kwargs: None,
    )
    driver = SmartAdvisorDriver(poll_interval=0.01)

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.2)

    assert (
        captured.value.code
        == "smartadvisor_open_bill_frame_not_accessible"
    )
    assert calls["set_focus"] == 1
    assert calls["type_keys"] == ["^o"]

    launch_steps = [
        step
        for step in captured.value.diagnostics["steps"]
        if step["stage"] == "open_bill_launch"
    ]
    assert [step["outcome"] for step in launch_steps] == ["shortcut_sent"]
