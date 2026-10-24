"""Gestor de librerías de un bot: analizar, instalar, desinstalar y entorno aislado."""

from __future__ import annotations

import os
import re
import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from botcontrol import deps
from botcontrol.launcher import LaunchError, resolve_interpreter
from botcontrol.models import BotConfig
from botcontrol.paths import data_dir
from botcontrol.proc_utils import Cancelled
from botcontrol.ui.bot_dialog import hint


class _Bridge(QObject):
    line = Signal(str)
    done = Signal(object, object)


def split_packages(text: str) -> list[str]:
    return [p for p in re.split(r"[\s,;]+", text.strip()) if p]


class DepsDialog(QDialog):
    def __init__(self, bot: BotConfig, window, parent=None):
        super().__init__(parent or window)
        self.bot = bot
        self.window = window
        self.manager = window.manager
        self.is_python = bot.kind == "python"
        self._cancel: threading.Event | None = None
        self._bridge: _Bridge | None = None
        self._busy_buttons: list[QPushButton] = []
        self.setWindowTitle(f"Librerías de «{bot.name}»")
        self.resize(920, 780)

        self.interp_label = QLabel("Comprobando el intérprete…")
        self.interp_label.setWordWrap(True)
        self.interp_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shared_label = hint("")
        self.manifest_label = hint("")

        self.btn_analyze = self._button("Analizar librerías del bot", self.analyze, accent=True)
        self.btn_requirements = self._button("Instalar requirements.txt" if self.is_python else "npm install",
                                             self.install_manifest)
        self.btn_isolate = self._button("Crear entorno aislado (recomendado)", self.create_isolated)

        top = QHBoxLayout()
        for button in (self.btn_analyze, self.btn_requirements, self.btn_isolate):
            top.addWidget(button)
        top.addStretch(1)

        # Librerías que faltan
        self.missing_box = QGroupBox("Librerías que usa el bot y faltan")
        self.missing = QTableWidget(0, 4)
        self.missing.setHorizontalHeaderLabels(["Instalar", "Import", "Paquete (editable)", "Dónde se usa"])
        self.missing.verticalHeader().setVisible(False)
        self.missing.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.missing.setSelectionMode(QAbstractItemView.NoSelection)
        self.missing.setMinimumHeight(150)
        self.missing_checks: list[QCheckBox] = []
        self.btn_install_missing = self._button("Instalar seleccionadas", self.install_missing)
        self.btn_install_missing.setEnabled(False)
        missing_layout = QVBoxLayout(self.missing_box)
        missing_layout.addWidget(self.missing)
        missing_layout.addWidget(self.btn_install_missing, 0, Qt.AlignRight)
        self.missing_box.setVisible(False)

        # Instalar a mano
        self.package_edit = QLineEdit()
        self.package_edit.setPlaceholderText("Nombre del paquete, p. ej.  matplotlib   pandas==2.2.2   requests")
        self.package_edit.returnPressed.connect(self.install_typed)
        self.btn_install = self._button("Instalar", self.install_typed, accent=True)
        manual = QHBoxLayout()
        manual.addWidget(QLabel("Añadir librería:"))
        manual.addWidget(self.package_edit, 1)
        manual.addWidget(self.btn_install)

        # Instaladas
        self.installed_box = QGroupBox("Librerías instaladas en el Python del bot")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.installed = QTableWidget(0, 2)
        self.installed.setHorizontalHeaderLabels(["Paquete", "Versión"])
        self.installed.verticalHeader().setVisible(False)
        self.installed.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.installed.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.installed.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.btn_refresh = self._button("Actualizar lista", self.refresh_installed)
        self.btn_uninstall = self._button("Desinstalar seleccionadas", self.uninstall_selected)
        installed_buttons = QHBoxLayout()
        installed_buttons.addWidget(self.filter_edit, 1)
        installed_buttons.addWidget(self.btn_refresh)
        installed_buttons.addWidget(self.btn_uninstall)
        installed_layout = QVBoxLayout(self.installed_box)
        installed_layout.addLayout(installed_buttons)
        installed_layout.addWidget(self.installed)
        self.installed_box.setVisible(self.is_python)

        # Salida
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(4000)
        self.output.setPlaceholderText("Aquí verás lo que va haciendo pip / npm.")
        self.output.setMinimumHeight(110)
        self.status = QLabel("")
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setEnabled(False)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.interp_label)
        layout.addWidget(self.shared_label)
        layout.addWidget(self.manifest_label)
        layout.addLayout(top)
        layout.addWidget(self.missing_box, 2)
        layout.addLayout(manual)
        layout.addWidget(self.installed_box, 3)
        layout.addWidget(self.output, 1)
        layout.addLayout(bottom)

        if not self.is_python:
            self.btn_analyze.setVisible(False)
            self.btn_isolate.setVisible(False)
        self.refresh_info()  # después carga la lista de instaladas

    # ---------------------------------------------------------- utilidades
    def _button(self, text: str, slot, accent: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        if accent:
            button.setProperty("accent", True)
        self._busy_buttons.append(button)
        return button

    def _log(self, line: str) -> None:
        self.output.appendPlainText(line)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        for button in self._busy_buttons:
            button.setEnabled(not busy)
        if not busy:
            self.btn_requirements.setEnabled(deps.manifest_file(self.bot) is not None)
            self.btn_install_missing.setEnabled(bool(self.missing_checks))
        self.package_edit.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.status.setText(text)

    def _run(self, title: str, func: Callable, on_success: Callable | None = None, quiet: bool = False) -> None:
        """Ejecuta ``func(on_line, cancel)`` en un hilo mostrando su salida."""
        if self._cancel is not None:
            return
        self._cancel = threading.Event()
        bridge = _Bridge(self)
        self._bridge = bridge
        bridge.line.connect(self._log)
        if not quiet:
            self._log(f"\n▶ {title}")
        self._set_busy(True, title + "…")
        cancel = self._cancel

        def finished(result, error):
            self._cancel = None
            self._set_busy(False)
            if isinstance(error, Cancelled):
                self._log("✖ Cancelado")
                return
            if error is not None:
                self._log(f"✖ {error}")
                if not quiet:
                    QMessageBox.warning(self, title, str(error))
                return
            if on_success:
                on_success(result)

        bridge.done.connect(finished)

        def worker():
            try:
                result, error = func(bridge.line.emit, cancel), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            try:
                bridge.done.emit(result, error)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._cancel is not None:
            if QMessageBox.question(self, "Librerías", "Hay una instalación en curso. ¿Cancelarla y cerrar?") \
                    != QMessageBox.Yes:
                event.ignore()
                return
            self._cancel.set()
        super().closeEvent(event)

    def _interp(self) -> list[str]:
        return resolve_interpreter(self.bot)

    def _env(self) -> dict[str, str]:
        return deps.pip_env(self.bot)

    # ----------------------------------------------------------- información
    def refresh_info(self) -> None:
        manifest = deps.manifest_file(self.bot)
        name = "requirements.txt" if self.is_python else "package.json"
        self.manifest_label.setText(f"{name}: {manifest}" if manifest else f"No hay {name} en la carpeta del bot.")
        self.btn_requirements.setEnabled(manifest is not None)
        if not self.is_python:
            self.interp_label.setText("Bot de Node.js: las librerías se instalan en su carpeta (node_modules), "
                                      "así que no afectan a otros bots.")
            return
        others = [b for b in self.window.config.bots if b.id != self.bot.id and b.kind == "python"]

        def work(_on_line, _cancel):
            interp = self._interp()
            info = deps.interpreter_info(interp, self._env())
            mine = os.path.normcase(os.path.realpath(info["executable"]))
            shared = []
            for other in others:
                try:
                    other_info = deps.interpreter_info(resolve_interpreter(other))
                except (LaunchError, deps.DepsError):
                    continue
                if os.path.normcase(os.path.realpath(other_info["executable"])) == mine:
                    shared.append(other.name)
            return interp, info, shared

        def show(result):
            interp, info, shared = result
            kind = "entorno aislado ✔" if info["is_venv"] else "Python del sistema (compartido)"
            self.interp_label.setText(f"<b>Python {info['version']}</b> — {kind}<br>{' '.join(interp)}")
            if shared:
                self.shared_label.setText(
                    "⚠ Este Python también lo usan: " + ", ".join(shared) + ". Instalar o cambiar versiones aquí "
                    "les afecta. Para evitar conflictos, pulsa «Crear entorno aislado».")
            elif not info["is_venv"]:
                self.shared_label.setText("Consejo: crea un entorno aislado para que las librerías de este bot "
                                          "no se mezclen con las de otros programas.")
            else:
                self.shared_label.setText("Las librerías de este bot están aisladas: no afectan a otros bots.")
            self.btn_isolate.setText("Reparar entorno aislado" if info["is_venv"] else
                                     "Crear entorno aislado (recomendado)")
            self.refresh_installed()

        try:
            self._interp()
        except LaunchError as exc:
            self.interp_label.setText(f"⚠ {exc}")
            return
        self._run("Comprobando el intérprete", work, show, quiet=True)

    def refresh_installed(self) -> None:
        if not self.is_python:
            return
        if self._cancel is not None:
            return

        def work(_on_line, _cancel):
            return deps.pip_list(self._interp(), self._env())

        def show(packages):
            self.installed.setRowCount(len(packages))
            for row, (name, version) in enumerate(packages):
                self.installed.setItem(row, 0, QTableWidgetItem(name))
                self.installed.setItem(row, 1, QTableWidgetItem(version))
            self.installed_box.setTitle(f"Librerías instaladas en el Python del bot ({len(packages)})")
            self._apply_filter()

        self._run("Leyendo librerías instaladas", work, show, quiet=True)

    def _apply_filter(self) -> None:
        term = self.filter_edit.text().strip().lower()
        for row in range(self.installed.rowCount()):
            item = self.installed.item(row, 0)
            self.installed.setRowHidden(row, bool(term) and term not in item.text().lower())

    # -------------------------------------------------------------- acciones
    def _after_change(self, message: str) -> None:
        """Tras instalar: refresca y ofrece reiniciar/iniciar el bot."""
        self._log(f"✔ {message}")
        self.bot.deps_hash = ""  # se volverá a comprobar al iniciar
        self.window.save()
        if self._cancel is None:
            self.refresh_installed()
        rt = self.manager.runtime(self.bot.id)
        if rt.is_active:
            if QMessageBox.question(self, "Librerías", f"{message}.\n\n¿Reiniciar «{self.bot.name}» ahora para "
                                    "que use los cambios?") == QMessageBox.Yes:
                self.window.restart_bot(self.bot)
        elif rt.state.value in ("failed", "crashed"):
            if QMessageBox.question(self, "Librerías", f"{message}.\n\n¿Iniciar «{self.bot.name}» ahora?") \
                    == QMessageBox.Yes:
                self.window.start_bot(self.bot)

    def analyze(self) -> None:
        def work(_on_line, _cancel):
            return deps.analyze(self.bot)

        def show(items):
            self.missing_checks = []
            self.missing.setRowCount(len(items))
            for row, item in enumerate(items):
                check = QCheckBox()
                check.setChecked(not item.optional)
                self.missing_checks.append(check)
                self.missing.setCellWidget(row, 0, check)
                module = QTableWidgetItem(item.module + ("  (opcional)" if item.optional else ""))
                module.setFlags(module.flags() & ~Qt.ItemIsEditable)
                self.missing.setItem(row, 1, module)
                self.missing.setItem(row, 2, QTableWidgetItem(item.package))
                files = QTableWidgetItem(", ".join(item.files[:5]) + (" …" if len(item.files) > 5 else ""))
                files.setFlags(files.flags() & ~Qt.ItemIsEditable)
                self.missing.setItem(row, 3, files)
            self.missing.resizeColumnsToContents()
            self.missing.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.missing_box.setVisible(True)
            self.btn_install_missing.setEnabled(bool(items))
            if items:
                self._log(f"Faltan {len(items)} librería(s): " + ", ".join(i.package for i in items))
                self.missing_box.setTitle(f"Librerías que usa el bot y faltan ({len(items)})")
            else:
                self._log("✔ Están instaladas todas las librerías que usa el código del bot.")
                self.missing_box.setTitle("No falta ninguna librería ✔")

        self._run("Analizando las librerías que usa el bot", work, show)

    def install_missing(self) -> None:
        packages = [self.missing.item(row, 2).text().strip() for row, check in enumerate(self.missing_checks)
                    if check.isChecked() and self.missing.item(row, 2).text().strip()]
        if packages:
            self._install(packages, remember=False)

    def install_typed(self) -> None:
        packages = split_packages(self.package_edit.text())
        if not packages:
            self.package_edit.setFocus()
            return
        remember = QMessageBox.question(
            self, "Añadir librería",
            f"¿Guardar {', '.join(packages)} como librería(s) del bot?\n\n"
            "Si respondes Sí, BotControl comprobará que estén instaladas cada vez que inicie el bot "
            "(y las instalará en el entorno aislado si lo creas).") == QMessageBox.Yes
        self._install(packages, remember)

    def _install(self, packages: list[str], remember: bool) -> None:
        if remember:
            for package in packages:
                if package not in self.bot.extra_packages:
                    self.bot.extra_packages.append(package)
            self.window.save()

        if self.is_python:
            def work(on_line, cancel):
                deps.pip_install(self._interp(), self._env(), packages, on_line=on_line, cancel=cancel)
        else:
            def work(on_line, cancel):
                deps.npm_install(deps.bot_folder(self.bot), self._env(), packages, on_line=on_line, cancel=cancel)

        def done(_):
            self.package_edit.clear()
            self.missing_box.setVisible(False)
            self.missing_checks = []
            self._after_change("Instalado: " + ", ".join(packages))

        self._run("Instalando " + ", ".join(packages), work, done)

    def install_manifest(self) -> None:
        def work(on_line, cancel):
            snapshot = BotConfig.from_dict({**self.bot.to_dict(), "extra_packages": []})
            return deps.sync(snapshot, on_line, cancel)

        name = "requirements.txt" if self.is_python else "package.json"
        self._run(f"Instalando {name}", work, lambda _: self._after_change(f"Instalado {name}"))

    def uninstall_selected(self) -> None:
        rows = sorted({i.row() for i in self.installed.selectionModel().selectedRows()})
        packages = [self.installed.item(r, 0).text() for r in rows]
        if not packages:
            QMessageBox.information(self, "Desinstalar", "Selecciona en la lista las librerías a desinstalar.")
            return
        protected = {"pip", "setuptools", "wheel"} & {p.lower() for p in packages}
        if protected:
            QMessageBox.warning(self, "Desinstalar", f"No se recomienda desinstalar {', '.join(protected)}.")
            return
        if QMessageBox.question(self, "Desinstalar", f"¿Desinstalar {', '.join(packages)}?") != QMessageBox.Yes:
            return
        self.bot.extra_packages = [p for p in self.bot.extra_packages
                                   if re.split(r"[<>=!~\[ ]", p, maxsplit=1)[0].lower() not in
                                   {x.lower() for x in packages}]

        def work(on_line, cancel):
            deps.pip_uninstall(self._interp(), self._env(), packages, on_line, cancel)

        self._run("Desinstalando " + ", ".join(packages), work,
                  lambda _: self._after_change("Desinstalado: " + ", ".join(packages)))

    def create_isolated(self) -> None:
        target = deps.isolated_env_path(self.bot, data_dir())
        if QMessageBox.question(
                self, "Entorno aislado",
                f"Se creará un entorno de Python sólo para «{self.bot.name}» en:\n{target}\n\n"
                "Se instalarán ahí su requirements.txt, sus librerías adicionales y las que use su código. "
                "Así sus librerías no interfieren con otros bots.\n\n¿Continuar?") != QMessageBox.Yes:
            return
        snapshot = BotConfig.from_dict(self.bot.to_dict())

        def work(on_line, cancel):
            return deps.create_isolated_env(snapshot, data_dir(), on_line=on_line, cancel=cancel)

        def done(python):
            self.bot.interpreter = str(python)
            self.window.save()
            self._after_change(f"Entorno aislado listo ({python})")
            self.refresh_info()

        self._run("Creando el entorno aislado", work, done)
