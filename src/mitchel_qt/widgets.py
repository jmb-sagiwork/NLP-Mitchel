"""Widgets that used to be hand-drawn on a Tk Canvas because Tk has no
rounded rectangle. Qt has one natively, so these are QLabel/QWidget with
QSS/QPainter rounded corners instead of manually drawn arcs.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from . import theme as th


class Pill(QLabel):
    """Rounded status chip."""

    def __init__(self, parent: QWidget | None = None, fonts: th.Fonts | None = None,
                 *, bg: str | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(22)
        self.setFont((fonts or th.Fonts()).tiny)
        self.set("", th.NEUTRAL)

    def set(self, text: str, color: str, *, text_color: str = "#0d0f13") -> None:
        self.setText(text)
        width = QFontMetrics(self.font()).horizontalAdvance(text) + 20
        self.setFixedWidth(max(width, 40))
        self.setStyleSheet(
            f"background-color: {color}; color: {text_color};"
            f"border-radius: {th.RADIUS_PILL}px; font-weight: 600; padding: 0 2px;"
        )


class ConfidenceMeter(QWidget):
    """Flat confidence bar with threshold ticks."""

    def __init__(self, parent: QWidget | None = None, *, width: int = 208,
                 bg: str | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(width, 8)
        self._fraction = 0.0
        self._color = th.NEUTRAL
        self._ticks: tuple[float, ...] = ()

    def set(self, fraction: float, color: str, *, ticks: tuple[float, ...] = ()) -> None:
        self._fraction = max(0.0, min(fraction, 1.0))
        self._color = color
        self._ticks = ticks
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = self.height() / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(th.BORDER))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)

        if self._fraction > 0:
            painter.setBrush(QColor(self._color))
            painter.drawRoundedRect(
                QRectF(0, 0, self._fraction * self.width(), self.height()), radius, radius
            )

        painter.setPen(QColor(th.TEXT_FAINT))
        for tick in self._ticks:
            x = tick * self.width()
            painter.drawLine(int(x), 0, int(x), self.height())
        painter.end()


class StatusDot(QWidget):
    """Small filled circle used for the pipeline run-state indicator."""

    def __init__(self, parent: QWidget | None = None, *, diameter: int = 10) -> None:
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._color = th.TEXT_FAINT

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(self.rect())
        painter.end()
