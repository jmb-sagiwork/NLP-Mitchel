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
    ) -> None:
        self.element_info = SimpleNamespace(
            name=name,
            automation_id=automation_id,
            control_type=control_type,
        )
        self.calls: list[tuple[object, ...]] = []

    def wait(self, state: str, timeout: int) -> None:
        self.calls.append(("match_wait", state, timeout))

    def print_control_identifiers(self) -> None:
        self.calls.append(("print", self.element_info.name))


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

    class FakeApplication:
        def connect(self, **kwargs):
            calls.append(("connect", kwargs))
            return self

        def window(self, **kwargs):
            calls.append(("window", kwargs))
            return SimpleNamespace(
                wait=lambda state, timeout: calls.append(
                    ("main_wait", state, timeout)
                ),
                descendants=lambda **kwargs: (
                    calls.append(("descendants", kwargs)) or descendants
                ),
            )

    def application_factory(**kwargs):
        calls.append(("factory", kwargs))
        return FakeApplication()

    print_bill_search_controls(application_factory)

    for descendant in descendants:
        calls.extend(descendant.calls)
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
        ("factory", {"backend": "uia"}),
        ("connect", {"title": "SmartAdvisor Main System"}),
        ("window", {"title": "SmartAdvisor Main System"}),
        ("main_wait", "exists visible enabled", 15),
        ("descendants", {"control_type": "Window"}),
        ("match_wait", "exists visible enabled", 15),
        ("print", "Bill Search"),
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
