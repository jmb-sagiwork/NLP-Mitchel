"""Themed modal message dialog, shared by both apps.

QMessageBox renders with the OS theme, which clashes against the AURA dark
surfaces. This gives blocking operator messages the same palette as the rest
of the app.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme as th


class MessageDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, message: str,
                 fonts: th.Fonts | None = None) -> None:
        super().__init__(parent)
        fonts = fonts or th.Fonts()
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(self)
        th.set_class(header, "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        title_label = QLabel(title, header)
        title_label.setFont(fonts.title)
        header_layout.addWidget(title_label)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(14, 14, 14, 14)

        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(message)
        text.setFont(fonts.mono)
        line_count = message.count("\n") + 1
        row_height = text.fontMetrics().lineSpacing()
        text.setFixedHeight(max(4, min(20, line_count + 1)) * row_height + 20)
        body.addWidget(text)
        layout.addLayout(body)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 0, 14, 14)
        footer.addStretch(1)
        ok_button = QPushButton("OK", self)
        th.set_class(ok_button, "accent")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        footer.addWidget(ok_button)
        layout.addLayout(footer)

        ok_button.setFocus()


def show_message(parent: QWidget | None, title: str, message: str) -> None:
    MessageDialog(parent, title, message).exec()


class ConfirmDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, message: str,
                 fonts: th.Fonts | None = None) -> None:
        super().__init__(parent)
        fonts = fonts or th.Fonts()
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(self)
        th.set_class(header, "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        title_label = QLabel(title, header)
        title_label.setFont(fonts.title)
        header_layout.addWidget(title_label)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(14, 14, 14, 14)

        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(message)
        text.setFont(fonts.mono)
        line_count = message.count("\n") + 1
        row_height = text.fontMetrics().lineSpacing()
        text.setFixedHeight(max(4, min(20, line_count + 1)) * row_height + 20)
        body.addWidget(text)
        layout.addLayout(body)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 0, 14, 14)
        footer.addStretch(1)
        decline_button = QPushButton("Decline", self)
        decline_button.clicked.connect(self.reject)
        footer.addWidget(decline_button)
        approve_button = QPushButton("Approve", self)
        th.set_class(approve_button, "accent")
        approve_button.setDefault(True)
        approve_button.clicked.connect(self.accept)
        footer.addWidget(approve_button)
        layout.addLayout(footer)

        approve_button.setFocus()


def show_confirm(parent: QWidget | None, title: str, message: str) -> bool:
    """Show a blocking Approve/Decline dialog. Returns True only if approved."""

    return ConfirmDialog(parent, title, message).exec() == QDialog.DialogCode.Accepted
