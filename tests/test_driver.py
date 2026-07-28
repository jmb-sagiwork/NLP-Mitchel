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
        element_info=SimpleNamespace(automation_id="_cmdSearch_1"),
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
        element_info=SimpleNamespace(automation_id="394450"),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )
    bill_records = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="Frame1"),
        descendants=lambda: [search_button],
    )
    monkeypatch.setattr(
        driver,
        "_windows_for_process",
        lambda: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        "smartadvisor_automation.driver.find_bill_search_frame",
        lambda _backend, _roots: bill_records,
    )

    assert (
        driver.resolve(CONTROLS_BY_STEP["2"], timeout=0.1)
        is search_button
    )


def test_attach_retries_while_open_bill_still_renders(monkeypatch) -> None:
    """Open Bill can take a moment to register; attach should poll for it."""

    landmark = SimpleNamespace(
        element_info=SimpleNamespace(automation_id="_cmdSearch_1"),
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


def test_attach_sends_ctrl_o_only_once(monkeypatch) -> None:
    calls = {"focus": 0, "keys": []}
    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234),
        set_focus=lambda: calls.__setitem__("focus", calls["focus"] + 1),
        type_keys=lambda keys: calls["keys"].append(keys),
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
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.3)

    assert calls == {"focus": 1, "keys": ["^o"]}
    launch_steps = [
        step
        for step in captured.value.diagnostics["steps"]
        if step["stage"] == "open_bill_launch"
    ]
    assert [step["outcome"] for step in launch_steps] == [
        "shortcut_sent",
    ]


def test_attach_records_ctrl_o_failure(monkeypatch) -> None:
    def fail_focus():
        raise RuntimeError("cannot focus")

    window = SimpleNamespace(
        element_info=SimpleNamespace(process_id=1234),
        set_focus=fail_focus,
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
        driver.attach(CONTROLS_BY_STEP["1"], timeout=0.3)

    launch_steps = [
        step
        for step in captured.value.diagnostics["steps"]
        if step["stage"] == "open_bill_launch"
    ]
    assert [step["outcome"] for step in launch_steps] == [
        "shortcut_failed",
    ]
    assert launch_steps[0]["exception"] == "RuntimeError"


def test_invoke_uses_uia_invoke_pattern(monkeypatch) -> None:
    calls: list[str] = []
    element = SimpleNamespace(
        iface_invoke=SimpleNamespace(
            Invoke=lambda: calls.append("invoke")
        )
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.invoke(CONTROLS_BY_STEP["1"])

    assert calls == ["invoke"]


def test_click_with_invoke_fallback_stops_after_confirmed_click(
    monkeypatch,
) -> None:
    calls: list[str] = []
    element = SimpleNamespace(
        set_focus=lambda: calls.append("focus"),
        click_input=lambda: calls.append("click"),
        iface_invoke=SimpleNamespace(
            Invoke=lambda: calls.append("invoke")
        ),
    )
    driver = SmartAdvisorDriver()

    def resolve(spec, *, timeout=None):
        if spec.step == "1":
            return element
        calls.append(f"confirm:{timeout}")
        return SimpleNamespace()

    monkeypatch.setattr(driver, "resolve", resolve)

    driver.click_with_invoke_fallback(
        CONTROLS_BY_STEP["1"],
        CONTROLS_BY_STEP["2"],
    )

    assert calls == ["focus", "click", "confirm:2.0"]


def test_click_with_invoke_fallback_invokes_after_no_result(
    monkeypatch,
) -> None:
    calls: list[str] = []
    element = SimpleNamespace(
        set_focus=lambda: calls.append("focus"),
        click_input=lambda: calls.append("click"),
        iface_invoke=SimpleNamespace(
            Invoke=lambda: calls.append("invoke")
        ),
    )
    driver = SmartAdvisorDriver()

    def resolve(spec, *, timeout=None):
        if spec.step == "1":
            return element
        calls.append(f"confirm:{timeout}")
        raise AutomationError("selector_not_found", step=spec.step)

    monkeypatch.setattr(driver, "resolve", resolve)

    driver.click_with_invoke_fallback(
        CONTROLS_BY_STEP["1"],
        CONTROLS_BY_STEP["2"],
    )

    assert calls == ["focus", "click", "confirm:2.0", "invoke"]


def test_click_with_invoke_fallback_invokes_after_click_error(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fail_click():
        calls.append("click")
        raise RuntimeError("mouse input failed")

    element = SimpleNamespace(
        set_focus=lambda: calls.append("focus"),
        click_input=fail_click,
        iface_invoke=SimpleNamespace(
            Invoke=lambda: calls.append("invoke")
        ),
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.click_with_invoke_fallback(
        CONTROLS_BY_STEP["1"],
        CONTROLS_BY_STEP["2"],
    )

    assert calls == ["focus", "click", "invoke"]


def test_clear_uses_edit_value_pattern(monkeypatch) -> None:
    calls: list[str] = []
    element = SimpleNamespace(
        set_edit_text=lambda value: calls.append(f"value:{value}"),
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.clear(CONTROLS_BY_STEP["2"])

    assert calls == ["value:"]


def test_clear_falls_back_to_keyboard_input(monkeypatch) -> None:
    calls: list[str] = []

    def fail_value(_value: str) -> None:
        calls.append("value_failed")
        raise RuntimeError("ValuePattern failed")

    element = SimpleNamespace(
        set_edit_text=fail_value,
        set_focus=lambda: calls.append("focus"),
        click_input=lambda: calls.append("click"),
        type_keys=lambda keys, **kwargs: calls.append(
            f"keys:{keys}:{kwargs['set_foreground']}"
        ),
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.clear(CONTROLS_BY_STEP["2"])

    assert calls == [
        "value_failed",
        "focus",
        "click",
        "keys:^a{BACKSPACE}:True",
    ]
