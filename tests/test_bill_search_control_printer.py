from types import SimpleNamespace

import pytest

from smartadvisor_automation.bill_search_control_printer import (
    BILL_SEARCH_AUTOMATION_ID,
    BILL_SEARCH_TITLE,
    MAIN_WINDOW_TITLE,
    print_bill_search_controls,
)


class FakeElement:
    def __init__(
        self,
        *,
        name: str,
        automation_id: str,
        control_type: str,
        handle: int = 1234,
    ) -> None:
        self.element_info = SimpleNamespace(
            name=name,
            automation_id=automation_id,
            control_type=control_type,
        )
        self.handle = handle


def element(
    *,
    name: str = BILL_SEARCH_TITLE,
    automation_id: str = BILL_SEARCH_AUTOMATION_ID,
    control_type: str = "Window",
) -> FakeElement:
    return FakeElement(
        name=name,
        automation_id=automation_id,
        control_type=control_type,
    )


def run_with_descendants(
    descendants: list[FakeElement],
) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []
    main = SimpleNamespace(
        descendants=lambda **kwargs: (
            calls.append(("descendants", kwargs)) or descendants
        ),
    )
    window = SimpleNamespace(
        wait=lambda state, timeout: calls.append(
            ("match_wait", state, timeout)
        ),
        print_control_identifiers=lambda: calls.append(("print",)),
    )

    def window_finder(backend):
        calls.append(("find_main", backend))
        return main

    class FakeDesktop:
        def window(self, **kwargs):
            calls.append(("window", kwargs))
            return window

    def desktop_factory(**kwargs):
        calls.append(("desktop", kwargs))
        return FakeDesktop()

    print_bill_search_controls(window_finder, desktop_factory)
    return calls


def test_print_bill_search_controls_finds_exact_nested_window() -> None:
    calls = run_with_descendants(
        [
            element(name="Open Bill", automation_id="frmBillOpen"),
            element(name="Wrong title"),
            element(automation_id="wrongAutomationId"),
            element(control_type="Pane"),
            element(),
        ]
    )

    assert BILL_SEARCH_TITLE == "Bill Search"
    assert BILL_SEARCH_AUTOMATION_ID == "frmBillSearch"
    assert MAIN_WINDOW_TITLE == "SmartAdvisor Main System"
    assert calls == [
        ("find_main", "uia"),
        ("descendants", {"control_type": "Window"}),
        ("desktop", {"backend": "uia"}),
        ("window", {"handle": 1234}),
        ("match_wait", "exists visible enabled", 15),
        ("print",),
    ]


@pytest.mark.parametrize("match_count", [0, 2])
def test_print_bill_search_controls_requires_one_exact_match(
    match_count: int,
) -> None:
    with pytest.raises(
        RuntimeError,
        match=rf"found {match_count}\.",
    ):
        run_with_descendants([element() for _ in range(match_count)])


def test_print_bill_search_controls_reports_missing_main_window() -> None:
    def window_finder(_backend):
        return None

    with pytest.raises(
        RuntimeError,
        match="Could not find the 'SmartAdvisor Main System'",
    ):
        print_bill_search_controls(window_finder)
