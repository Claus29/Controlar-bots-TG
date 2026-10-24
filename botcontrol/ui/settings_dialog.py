"""Ajustes generales de la aplicación."""

from __future__ import annotations

import copy

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout,
)

from botcontrol import startup
from botcontrol.models import EXIT_ASK, EXIT_LEAVE, EXIT_STOP, AppSettings
from botcontrol.paths import data_dir
from botcontrol.ui.bot_dialog import hint


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes")
        self.setMinimumWidth(520)
        self.settings = copy.deepcopy(settings)

        boot = QGroupBox("Inicio")
        boot_form = QFormLayout(boot)
        self.run_at_login = QCheckBox("Iniciar BotControl al encender el PC (iniciar sesión en Windows)")
        self.run_at_login.setChecked(startup.is_enabled())
        self.run_at_login.setEnabled(startup.supported())
        self.start_minimized = QCheckBox("Arrancar minimizado en la bandeja del sistema")
        self.start_minimized.setChecked(settings.start_minimized_on_boot)
        self.wait_net = QCheckBox("Esperar a tener Internet antes de abrir los bots automáticos")
        self.wait_net.setChecked(settings.wait_for_internet)
        self.net_timeout = QSpinBox()
        self.net_timeout.setRange(5, 600)
        self.net_timeout.setSuffix(" s como máximo")
        self.net_timeout.setValue(settings.internet_timeout)
        boot_form.addRow(self.run_at_login)
        boot_form.addRow(self.start_minimized)
        boot_form.addRow(self.wait_net)
        boot_form.addRow("", self.net_timeout)
        boot_form.addRow(hint("Los bots que se abren al iniciar se eligen con la columna «Inicio auto» "
                              "de la lista principal."))

        window = QGroupBox("Ventana y avisos")
        window_form = QFormLayout(window)
        self.to_tray = QCheckBox("Al cerrar la ventana, seguir funcionando en la bandeja")
        self.to_tray.setChecked(settings.minimize_to_tray)
        self.notify = QCheckBox("Avisarme cuando un bot se caiga")
        self.notify.setChecked(settings.notify_crash)
        self.exit_action = QComboBox()
        self.exit_action.addItem("Preguntar", EXIT_ASK)
        self.exit_action.addItem("Detener todos los bots", EXIT_STOP)
        self.exit_action.addItem("Dejar los bots funcionando", EXIT_LEAVE)
        self.exit_action.setCurrentIndex(self.exit_action.findData(settings.exit_action))
        self.log_size = QSpinBox()
        self.log_size.setRange(1, 500)
        self.log_size.setSuffix(" MB por bot")
        self.log_size.setValue(settings.max_log_mb)
        window_form.addRow(self.to_tray)
        window_form.addRow(self.notify)
        window_form.addRow("Al salir de BotControl", self.exit_action)
        window_form.addRow("Tamaño máx. del registro", self.log_size)

        open_data = QPushButton("Abrir carpeta de datos")
        open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(boot)
        layout.addWidget(window)
        layout.addWidget(open_data)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if startup.supported() and self.run_at_login.isChecked() != startup.is_enabled():
            try:
                startup.set_enabled(self.run_at_login.isChecked())
            except OSError as exc:
                QMessageBox.warning(self, "Inicio con Windows", f"No se pudo cambiar: {exc}")
        s = self.settings
        s.start_minimized_on_boot = self.start_minimized.isChecked()
        s.wait_for_internet = self.wait_net.isChecked()
        s.internet_timeout = self.net_timeout.value()
        s.minimize_to_tray = self.to_tray.isChecked()
        s.notify_crash = self.notify.isChecked()
        s.exit_action = self.exit_action.currentData()
        s.max_log_mb = self.log_size.value()
        self.accept()
