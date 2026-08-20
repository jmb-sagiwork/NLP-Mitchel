"""PyInstaller entry point for the combined Mitchel desktop application."""

from __future__ import annotations

from mitchel_pipeline.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
