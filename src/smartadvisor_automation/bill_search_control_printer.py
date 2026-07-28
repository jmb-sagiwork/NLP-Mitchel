from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pywinauto import Application

BILL_SEARCH_TITLE = "Bill Search"
BILL_SEARCH_AUTOMATION_ID = "frmBillSearch"


def print_bill_search_controls(
    application_factory: Callable[..., Any] = Application,
) -> None:
    """Connect to Bill Search and print its complete UIA control tree."""

    app = application_factory(backend="uia").connect(
        title=BILL_SEARCH_TITLE,
    )
    window = app.window(
        title=BILL_SEARCH_TITLE,
        auto_id=BILL_SEARCH_AUTOMATION_ID,
        control_type="Window",
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
        "Warning: printed control text can include values currently "
        "visible in SmartAdvisor."
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
            "Expected window: title='Bill Search', "
            "AutomationId='frmBillSearch', ControlType='Window'."
        )
    finally:
        _pause()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
