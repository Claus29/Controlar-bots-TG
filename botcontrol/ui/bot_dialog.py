"""Formulario para añadir o editar un bot."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout,
    QWidget,
)

from botcontrol import secrets
from botcontrol.launcher import LaunchError, build_launch, resolve_interpreter
from botcontrol.models import DAY_NAMES, KINDS, BotConfig
from botcontrol.telegram_api import TelegramError, get_me
from botcontrol.ui.workers import run_async

TARGET_LABELS = {
    "python": ("Script (.py)", "Scripts de Python (*.py *.pyw);;Todos los archivos (*)"),
    "node": ("Script (.js)", "Scripts de Node (*.js *.mjs *.cjs *.ts);;Todos los archivos (*)"),
    "exe": ("Ejecutable", "Programas (*.exe *.bat *.cmd);;Todos los archivos (*)"),
    "command": ("Comando", ""),
}


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("hint", True)
    label.setWordWrap(True)
    return label


def path_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    button = QPushButton("Examinar…")
    button.clicked.connect(on_browse)
    layout.addWidget(button)
    return row


def parse_env(text: str) -> dict[str, str]:
    env = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Línea {number}: falta «=» (formato CLAVE=valor)")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Línea {number}: la clave está vacía")
        env[key] = value.strip()
    return env


class BotDialog(QDialog):
    def __init__(self, parent=None, bot: BotConfig | None = None, existing_names: set[str] | None = None):
        super().__init__(parent)
        self.is_new = bot is None
        self.bot = copy.deepcopy(bot) if bot else BotConfig(name="")
        self.existing_names = {n.lower() for n in (existing_names or set())}
        self.setWindowTitle("Añadir bot" if self.is_new else f"Editar «{self.bot.name}»")
        self.setMinimumWidth(620)

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._telegram_tab(), "Telegram")
        tabs.addTab(self._start_tab(), "Inicio y reinicio")
        tabs.addTab(self._schedule_tab(), "Programación")
        tabs.addTab(self._advanced_tab(), "Avanzado")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self._kind_changed()

    # ----------------------------------------------------------------- tabs
    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.name = QLineEdit(self.bot.name)
        self.name.setPlaceholderText("Ej.: Bot de pedidos")
        self.kind = QComboBox()
        for key, label in KINDS.items():
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(list(KINDS).index(self.bot.kind))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.target = QLineEdit(self.bot.target)
        self.target.editingFinished.connect(self._target_changed)
        self.target_label = QLabel()
        self.target_row = path_row(self.target, self._browse_target)
        self.args = QLineEdit(self.bot.args)
        self.args.setPlaceholderText("Opcional, p. ej. --config config.json")
        self.workdir = QLineEdit(self.bot.workdir)
        self.workdir.setPlaceholderText("Por defecto, la carpeta del script")
        self.interpreter = QLineEdit(self.bot.interpreter)
        self.interpreter.setPlaceholderText("Autodetectar (venv del bot o Python del sistema)")
        self.interpreter.editingFinished.connect(self._update_detected)
        self.interp_row = path_row(self.interpreter, self._browse_interpreter)
        self.interp_label = QLabel("Intérprete")
        self.detected = hint("")
        self.target_hint = hint("")

        form.addRow("Nombre", self.name)
        form.addRow("Tipo", self.kind)
        form.addRow(self.target_label, self.target_row)
        form.addRow("", self.target_hint)
        form.addRow("Argumentos", self.args)
        form.addRow("Carpeta de trabajo", path_row(self.workdir, self._browse_workdir))
        form.addRow(self.interp_label, self.interp_row)
        form.addRow("", self.detected)
        return page

    def _telegram_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.token = QLineEdit(secrets.unprotect(self.bot.token_enc))
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("Opcional: 123456789:AA…")
        show = QCheckBox("Mostrar")
        show.toggled.connect(lambda on: self.token.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.token, 1)
        row_layout.addWidget(show)
        self.check_button = QPushButton("Comprobar token")
        self.check_button.clicked.connect(self._check_token)
        row_layout.addWidget(self.check_button)
        self.username = QLineEdit(self.bot.username)
        self.username.setPlaceholderText("Se rellena al comprobar el token")
        self.token_status = hint("")
        self.inject = QCheckBox("Pasar el token al bot como variable de entorno")
        self.inject.setChecked(self.bot.inject_token)
        self.token_env = QLineEdit(self.bot.token_env)
        form.addRow("Token", row)
        form.addRow("", self.token_status)
        form.addRow("Usuario del bot", self.username)
        form.addRow("", self.inject)
        form.addRow("Nombre de la variable", self.token_env)
        form.addRow("", hint(
            "El token se guarda cifrado con tu cuenta de Windows. Si tu bot lee el token de una variable "
            "de entorno (os.environ[\"BOT_TOKEN\"]), activa la casilla y escribe el nombre de la variable. "
            "Si el token ya está dentro del código del bot, basta con dejarlo aquí para comprobarlo."))
        return page

    def _start_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.autostart = QCheckBox("Abrir este bot automáticamente al iniciar BotControl / el PC")
        self.autostart.setChecked(self.bot.autostart)
        self.delay = QSpinBox()
        self.delay.setRange(0, 3600)
        self.delay.setSuffix(" s")
        self.delay.setValue(self.bot.start_delay)
        self.auto_restart = QCheckBox("Reiniciar automáticamente si se cae")
        self.auto_restart.setChecked(self.bot.auto_restart)
        self.max_restarts = QSpinBox()
        self.max_restarts.setRange(0, 100)
        self.max_restarts.setValue(self.bot.max_restarts)
        self.window = QSpinBox()
        self.window.setRange(30, 86400)
        self.window.setSuffix(" s")
        self.window.setValue(self.bot.restart_window)
        form.addRow("", self.autostart)
        form.addRow("Retraso al iniciar", self.delay)
        form.addRow("", hint("Útil para escalonar el arranque de varios bots al encender el PC."))
        form.addRow("", self.auto_restart)
        form.addRow("Máx. reinicios", self.max_restarts)
        form.addRow("…en un periodo de", self.window)
        form.addRow("", hint("Si el bot se cae más veces en ese periodo, se deja parado y se avisa "
                             "(evita reiniciarlo sin fin si tiene un error)."))
        return page

    def _schedule_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        sched = self.bot.schedule
        self.sched_enabled = QCheckBox("Usar programación horaria")
        self.sched_enabled.setChecked(sched.enabled)
        layout.addWidget(self.sched_enabled)
        days_row = QHBoxLayout()
        self.day_checks = []
        for index, name in enumerate(DAY_NAMES):
            check = QCheckBox(name)
            check.setChecked(index in sched.days)
            self.day_checks.append(check)
            days_row.addWidget(check)
        layout.addLayout(days_row)
        form = QFormLayout()
        self.sched_start = QTimeEdit(QTime.fromString(sched.start, "HH:mm"))
        self.sched_start.setDisplayFormat("HH:mm")
        self.sched_stop = QTimeEdit(QTime.fromString(sched.stop, "HH:mm"))
        self.sched_stop.setDisplayFormat("HH:mm")
        form.addRow("Iniciar a las", self.sched_start)
        form.addRow("Detener a las", self.sched_stop)
        layout.addLayout(form)
        layout.addWidget(hint(
            "El bot se inicia al empezar la franja y se detiene al terminarla. Si la hora de parada es anterior "
            "a la de inicio (p. ej. 22:00-06:00) la franja cruza la medianoche. Si ambas son iguales, el bot "
            "funciona el día completo. Puedes iniciarlo o pararlo a mano en cualquier momento."))
        layout.addStretch(1)
        return page

    def _advanced_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.env = QPlainTextEdit("\n".join(f"{k}={v}" for k, v in self.bot.env.items()))
        self.env.setPlaceholderText("CLAVE=valor\nOTRA_CLAVE=otro valor")
        self.env.setFixedHeight(120)
        self.notes = QPlainTextEdit(self.bot.notes)
        self.notes.setFixedHeight(90)
        self.preview = hint("")
        test = QPushButton("Ver comando que se ejecutará")
        test.clicked.connect(self._show_preview)
        form.addRow("Variables de entorno", self.env)
        form.addRow("Notas", self.notes)
        form.addRow("", test)
        form.addRow("", self.preview)
        return page

    # ------------------------------------------------------------- helpers
    @property
    def kind_key(self) -> str:
        return self.kind.currentData()

    def _kind_changed(self) -> None:
        label, _ = TARGET_LABELS[self.kind_key]
        self.target_label.setText(label)
        is_command = self.kind_key == "command"
        self.target_row.layout().itemAt(1).widget().setVisible(not is_command)
        self.target.setPlaceholderText("Ej.: python C:\\bots\\mibot.py" if is_command else "Ruta del archivo")
        needs_interp = self.kind_key in ("python", "node")
        self.interp_row.setVisible(needs_interp)
        self.interp_label.setVisible(needs_interp)
        self.detected.setVisible(needs_interp)
        self.target_hint.setText("Se ejecuta tal cual en la consola de Windows (cmd), sin ventana.")
        self.target_hint.setVisible(is_command)
        self._update_detected()

    def _target_changed(self) -> None:
        if not self.name.text().strip() and self.target.text().strip():
            from botcontrol.scanner import guess_name

            self.name.setText(guess_name(self.target.text().strip()))
        self._update_detected()

    def _update_detected(self) -> None:
        if self.kind_key not in ("python", "node") or self.interpreter.text().strip():
            self.detected.setText("")
            return
        probe = BotConfig(name="x", kind=self.kind_key, target=self.target.text().strip() or "x")
        try:
            self.detected.setText("Se usará: " + " ".join(resolve_interpreter(probe)))
        except LaunchError as exc:
            self.detected.setText("⚠ " + str(exc))

    def _start_dir(self) -> str:
        current = self.target.text().strip()
        return str(Path(current).parent) if current else str(Path.home())

    def _browse_target(self) -> None:
        _, filters = TARGET_LABELS[self.kind_key]
        path, _ = QFileDialog.getOpenFileName(self, "Selecciona el archivo del bot", self._start_dir(), filters)
        if path:
            self.target.setText(str(Path(path)))
            self._target_changed()

    def _browse_workdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta de trabajo", self.workdir.text() or self._start_dir())
        if path:
            self.workdir.setText(str(Path(path)))

    def _browse_interpreter(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Selecciona el intérprete", self._start_dir(),
                                              "Programas (*.exe);;Todos los archivos (*)")
        if path:
            self.interpreter.setText(str(Path(path)))
            self._update_detected()

    def _check_token(self) -> None:
        token = self.token.text().strip()
        if not token:
            self.token_status.setText("Escribe un token primero.")
            return
        self.check_button.setEnabled(False)
        self.token_status.setText("Comprobando…")

        def done(result, error):
            self.check_button.setEnabled(True)
            if error:
                message = str(error) if isinstance(error, TelegramError) else f"Error: {error}"
                self.token_status.setText("❌ " + message)
                return
            username = result.get("username", "")
            self.username.setText(username)
            self.token_status.setText(f"✅ Token válido: {result.get('first_name', '')} (@{username})")
            if not self.name.text().strip():
                self.name.setText(result.get("first_name", username))

        run_async(lambda: get_me(token), done, self)

    def _collect(self) -> BotConfig:
        bot = copy.deepcopy(self.bot)
        bot.name = self.name.text().strip()
        bot.kind = self.kind_key
        bot.target = self.target.text().strip().strip('"') if bot.kind != "command" else self.target.text().strip()
        bot.args = self.args.text().strip()
        bot.workdir = self.workdir.text().strip().strip('"')
        bot.interpreter = self.interpreter.text().strip().strip('"') if bot.kind in ("python", "node") else ""
        bot.token_enc = secrets.protect(self.token.text())
        bot.username = self.username.text().strip().lstrip("@")
        bot.inject_token = self.inject.isChecked()
        bot.token_env = self.token_env.text().strip() or "BOT_TOKEN"
        bot.autostart = self.autostart.isChecked()
        bot.start_delay = self.delay.value()
        bot.auto_restart = self.auto_restart.isChecked()
        bot.max_restarts = self.max_restarts.value()
        bot.restart_window = self.window.value()
        bot.schedule.enabled = self.sched_enabled.isChecked()
        bot.schedule.days = [i for i, c in enumerate(self.day_checks) if c.isChecked()]
        bot.schedule.start = self.sched_start.time().toString("HH:mm")
        bot.schedule.stop = self.sched_stop.time().toString("HH:mm")
        bot.env = parse_env(self.env.toPlainText())
        bot.notes = self.notes.toPlainText().strip()
        return bot

    def _show_preview(self) -> None:
        try:
            spec = build_launch(self._collect())
            self.preview.setText(f"{spec.display()}\nCarpeta: {spec.cwd}")
        except (LaunchError, ValueError) as exc:
            self.preview.setText("⚠ " + str(exc))

    def _accept(self) -> None:
        try:
            bot = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Variables de entorno", str(exc))
            return
        if not bot.name:
            QMessageBox.warning(self, "Falta el nombre", "Escribe un nombre para el bot.")
            return
        original = (self.bot.name or "").lower()
        if bot.name.lower() in self.existing_names and bot.name.lower() != original:
            QMessageBox.warning(self, "Nombre repetido", "Ya hay otro bot con ese nombre.")
            return
        if bot.schedule.enabled and not bot.schedule.days:
            QMessageBox.warning(self, "Programación", "Marca al menos un día o desactiva la programación.")
            return
        if bot.inject_token and not secrets.unprotect(bot.token_enc):
            QMessageBox.warning(self, "Token", "Has marcado pasar el token al bot pero no has escrito ninguno.")
            return
        try:
            build_launch(bot)
        except LaunchError as exc:
            answer = QMessageBox.question(
                self, "Revisa la configuración",
                f"{exc}\n\n¿Guardar de todos modos?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self.bot = bot
        self.accept()
