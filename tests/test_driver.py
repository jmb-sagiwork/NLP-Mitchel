from types import SimpleNamespace

import pytest

from smartadvisor_automation.driver import SmartAdvisorDriver
from smartadvisor_automation.errors import AutomationError
from smartadvisor_automation.selectors import CONTROLS_BY_STEP


def test_attach_reports_window_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend: None,
    )
    driver = SmartAdvisorDriver()

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"])

    assert captured.value.code == "smartadvisor_window_not_found"


def test_attach_reports_open_bill_frame_not_accessible(monkeypatch) -> None:
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234)
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window: None,
    )
    driver = SmartAdvisorDriver()

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"])

    assert (
        captured.value.code
        == "smartadvisor_open_bill_frame_not_accessible"
    )


def test_attach_reports_inaccessible_controls(monkeypatch) -> None:
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234)
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window: SimpleNamespace(),
    )
    driver = SmartAdvisorDriver()

    def fail_resolve(_spec, *, timeout=None):
        raise AutomationError("selector_not_found")

    monkeypatch.setattr(driver, "resolve", fail_resolve)

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"])

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
        lambda _backend: window,
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_open_bill_frame",
        lambda _backend, _window: frame,
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
