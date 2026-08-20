"""PyInstaller entry point for the SmartAdvisor JSON-lines helper."""

from __future__ import annotations

from mitchel_pipeline.smartadvisor_helper import main


if __name__ == "__main__":
    raise SystemExit(main())
