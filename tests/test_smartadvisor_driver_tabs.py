from __future__ import annotations

from dataclasses import dataclass

from smartadvisor_automation.driver import SmartAdvisorDriver
from smartadvisor_automation.selectors import CONTROLS_BY_STEP


@dataclass
class _Rectangle:
    left: int = 0
    top: int = 0
    right: int = 400


class _Page:
    def rectangle(self) -> _Rectangle:
        return _Rectangle(top=24)


class _ClickOnlyHistoryTab:
    """Owner-drawn tab strip whose keyboard navigation is inert."""

    def __init__(self) -> None:
        self.name = "Hea&der"
        self.keys: list[str] = []
        self.clicks: list[tuple[int, int]] = []

    def window_text(self) -> str:
        return self.name

    def rectangle(self) -> _Rectangle:
        return _Rectangle()

    def children(self) -> list[_Page]:
        return [_Page()]

    def set_focus(self) -> None:
        return None

    def type_keys(self, keys: str, **_kwargs) -> None:
        self.keys.append(keys)

    def click_input(self, *, coords: tuple[int, int]) -> None:
        self.clicks.append(coords)
        if coords[0] == 35:
            self.name = " &His&tory"


def test_select_tab_scans_visible_strip_when_citrix_ignores_keys(
    monkeypatch,
) -> None:
    tab = _ClickOnlyHistoryTab()
    log: list[str] = []
    driver = SmartAdvisorDriver(poll_interval=0.001, log=log.append)
    monkeypatch.setattr(driver, "resolve", lambda _spec: tab)

    driver.select_tab(
        CONTROLS_BY_STEP["7.4"],
        expected_fragment="History",
        accelerator="%l",
        next_key="{RIGHT}",
        fallback_key="^{TAB}",
        max_presses=12,
        settle_timeout=0.001,
    )

    assert tab.name == " &His&tory"
    assert (35, 12) in tab.clicks
    assert "tab reached via scan_clicks" in log
    assert "^{TAB}" not in tab.keys


def test_tab_name_matching_ignores_rendered_accelerator_markers(
    monkeypatch,
) -> None:
    tab = _ClickOnlyHistoryTab()
    tab.name = " &His&tory"
    driver = SmartAdvisorDriver(poll_interval=0.001)
    monkeypatch.setattr(driver, "resolve", lambda _spec: tab)

    driver.select_tab(
        CONTROLS_BY_STEP["7.4"],
        expected_fragment="History",
        accelerator="%l",
        next_key="{RIGHT}",
        fallback_key="^{TAB}",
        max_presses=12,
        settle_timeout=0.001,
    )

    assert tab.keys == []
    assert tab.clicks == []


class _ElementInfo:
    def __init__(self, control_type: str) -> None:
        self.control_type = control_type


class _InnerEdit:
    def __init__(self) -> None:
        self.element_info = _ElementInfo("Edit")
        self.value = ""
        self.focused = False
        self.clicked = False

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def set_focus(self) -> None:
        self.focused = True

    def click_input(self) -> None:
        self.clicked = True

    def set_edit_text(self, value: str) -> None:
        self.value = value


class _ParentEdit:
    def __init__(self, child: _InnerEdit) -> None:
        self.child = child

    def descendants(self, *, depth: int):
        assert depth == 1
        return [self.child]


def test_input_child_edit_text_targets_inner_winforms_edit(monkeypatch) -> None:
    child = _InnerEdit()
    parent = _ParentEdit(child)
    driver = SmartAdvisorDriver(poll_interval=0.001)
    monkeypatch.setattr(driver, "resolve", lambda _spec: parent)

    driver.input_child_edit_text(CONTROLS_BY_STEP["8.2"], "BILL-77")

    assert child.value == "BILL-77"
    assert child.focused
    assert child.clicked
