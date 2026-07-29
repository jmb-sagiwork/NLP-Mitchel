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
        element_info=SimpleNamespace(automation_id="txtClient"),
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


def test_focus_grid_clicks_even_when_set_focus_fails(monkeypatch) -> None:
    """Arrow keys only work once focus is genuinely inside the pane."""

    calls: list[str] = []

    def fail_focus() -> None:
        calls.append("focus_failed")
        raise RuntimeError("cannot focus a custom pane")

    element = SimpleNamespace(
        set_focus=fail_focus,
        click_input=lambda: calls.append("click"),
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.focus_grid(CONTROLS_BY_STEP["7.0"])

    assert calls == ["focus_failed", "click"]


def test_focus_grid_reports_failure_when_the_click_fails(monkeypatch) -> None:
    def fail_click() -> None:
        raise RuntimeError("mouse input failed")

    element = SimpleNamespace(
        set_focus=lambda: None,
        click_input=fail_click,
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    with pytest.raises(AutomationError) as captured:
        driver.focus_grid(CONTROLS_BY_STEP["7.0"])

    assert captured.value.code == "focus_failed"
    assert captured.value.step == "7.0"


def test_send_keys_types_into_the_focused_control(monkeypatch) -> None:
    calls: list[str] = []
    element = SimpleNamespace(
        type_keys=lambda keys, **kwargs: calls.append(
            f"{keys}:{kwargs['set_foreground']}"
        ),
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.send_keys(CONTROLS_BY_STEP["7.1"], "{DOWN}{DOWN}")

    assert calls == ["{DOWN}{DOWN}:True"]


def test_send_keys_skips_an_empty_seek(monkeypatch) -> None:
    """Row 0 needs no seek presses, so nothing should be resolved."""

    resolved: list[str] = []
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(
        driver,
        "resolve",
        lambda spec: resolved.append(spec.step) or SimpleNamespace(),
    )

    driver.send_keys(CONTROLS_BY_STEP["7.1"], "")

    assert resolved == []


def test_send_keys_wraps_failures(monkeypatch) -> None:
    def fail_type(_keys, **_kwargs):
        raise RuntimeError("keyboard blocked")

    driver = SmartAdvisorDriver()
    monkeypatch.setattr(
        driver,
        "resolve",
        lambda _spec: SimpleNamespace(type_keys=fail_type),
    )

    with pytest.raises(AutomationError) as captured:
        driver.send_keys(CONTROLS_BY_STEP["7.1"], "{DOWN}")

    assert captured.value.code == "send_keys_failed"


def test_send_window_keys_sends_the_accelerator(monkeypatch) -> None:
    calls: list[str] = []
    element = SimpleNamespace(
        set_focus=lambda: calls.append("focus"),
        type_keys=lambda keys, **kwargs: calls.append(f"keys:{keys}"),
    )
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.send_window_keys(CONTROLS_BY_STEP["7.4"], "%l")

    assert calls == ["focus", "keys:%l"]


def test_send_window_keys_wraps_failures(monkeypatch) -> None:
    def fail_type(_keys, **_kwargs):
        raise RuntimeError("window not accepting input")

    driver = SmartAdvisorDriver()
    monkeypatch.setattr(
        driver,
        "resolve",
        lambda _spec: SimpleNamespace(
            set_focus=lambda: None,
            type_keys=fail_type,
        ),
    )

    with pytest.raises(AutomationError) as captured:
        driver.send_window_keys(CONTROLS_BY_STEP["7.4"], "%l")

    assert captured.value.code == "window_keys_failed"


def test_is_present_reports_absence_without_raising(monkeypatch) -> None:
    driver = SmartAdvisorDriver()

    def missing(_spec, *, timeout=None):
        raise AutomationError("selector_not_found")

    monkeypatch.setattr(driver, "resolve", missing)

    assert driver.is_present(CONTROLS_BY_STEP["7.3"]) is False

    monkeypatch.setattr(
        driver, "resolve", lambda _spec, *, timeout=None: SimpleNamespace()
    )

    assert driver.is_present(CONTROLS_BY_STEP["7.3"]) is True


def test_scoped_selector_searches_only_inside_its_container(
    monkeypatch,
) -> None:
    """Every window owns a Close button, so the scope is what makes it safe."""

    wanted = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="",
            name="Close",
            control_type="Button",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )
    other_close = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="",
            name="Close",
            control_type="Button",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )
    bill_window = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="frmBillEntry",
            name="Bill: redacted",
            control_type="Window",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
        descendants=lambda: [wanted],
    )
    main_window = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="bilMain",
            name="SmartAdvisor Main System",
            control_type="Window",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
        descendants=lambda: [bill_window, wanted, other_close],
    )

    driver = SmartAdvisorDriver(poll_interval=0.01)
    driver.backend = "uia"
    driver.process_id = 1234
    monkeypatch.setattr(
        driver, "_windows_for_process", lambda: [main_window]
    )

    assert driver.resolve(CONTROLS_BY_STEP["7.6"], timeout=0.2) is wanted


def test_scoped_selector_fails_when_the_container_is_absent(
    monkeypatch,
) -> None:
    main_window = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="bilMain",
            name="SmartAdvisor Main System",
            control_type="Window",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
        descendants=lambda: [],
    )

    driver = SmartAdvisorDriver(poll_interval=0.01)
    driver.backend = "uia"
    driver.process_id = 1234
    monkeypatch.setattr(
        driver, "_windows_for_process", lambda: [main_window]
    )

    with pytest.raises(AutomationError) as captured:
        driver.resolve(CONTROLS_BY_STEP["7.6"], timeout=0.1)

    assert captured.value.code == "selector_not_found"


def test_log_lines_describe_selectors_without_values(monkeypatch) -> None:
    lines: list[str] = []
    element = SimpleNamespace(
        set_focus=lambda: None,
        click_input=lambda: None,
    )
    driver = SmartAdvisorDriver(log=lines.append)
    monkeypatch.setattr(driver, "resolve", lambda _spec: element)

    driver.click(CONTROLS_BY_STEP["7.2"])
    driver.focus_grid(CONTROLS_BY_STEP["7.0"])

    assert lines == [
        "click cmdOk",
        "focus fpSearchResult",
    ]


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
