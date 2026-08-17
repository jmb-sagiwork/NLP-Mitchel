"""CLI: python -m email_triage_ui [--selftest]"""

from __future__ import annotations

import sys


def main() -> int:
    if "--selftest" in sys.argv:
        from .selftest import selftest

        return selftest()
    from .app import main as ui_main

    ui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
