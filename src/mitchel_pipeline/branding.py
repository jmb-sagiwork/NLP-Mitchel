"""Locates the AURA icon/logo assets in both dev and frozen (PyInstaller) runs.

Mirrors the sys._MEIPASS resolution pattern used by helper_client.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DEV_RESOURCES = Path(__file__).resolve().parent / "resources"


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle / "mitchel_pipeline" / "resources"
    return _DEV_RESOURCES


ICON_PATH = _resource_dir() / "AURA.ico"
LOGO_PATH = _resource_dir() / "brand_logo.png"
