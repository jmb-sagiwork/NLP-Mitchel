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


def test_attach_reports_inaccessible_controls(monkeypatch) -> None:
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234)
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_smartadvisor_window",
        lambda _backend: window,
    )
    driver = SmartAdvisorDriver()

    def fail_resolve(_spec, *, timeout=None):
        raise AutomationError("selector_not_found")

    monkeypatch.setattr(driver, "resolve", fail_resolve)

    with pytest.raises(AutomationError) as captured:
        driver.attach(CONTROLS_BY_STEP["1"])

    assert captured.value.code == "smartadvisor_controls_not_accessible"
