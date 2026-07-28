from types import SimpleNamespace

from smartadvisor_automation.bill_search_control_printer import (
    BILL_SEARCH_AUTOMATION_ID,
    BILL_SEARCH_TITLE,
    print_bill_search_controls,
)


def test_print_bill_search_controls_uses_exact_window_identity() -> None:
    calls: list[tuple[object, ...]] = []
    window = SimpleNamespace(
        wait=lambda state, timeout: calls.append(
            ("wait", state, timeout)
        ),
        print_control_identifiers=lambda: calls.append(("print",)),
    )

    class FakeApplication:
        def connect(self, **kwargs):
            calls.append(("connect", kwargs))
            return self

        def window(self, **kwargs):
            calls.append(("window", kwargs))
            return window

    def application_factory(**kwargs):
        calls.append(("factory", kwargs))
        return FakeApplication()

    print_bill_search_controls(application_factory)

    assert BILL_SEARCH_TITLE == "Bill Search"
    assert BILL_SEARCH_AUTOMATION_ID == "frmBillSearch"
    assert calls == [
        ("factory", {"backend": "uia"}),
        ("connect", {"title": "Bill Search"}),
        (
            "window",
            {
                "title": "Bill Search",
                "auto_id": "frmBillSearch",
                "control_type": "Window",
            },
        ),
        ("wait", "exists visible enabled", 15),
        ("print",),
    ]
