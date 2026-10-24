"""Visor del log en vivo del bot seleccionado."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")  # códigos de color de la consola
INITIAL_BYTES = 256 * 1024
MAX_LINES = 5000


class LogView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Path | None = None
        self.offset = 0

        self.title = QLabel("Selecciona un bot para ver su registro")
        self.title.setStyleSheet("font-weight: 600; color: #9fb0c2;")
        self.follow = QCheckBox("Seguir")
        self.follow.setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en el registro… (Intro)")
        self.search.setMaximumWidth(260)
        self.search.returnPressed.connect(self.find_next)
        self.open_button = QPushButton("Abrir archivo")
        self.open_button.clicked.connect(self.open_file)
        self.clear_button = QPushButton("Vaciar")
        self.clear_button.clicked.connect(self.clear_log)

        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.search)
        header.addWidget(self.follow)
        header.addWidget(self.open_button)
        header.addWidget(self.clear_button)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(MAX_LINES)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.text, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.open_button, self.clear_button, self.search):
            widget.setEnabled(enabled)

    def show_log(self, name: str | None, path: Path | None) -> None:
        if path == self.path:
            return
        self.path = path
        self.offset = 0
        self.text.clear()
        self.title.setText(f"Registro de «{name}»" if name else "Selecciona un bot para ver su registro")
        self._set_enabled(path is not None)
        if path is None:
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        self.offset = max(0, size - INITIAL_BYTES)
        self.refresh(skip_partial=self.offset > 0)

    def refresh(self, skip_partial: bool = False) -> None:
        if self.path is None:
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:  # vaciado o rotado
            self.offset = 0
            self.text.clear()
        if size == self.offset:
            return
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read(min(size - self.offset, 2 * 1024 * 1024))
        except OSError:
            return
        self.offset += len(data)
        text = ANSI.sub("", data.decode("utf-8", errors="replace")).replace("\r\n", "\n").replace("\r", "\n")
        if skip_partial and "\n" in text:
            text = text.split("\n", 1)[1]
        self._append(text)

    def _append(self, text: str) -> None:
        cursor = QTextCursor(self.text.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        if self.follow.isChecked():
            bar = self.text.verticalScrollBar()
            bar.setValue(bar.maximum())

    def find_next(self) -> None:
        term = self.search.text()
        if not term:
            return
        if not self.text.find(term):
            self.text.moveCursor(QTextCursor.Start)
            if not self.text.find(term):
                self.title.setText(f"«{term}» no aparece en el registro")
                return
        self.follow.setChecked(False)

    def open_file(self) -> None:
        if self.path and self.path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))

    def clear_log(self) -> None:
        if not self.path:
            return
        if QMessageBox.question(self, "Vaciar registro", "¿Borrar el contenido del registro de este bot?") \
                != QMessageBox.Yes:
            return
        try:
            with open(self.path, "r+b") as fh:
                fh.truncate(0)
        except OSError as exc:
            QMessageBox.warning(self, "Vaciar registro", f"No se pudo vaciar el registro: {exc}")
            return
        self.offset = 0
        self.text.clear()

