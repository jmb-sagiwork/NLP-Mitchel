from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pywinauto import Desktop

from smartadvisor_automation.probe import find_smartadvisor_window


BILL_SEARCH_TITLE = "Bill Search"
BILL_SEARCH_AUTOMATION_ID = "frmBillSearch"
MAIN_WINDOW_TITLE = "SmartAdvisor Main System"


def print_bill_search_controls(
    window_finder: Callable[..., Any] = find_smartadvisor_window,
    desktop_factory: Callable[..., Any] = Desktop,
) -> None:
    """Find the nested Bill Search window and print its complete UIA tree."""
    main = window_finder("uia")
    if main is None:
        raise RuntimeError(
            f"Could not find the {MAIN_WINDOW_TITLE!r} top-level window."
        )

    matches = [
        element
        for element in main.descendants(control_type="Window")
        if element.element_info.name == BILL_SEARCH_TITLE
        and element.element_info.automation_id == BILL_SEARCH_AUTOMATION_ID
        and element.element_info.control_type == "Window"
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one nested Bill Search window "
            f"(Name={BILL_SEARCH_TITLE!r}, "
            f"AutomationId={BILL_SEARCH_AUTOMATION_ID!r}, "
            f"ControlType='Window'); found {len(matches)}."
        )

    window = desktop_factory(backend="uia").window(
        handle=matches[0].handle,
    )
    window.wait("exists visible enabled", timeout=15)
    window.print_control_identifiers()


def _pause() -> None:
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass


def main() -> int:
    print("SmartAdvisor Bill Search Control Printer")
    print("=" * 40)
    print("Open the Bill Search window before running this utility.")
    print(
        "Warning: printed text may include currently visible values "
        "in SmartAdvisor."
    )
    print()

    exit_code = 0
    try:
        print_bill_search_controls()
    except Exception as exc:
        exit_code = 1
        print("Could not inspect the Bill Search window.")
        print(f"{type(exc).__name__}: {exc}")
        print()
        print(
            "Expected one nested window below 'SmartAdvisor Main System': "
            "Name='Bill Search', AutomationId='frmBillSearch', "
            "ControlType='Window'."
        )
    finally:
        _pause()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
