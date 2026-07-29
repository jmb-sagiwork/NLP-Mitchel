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


class FakeRect:
    def __init__(self, top: int) -> None:
        self.top = top


class FakeTabControl:
    """A tab control whose Name is whichever page is selected.

    That is the real behaviour: it publishes only the selected page's
    children and its Name is that page's text. `responds_to` lists the
    keystrokes that actually move the strip, so a test can model the
    accelerator working, the arrows working, or nothing working.
    """

    def __init__(
        self,
        pages: list[str],
        *,
        responds_to: tuple[str, ...] = ("{RIGHT}",),
        selected: int = 0,
        needs_strip_click: bool = False,
    ) -> None:
        self.pages = pages
        self.selected = selected
        self.responds_to = responds_to
        self.needs_strip_click = needs_strip_click
        self.strip_clicked = False
        self.keys: list[str] = []

    def set_focus(self) -> None:
        pass

    def rectangle(self) -> FakeRect:
        return FakeRect(325)

    def children(self):
        return [SimpleNamespace(rectangle=lambda: FakeRect(349))]

    def click_input(self, coords=None) -> None:
        self.strip_clicked = True

    def window_text(self) -> str:
        return self.pages[self.selected]

    def type_keys(self, keys: str, **_kwargs) -> None:
        self.keys.append(keys)
        if keys not in self.responds_to:
            return
        if self.needs_strip_click and not self.strip_clicked:
            return
        self.selected = (self.selected + 1) % len(self.pages)


def select_lines_tab(driver, tab, monkeypatch) -> None:
    monkeypatch.setattr(driver, "resolve", lambda _spec: tab)
    driver.select_tab(
        CONTROLS_BY_STEP["7.4"],
        expected_fragment="Lines",
        accelerator="%l",
        next_key="{RIGHT}",
        fallback_key="^{TAB}",
        max_presses=12,
        settle_timeout=0.05,
    )


def test_select_tab_uses_the_accelerator_when_it_works(monkeypatch) -> None:
    tab = FakeTabControl(["  Hea&der", " &Lines(10)"], responds_to=("%l",))
    driver = SmartAdvisorDriver(poll_interval=0.01)

    select_lines_tab(driver, tab, monkeypatch)

    assert tab.keys == ["%l"]
    assert "Lines" in tab.window_text()


def test_select_tab_falls_back_to_arrows_when_the_accelerator_is_inert(
    monkeypatch,
) -> None:
    """0.4.0's symptom: %l changes nothing, so arrowing has to take over."""

    tab = FakeTabControl(
        ["  Hea&der", " &Codes", " &Lines(10)"], responds_to=("{RIGHT}",)
    )
    driver = SmartAdvisorDriver(poll_interval=0.01)

    select_lines_tab(driver, tab, monkeypatch)

    assert tab.keys[0] == "%l"
    assert tab.keys.count("{RIGHT}") == 2
    assert "Lines" in tab.window_text()


def test_select_tab_clicks_the_strip_before_arrowing(monkeypatch) -> None:
    """0.4.1's symptom: arrows do nothing until the strip holds focus."""

    tab = FakeTabControl(
        ["  Hea&der", " &Lines(10)"],
        responds_to=("{RIGHT}",),
        needs_strip_click=True,
    )
    driver = SmartAdvisorDriver(poll_interval=0.01)

    select_lines_tab(driver, tab, monkeypatch)

    assert tab.strip_clicked is True
    assert "Lines" in tab.window_text()


def test_select_tab_presses_nothing_when_already_on_the_page(
    monkeypatch,
) -> None:
    tab = FakeTabControl([" &Lines(10)", "  Hea&der"])
    driver = SmartAdvisorDriver(poll_interval=0.01)

    select_lines_tab(driver, tab, monkeypatch)

    assert tab.keys == []


def test_select_tab_tries_every_mechanism_then_fails(monkeypatch) -> None:
    tab = FakeTabControl(["  Hea&der", " &Codes"], responds_to=())
    driver = SmartAdvisorDriver(poll_interval=0.01)

    with pytest.raises(AutomationError) as captured:
        select_lines_tab(driver, tab, monkeypatch)

    assert captured.value.code == "tab_not_found"
    assert captured.value.step == "7.4"
    # An inert keystroke is not repeated: one of each is enough to know.
    assert tab.keys == ["%l", "{RIGHT}", "^{TAB}"]


def test_select_tab_reports_each_mechanism_it_tried(monkeypatch) -> None:
    lines: list[str] = []
    tab = FakeTabControl(
        ["  Hea&der", " &Lines(10)"], responds_to=("{RIGHT}",)
    )
    driver = SmartAdvisorDriver(poll_interval=0.01, log=lines.append)

    select_lines_tab(driver, tab, monkeypatch)

    joined = "\n".join(lines)
    assert "accelerator did not reach" in joined
    assert "reached via click_then_arrow" in joined
    # Tab names are logged verbatim: the line count was never sensitive and
    # one rule for the whole log is simpler than two.
    assert "Lines(10)" in joined


def test_scopes_are_cached_then_invalidated(monkeypatch) -> None:
    """Resolving a container walks window subtrees, so it must not repeat."""

    walks = {"count": 0}
    bill_window = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="frmBillEntry",
            name="Bill: redacted",
            control_type="Window",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
        descendants=lambda **_kwargs: [],
    )

    def descendants(**_kwargs):
        walks["count"] += 1
        return [bill_window]

    main_window = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="bilMain",
            name="SmartAdvisor Main System",
            control_type="Window",
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
        descendants=descendants,
    )

    driver = SmartAdvisorDriver(poll_interval=0.01)
    driver.backend = "uia"
    driver.process_id = 1234
    monkeypatch.setattr(
        driver, "_windows_for_process", lambda: [main_window]
    )

    assert driver._find_scope("frmBillEntry") is bill_window
    assert driver._find_scope("frmBillEntry") is bill_window
    assert walks["count"] == 1

    driver.invalidate_scopes()

    assert driver._find_scope("frmBillEntry") is bill_window
    assert walks["count"] == 2


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


def test_search_depth_caps_an_unscoped_walk(monkeypatch) -> None:
    """An unbounded walk costs seconds per level at Citrix COM latency."""

    depths: list[object] = []
    window = SimpleNamespace(
        element_info=SimpleNamespace(
            automation_id="bilMain", name="", control_type="Window"
        ),
        is_visible=lambda: True,
        is_enabled=lambda: True,
        descendants=lambda **kwargs: depths.append(kwargs.get("depth")) or [],
    )

    driver = SmartAdvisorDriver(poll_interval=0.01)
    driver.backend = "uia"
    driver.process_id = 1234
    monkeypatch.setattr(driver, "_windows_for_process", lambda: [window])

    with pytest.raises(AutomationError):
        driver.resolve(CONTROLS_BY_STEP["7.3"], timeout=0.05)

    assert depths and all(depth == 3 for depth in depths)


def test_scan_texts_reports_only_the_wanted_prefix(monkeypatch) -> None:
    def label(automation_id: str, text: str):
        return SimpleNamespace(
            element_info=SimpleNamespace(
                automation_id=automation_id, name="", control_type="Text"
            ),
            window_text=lambda: text,
        )

    scope = SimpleNamespace(
        descendants=lambda **_kwargs: [
            label("_lblTotals_47", "1,180.00 (5.00)"),
            label("_lblTotals_59", "12.34 (1.00)"),
            label("txtSomethingElse", "ignored"),
        ],
    )

    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "_find_scope", lambda _scope_id: scope)

    found = driver.scan_texts("frmBillEntry", "_lblTotals_")

    assert found == [
        ("_lblTotals_47", "1,180.00 (5.00)"),
        ("_lblTotals_59", "12.34 (1.00)"),
    ]


def test_scan_texts_returns_nothing_without_its_scope(monkeypatch) -> None:
    driver = SmartAdvisorDriver()
    monkeypatch.setattr(driver, "_find_scope", lambda _scope_id: None)

    assert driver.scan_texts("frmBillEntry", "_lblTotals_") == []


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
