"""CLI: python -m email_triage {check-config,classify}

Engine-only on purpose. The teaching window lives in its own package and is
launched with `python -m email_triage_ui`, so nothing here imports tkinter and
a host that vendors the engine alone still gets a working CLI.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="email_triage")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("check-config", help="validate and lint concerns.json")

    c = sub.add_parser("classify", help="classify text from stdin")
    c.add_argument("--subject", default="")
    c.add_argument("--json", action="store_true", help="emit JSON instead of plain text")

    args = ap.parse_args()

    if args.cmd == "check-config":
        from .config import check_config, load_config

        cfg = load_config()
        print(f"config {cfg.config_version} / schema {cfg.schema_version}")
        print(f"{len(cfg.concerns)} concerns, {len(cfg.patterns)} patterns -- valid")
        warnings = check_config()
        if not warnings:
            print("no warnings")
            return 0
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
        return 0

    if args.cmd == "classify":
        from .api import classify_email
        from .render import to_json, to_plain_text

        body = sys.stdin.read()
        result = classify_email(body, args.subject)
        print(to_json(result) if args.json else to_plain_text(result))
        return 0

    ap.print_help()
    print("\nTeaching UI: python -m email_triage_ui")
    return 1


if __name__ == "__main__":
    sys.exit(main())
