"""CLI for the teaching harness.

    python -m email_triage_ui                      open the window
    python -m email_triage_ui --selftest           headless bundle diagnostic
    python -m email_triage_ui --proposals          what reviewers asked for
    python -m email_triage_ui --scaffold <id>      concerns.json block for one

The frozen exe routes through here too (`launcher.py`), so every flag works on
a machine with no Python. Note the exe is windowed and therefore has no
console: each flag that produces text also drops a file beside the executable.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="email_triage_ui", description="Teaching harness for the triage engine."
    )
    ap.add_argument("--selftest", action="store_true",
                    help="classify a known sample and write selftest.json")
    ap.add_argument("--proposals", action="store_true",
                    help="summarise concerns/reasons reviewers proposed")
    ap.add_argument("--scaffold", metavar="ID",
                    help="print a concerns.json block for a proposed id")
    args = ap.parse_args(argv)

    if args.selftest:
        from .selftest import selftest

        return selftest()

    if args.proposals:
        from .proposals import report

        return report()

    if args.scaffold:
        from .proposals import scaffold

        return scaffold(args.scaffold)

    from .app import main as ui_main

    ui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
