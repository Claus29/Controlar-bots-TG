"""Diálogo para elegir bots detectados (en ejecución o en una carpeta)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from botcontrol.models import KINDS
from botcontrol.scanner import Candidate, norm
from botcontrol.ui.bot_dialog import hint


class CandidatesDialog(QDialog):
    def __init__(self, title: str, intro: str, candidates: list[Candidate], known: dict[str, str],
                 running: bool, parent=None):
        """``known`` asocia la ruta normalizada del script con el nombre del bot ya configurado."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 460)
        self.candidates = candidates
        self.running = running

        self.table = QTableWidget(len(candidates), 5 if running else 4)
        headers = ["Añadir", "Nombre", "Tipo", "Script"] + (["PID"] if running else [])
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.checks: list[QCheckBox] = []

        for row, cand in enumerate(candidates):
            check = QCheckBox()
            existing = known.get(norm(cand.script))
            check.setChecked(cand.likely_entry and not existing)
            self.checks.append(check)
            self.table.setCellWidget(row, 0, check)
            name = QTableWidgetItem(cand.name)
            name.setFlags(name.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 1, name)
            self._static(row, 2, KINDS.get(cand.kind, cand.kind))
            label = cand.script + (f"   (ya configurado como «{existing}»)" if existing else "")
            if not cand.likely_entry:
                label += "   (posible módulo auxiliar)"
            item = self._static(row, 3, label)
            item.setToolTip(cand.cmdline or cand.script)
            if running:
                self._static(row, 4, str(cand.pid))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(intro))
        if candidates:
            layout.addWidget(self.table, 1)
            layout.addWidget(hint("Puedes cambiar el nombre haciendo doble clic. Después podrás editar cada bot "
                                  "para ajustar el token, el inicio automático o la programación."))
        else:
            layout.addWidget(hint("No se ha encontrado ningún bot de Telegram."), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Añadir seleccionados" + (" y tomar control" if running else ""))
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(candidates))
        buttons.button(QDialogButtonBox.Cancel).setText("Cerrar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _static(self, row: int, col: int, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, col, item)
        return item

    def selected(self) -> list[Candidate]:
        chosen = []
        for row, check in enumerate(self.checks):
            if check.isChecked():
                cand = self.candidates[row]
                cand.name = (self.table.item(row, 1).text() or cand.name).strip()
                chosen.append(cand)
        return chosen
