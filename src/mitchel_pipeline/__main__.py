from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mitchel-nlp")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run a headless packaged-app diagnostic and write mitchel-selftest.json",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        from .selftest import selftest

        return selftest()

    from .app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
