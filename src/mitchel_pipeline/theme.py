"""Compact dark theme for the Mitchel NLP control panel.

Re-exports the shared AURA palette from `mitchel_qt` (mitchel_pipeline still
does not depend on email_triage_ui, and each ships as its own PyInstaller
target - both just depend on the shared, UI-only mitchel_qt package).
"""

from __future__ import annotations

from mitchel_qt.theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_HOVER,
    ACCENT_TEXT,
    BG,
    BORDER,
    BORDER_SOFT,
    DANGER,
    ELEVATED,
    NEUTRAL,
    RADIUS,
    RADIUS_PILL,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
    Fonts,
    apply_theme,
    set_class,
)
from mitchel_qt.theme import WARN as WARNING

__all__ = [
    "ACCENT",
    "ACCENT_DIM",
    "ACCENT_HOVER",
    "ACCENT_TEXT",
    "BG",
    "BORDER",
    "BORDER_SOFT",
    "DANGER",
    "ELEVATED",
    "NEUTRAL",
    "RADIUS",
    "RADIUS_PILL",
    "SURFACE",
    "TEXT",
    "TEXT_DIM",
    "TEXT_FAINT",
    "WARNING",
    "Fonts",
    "apply_theme",
    "set_class",
]
