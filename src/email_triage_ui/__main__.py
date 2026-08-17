"""CLI: python -m email_triage_ui [--selftest | --proposals]"""

from __future__ import annotations

import sys


def main() -> int:
    if "--selftest" in sys.argv:
        from .selftest import selftest

        return selftest()
    if "--proposals" in sys.argv:
        from .proposals import report

        return report()
    from .app import main as ui_main

    ui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
