"""Dark theme for the teaching window.

Re-exports the shared AURA palette from `mitchel_qt` - this used to be a
second, blue-accented theme independent from mitchel_pipeline's teal one;
the accent is now locked to one color across both windows. Pill/Meter used
to be hand-drawn on a Tk Canvas ("Tk has no rounded rectangle, so it is
drawn"); Qt has native rounded corners, so those now live in mitchel_qt.widgets.
"""

from __future__ import annotations

from mitchel_qt.theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_HOVER,
    BG,
    BORDER,
    BORDER_SOFT,
    DANGER,
    ELEVATED,
    NEUTRAL,
    OK,
    STATUS_COLORS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
    WARN,
    Fonts,
    apply_theme,
    set_class,
)
from mitchel_qt.widgets import ConfidenceMeter as Meter
from mitchel_qt.widgets import Pill

__all__ = [
    "ACCENT",
    "ACCENT_DIM",
    "ACCENT_HOVER",
    "BG",
    "BORDER",
    "BORDER_SOFT",
    "DANGER",
    "ELEVATED",
    "Meter",
    "NEUTRAL",
    "OK",
    "Pill",
    "STATUS_COLORS",
    "SURFACE",
    "TEXT",
    "TEXT_DIM",
    "TEXT_FAINT",
    "WARN",
    "Fonts",
    "apply_theme",
    "set_class",
]
