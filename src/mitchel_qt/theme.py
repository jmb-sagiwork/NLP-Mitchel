"""AURA dark theme: one accent, one radius scale, applied via QSS.

Replaces two divergent ttk themes (mitchel_pipeline had a teal accent,
email_triage_ui had a blue one). Native QSS `border-radius` also replaces the
old hand-drawn Tk Canvas Pill/Meter widgets - see widgets.py.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

BG = "#0b0f14"
SURFACE = "#121821"
ELEVATED = "#1a212b"
BORDER = "#232b36"
BORDER_SOFT = "#1e2530"

TEXT = "#e6edf3"
TEXT_DIM = "#8b98a8"
TEXT_FAINT = "#5b6674"

# Locked accent (was teal in mitchel_pipeline, blue in email_triage_ui).
ACCENT = "#2dd4bf"
ACCENT_HOVER = "#5fe4d3"
ACCENT_DIM = "#1f9a8a"
ACCENT_TEXT = "#04120f"  # dark text on the accent - passes WCAG AA

OK = "#3ecf8e"
WARN = "#fbbf24"
DANGER = "#ff6b6b"
NEUTRAL = "#5b6674"

STATUS_COLORS = {
    "CLASSIFIED": OK,
    "AMBIGUOUS": WARN,
    "UNCLASSIFIED": NEUTRAL,
    "ERROR": DANGER,
}

# One scale: cards/inputs/panels at RADIUS, pill chips/buttons at RADIUS_PILL.
RADIUS = 8
RADIUS_PILL = 11


def set_class(widget: QWidget, name: str) -> None:
    """Tag a widget for a QSS `[cssClass="..."]` rule. Call before first show."""
    widget.setProperty("cssClass", name)


def _pick_family() -> str:
    families = set(QFontDatabase.families())
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue"):
        if candidate in families:
            return candidate
    return QApplication.font().family()


def _pick_mono_family() -> str:
    families = set(QFontDatabase.families())
    for candidate in ("Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"):
        if candidate in families:
            return candidate
    return "Courier New"


class Fonts:
    def __init__(self) -> None:
        family = _pick_family()
        mono = _pick_mono_family()
        self.family = family
        self.mono_family = mono

        self.body = QFont(family, 10)
        self.body_bold = QFont(family, 10)
        self.body_bold.setBold(True)
        self.small = QFont(family, 9)
        self.tiny = QFont(family, 9)
        self.title = QFont(family, 12)
        self.title.setBold(True)
        self.h1 = QFont(family, 16)
        self.h1.setBold(True)
        self.h2 = QFont(family, 11)
        self.h2.setBold(True)
        self.mono = QFont(mono, 10)
        self.mono_value = QFont(mono, 10)


def build_qss(fonts: Fonts) -> str:
    return f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "{fonts.family}";
}}
QToolTip {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 6px;
}}

QFrame[cssClass="header"] {{ background: {SURFACE}; }}
QFrame[cssClass="surface"] {{ background: {SURFACE}; }}
QFrame[cssClass="card"] {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QFrame[cssClass="divider"] {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

QLabel {{ background: transparent; }}
QLabel[cssClass="dim"] {{ color: {TEXT_DIM}; }}
QLabel[cssClass="faint"] {{ color: {TEXT_FAINT}; }}
QLabel[cssClass="danger"] {{ color: {DANGER}; }}

QPushButton {{
    background: {ELEVATED};
    color: {TEXT};
    border: none;
    border-radius: {RADIUS}px;
    padding: 7px 16px;
}}
QPushButton:hover {{ background: {BORDER}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; }}

QPushButton[cssClass="accent"] {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 600;
}}
QPushButton[cssClass="accent"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[cssClass="accent"]:pressed {{ background: {ACCENT_DIM}; }}
QPushButton[cssClass="accent"]:disabled {{ background: {BORDER}; color: {TEXT_FAINT}; }}

QPushButton[cssClass="ghost"] {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
}}
QPushButton[cssClass="ghost"]:hover {{ background: {ELEVATED}; color: {TEXT}; }}
QPushButton[cssClass="ghost"]:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER_SOFT}; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_SOFT};
    border-radius: {RADIUS}px;
    padding: 6px 8px;
    selection-background-color: {ACCENT_DIM};
    selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT_DIM}; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {TEXT_FAINT}; }}

QComboBox {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_SOFT};
    border-radius: {RADIUS}px;
    padding: 5px 8px;
}}
QComboBox:disabled {{ color: {TEXT_FAINT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {ELEVATED};
    color: {TEXT};
    selection-background-color: {ACCENT_DIM};
    selection-color: #ffffff;
    border: 1px solid {BORDER};
    outline: none;
}}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background: {ELEVATED};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QCheckBox:disabled {{ color: {TEXT_FAINT}; }}

QProgressBar {{
    background: {ELEVATED};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    top: -1px;
    background: {SURFACE};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_FAINT};
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT_DIM}; }}

QTreeWidget, QTableWidget {{
    background: {ELEVATED};
    alternate-background-color: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {SURFACE};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
}}
QTreeWidget::item, QTableWidget::item {{ padding: 4px; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: {ACCENT_DIM};
    color: #ffffff;
}}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
"""


def apply_theme(app: QApplication) -> Fonts:
    fonts = Fonts()
    app.setFont(fonts.body)
    app.setStyleSheet(build_qss(fonts))
    return fonts
