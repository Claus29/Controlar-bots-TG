"""Ventana principal de BotControl."""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QByteArray, QModelIndex, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMenu, QMessageBox, QProgressDialog, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QStyle, QSystemTrayIcon,
    QTableView, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from botcontrol import APP_NAME, __version__, scanner, startup
from botcontrol.launcher import LaunchError
from botcontrol.models import EXIT_ASK, EXIT_LEAVE, EXIT_STOP, KINDS, AppConfig, BotConfig, new_id
from botcontrol.paths import config_file, data_dir
from botcontrol.process_manager import STATE_LABELS, AlreadyRunning, BotManager, State
from botcontrol.scheduler import ScheduleTracker
from botcontrol.storage import export_config, import_bots, save_config
from botcontrol.telegram_api import wait_for_internet
from botcontrol.ui.bot_dialog import BotDialog
from botcontrol.ui.detect_dialog import CandidatesDialog
from botcontrol.ui.log_view import LogView
from botcontrol.ui.settings_dialog import SettingsDialog
from botcontrol.ui.theme import STATE_COLORS, app_icon, dot_icon, tray_icon
from botcontrol.ui.workers import run_async

log = logging.getLogger(__name__)

COLUMNS = ["Estado", "Nombre", "Telegram", "Inicio auto", "Programación", "PID", "Activo", "CPU", "RAM",
           "Reinicios"]
COL_STATE, COL_NAME, COL_TG, COL_AUTO, COL_SCHED, COL_PID, COL_UP, COL_CPU, COL_RAM, COL_RESTARTS = range(10)
ALERT_EVENTS = {"crashed", "gave_up", "error", "missing_module", "deps_failed"}
INFO_EVENTS = {"deps", "deps_installed"}


def fmt_uptime(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def fmt_bytes(value: int) -> str:
    if value <= 0:
        return "—"
    mb = value / (1024 * 1024)
    return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB"


class BotTableModel(QAbstractTableModel):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window

    @property
    def bots(self) -> list[BotConfig]:
        return self.window.config.bots

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.bots)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_AUTO:
            base |= Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.bots):
            return None
        bot = self.bots[index.row()]
        rt = self.window.manager.runtime(bot.id)
        col = index.column()
        if role == Qt.DisplayRole:
            if col == COL_STATE:
                label = STATE_LABELS[rt.state]
                if rt.state == State.RUNNING and rt.external:
                    label += " (externo)"
                return label
            if col == COL_NAME:
                return bot.name
            if col == COL_TG:
                return f"@{bot.username}" if bot.username else "—"
            if col == COL_SCHED:
                return bot.schedule.describe()
            if col == COL_PID:
                return str(rt.pid) if rt.is_active and rt.pid else "—"
            if col == COL_UP:
                return fmt_uptime(rt.uptime())
            if col == COL_CPU:
                return f"{rt.cpu:.1f} %" if rt.is_active else "—"
            if col == COL_RAM:
                return fmt_bytes(rt.memory) if rt.is_active else "—"
            if col == COL_RESTARTS:
                return str(rt.restarts) if rt.restarts else "—"
        if role == Qt.DecorationRole and col == COL_STATE:
            return dot_icon(STATE_COLORS[rt.state])
        if role == Qt.CheckStateRole and col == COL_AUTO:
            return Qt.Checked if bot.autostart else Qt.Unchecked
        if role == Qt.ToolTipRole:
            if col == COL_STATE:
                return rt.message or STATE_LABELS[rt.state]
            if col == COL_NAME:
                return f"{KINDS[bot.kind]}: {bot.target}" + (f"\n{bot.notes}" if bot.notes else "")
            if col == COL_AUTO:
                return "Abrir este bot al iniciar BotControl (y con él, el PC)"
        if role == Qt.TextAlignmentRole and col in (COL_PID, COL_UP, COL_CPU, COL_RAM, COL_RESTARTS):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.EditRole):  # noqa: N802
        if role == Qt.CheckStateRole and index.column() == COL_AUTO:
            bot = self.bots[index.row()]
            bot.autostart = Qt.CheckState(value) == Qt.Checked
            self.window.save()
            self.dataChanged.emit(index, index)
            if bot.autostart and startup.supported() and not startup.is_enabled():
                self.window.offer_run_at_login()
            return True
        return False

    def refresh(self) -> None:
        if self.bots:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.bots) - 1, len(COLUMNS) - 1))

    def reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, manager: BotManager, launched_at_boot: bool = False):
        super().__init__()
        self.config = config
        self.manager = manager
        self.manager.on_event = self.on_bot_event
        self.tracker = ScheduleTracker()
        self.launched_at_boot = launched_at_boot
        self._quitting = False
        self._lib_prompts: set[str] = set()

        self.setWindowTitle(f"{APP_NAME} — Control de bots de Telegram")
        self.setWindowIcon(app_icon())
        self.resize(1180, 720)

        self.model = BotTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header.setHighlightSections(False)
        self.table.selectionModel().selectionChanged.connect(self.update_actions)

        self.log_view = LogView()
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.log_view)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page())
        self.stack.addWidget(splitter)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.addWidget(self.stack)
        self.setCentralWidget(container)

        self._build_actions()
        self._build_toolbar()
        self._build_tray()
        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)

        if config.settings.window_geometry:
            self.restoreGeometry(QByteArray.fromHex(config.settings.window_geometry.encode()))

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.tick)
        self.poll_timer.start(1000)
        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self.check_schedules)
        self.schedule_timer.start(15000)

        QApplication.instance().aboutToQuit.connect(self._persist)
        self.update_empty_state()
        self.update_actions()
        self.tick()

    # ------------------------------------------------------------ montaje
    def _icon(self, name: str):
        return self.style().standardIcon(getattr(QStyle.StandardPixmap, name))

    def _action(self, text: str, icon: str | None, slot, shortcut=None, tip: str = "", short: str = "") -> QAction:
        action = QAction(self._icon(icon), text, self) if icon else QAction(text, self)
        if short:
            action.setIconText(short)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self.act_add = self._action("Añadir bot", "SP_FileDialogNewFolder", self.add_bot, "Ctrl+N",
                                    "Añadir un bot manualmente", short="Añadir")
        self.act_detect = self._action("Detectar bots abiertos", "SP_BrowserReload", self.detect_running, "F5",
                                       "Buscar bots de Telegram que ya se están ejecutando en este PC",
                                       short="Detectar")
        self.act_scan = self._action("Buscar en carpeta", "SP_DirOpenIcon", self.scan_folder, None,
                                     "Buscar scripts de bots en una carpeta", short="Carpeta")
        self.act_start = self._action("Iniciar", "SP_MediaPlay", self.start_selected, "Ctrl+R")
        self.act_stop = self._action("Detener", "SP_MediaStop", self.stop_selected, "Ctrl+T")
        self.act_restart = self._action("Reiniciar", "SP_BrowserReload", self.restart_selected, "Ctrl+Shift+R")
        self.act_edit = self._action("Editar", "SP_FileDialogDetailedView", self.edit_selected, "Ctrl+E")
        self.act_duplicate = self._action("Duplicar", None, self.duplicate_selected)
        self.act_delete = self._action("Eliminar", "SP_TrashIcon", self.delete_selected, "Del")
        self.act_folder = self._action("Abrir carpeta del bot", "SP_DirIcon", self.open_bot_folder)
        self.act_libs = self._action("Librerías…", "SP_DriveHDIcon", self.open_libraries, "Ctrl+L",
                                     "Ver, analizar e instalar las librerías del bot, o crearle un entorno aislado",
                                     short="Librerías")
        self.act_telegram = self._action("Abrir en Telegram", None, self.open_in_telegram)
        self.act_start_all = self._action("Iniciar todos", "SP_MediaSeekForward", self.start_all)
        self.act_stop_all = self._action("Detener todos", "SP_MediaPause", self.stop_all)
        self.act_settings = self._action("Ajustes", "SP_FileDialogContentsView", self.open_settings, "Ctrl+,")
        self.act_import = self._action("Importar bots…", None, self.import_config)
        self.act_export = self._action("Exportar bots…", None, self.export_config)
        self.act_data = self._action("Abrir carpeta de datos", None,
                                     lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        self.act_about = self._action("Acerca de", None, self.about)
        self.act_quit = self._action("Salir", "SP_DialogCloseButton", self.request_quit, "Ctrl+Q")

    def _build_toolbar(self) -> None:
        bar = QToolBar("Principal")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        bar.setIconSize(QSize(22, 22))
        for action in (self.act_add, self.act_detect, self.act_scan):
            bar.addAction(action)
        bar.addSeparator()
        for action in (self.act_start, self.act_stop, self.act_restart, self.act_edit, self.act_libs,
                       self.act_delete):
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self.act_start_all)
        bar.addAction(self.act_stop_all)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(self.act_settings)
        more = QToolButton()
        more.setText("Más")
        more.setIcon(self._icon("SP_FileDialogListView"))
        more.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        for action in (self.act_import, self.act_export, self.act_data, None, self.act_about, None, self.act_quit):
            menu.addSeparator() if action is None else menu.addAction(action)
        more.setMenu(menu)
        bar.addWidget(more)
        self.addToolBar(bar)

    def _empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        title = QLabel("Todavía no tienes bots")
        title.setStyleSheet("font-size: 18pt; font-weight: 600; color: #e6edf3;")
        title.setAlignment(Qt.AlignCenter)
        text = QLabel("Empieza detectando los bots de Telegram que ya tienes abiertos, buscándolos en una "
                      "carpeta o añadiéndolos a mano.")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        text.setStyleSheet("color: #9fb0c2;")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for label, slot, accent in (("Detectar bots abiertos", self.detect_running, True),
                                    ("Buscar en carpeta", self.scan_folder, False),
                                    ("Añadir manualmente", self.add_bot, False)):
            button = QPushButton(label)
            button.setProperty("accent", accent)
            button.setMinimumHeight(38)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addSpacing(16)
        layout.addLayout(buttons)
        layout.addStretch(2)
        return page

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(tray_icon(0), self)
        menu = QMenu()
        show = QAction("Mostrar BotControl", self)
        show.triggered.connect(self.show_window)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(self.act_start_all)
        menu.addAction(self.act_stop_all)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.show()
        self._tray_active = -1

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    # ------------------------------------------------------------- estado
    def save(self) -> None:
        try:
            save_config(self.config, config_file())
        except OSError as exc:
            log.exception("No se pudo guardar la configuración")
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuración: {exc}")

    def _persist(self) -> None:
        self.config.settings.window_geometry = bytes(self.saveGeometry().toHex()).decode()
        try:
            save_config(self.config, config_file())
        except OSError:
            log.exception("No se pudo guardar la configuración al salir")
        self.manager.save_runtime()

    def tick(self) -> None:
        self.manager.poll()
        self.model.refresh()
        self.update_actions()
        active = self.manager.active_count()
        total = len(self.config.bots)
        self.status_label.setText(f"{active} de {total} bots en ejecución  ")
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME}: {active}/{total} bots en ejecución")
            if (active > 0) != (self._tray_active > 0):
                self.tray.setIcon(tray_icon(active))
            self._tray_active = active

    def update_empty_state(self) -> None:
        self.stack.setCurrentIndex(1 if self.config.bots else 0)

    def selected_bots(self) -> list[BotConfig]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.config.bots[r] for r in rows if r < len(self.config.bots)]

    def update_actions(self, *_) -> None:
        selected = self.selected_bots()
        runtimes = [self.manager.runtime(b.id) for b in selected]
        any_active = any(rt.is_active for rt in runtimes)
        any_startable = any(not rt.is_active and rt.state != State.WAITING for rt in runtimes)
        any_stoppable = any(rt.is_active or rt.state in (State.WAITING, State.CRASHED, State.FAILED)
                            or rt.pending_start_at for rt in runtimes)
        self.act_start.setEnabled(any_startable)
        self.act_stop.setEnabled(any_stoppable)
        self.act_restart.setEnabled(any_active)
        single = len(selected) == 1
        self.act_edit.setEnabled(single)
        self.act_duplicate.setEnabled(single)
        self.act_folder.setEnabled(single)
        self.act_libs.setEnabled(single and selected[0].kind in ("python", "node"))
        self.act_telegram.setEnabled(single and bool(selected[0].username))
        self.act_delete.setEnabled(bool(selected))
        self.act_start_all.setEnabled(bool(self.config.bots))
        self.act_stop_all.setEnabled(self.manager.active_count() > 0)
        current = selected[0] if single else None
        self.log_view.show_log(current.name if current else None,
                               self.manager.log_path(current.id) if current else None)

    # ------------------------------------------------------------ eventos
    def on_bot_event(self, bot_id: str, kind: str, message: str) -> None:
        bot = self.config.get(bot_id)
        name = bot.name if bot else bot_id
        self.statusBar().showMessage(f"{name}: {message}", 8000)
        if kind == "config_changed":
            self.save()
            return
        if kind in ALERT_EVENTS and self.config.settings.notify_crash and self.tray:
            self.tray.showMessage(f"{name}", message, QSystemTrayIcon.Warning, 8000)
        elif kind in INFO_EVENTS and self.tray and not self.isVisible():
            self.tray.showMessage(f"{name}", message, QSystemTrayIcon.Information, 5000)
        if kind == "missing_module" and bot and self.isVisible():
            # Diferido: no abrir diálogos modales dentro del sondeo de procesos.
            QTimer.singleShot(0, lambda: self._offer_libraries(bot_id, message))

    def _offer_libraries(self, bot_id: str, message: str) -> None:
        bot = self.config.get(bot_id)
        if bot is None or bot_id in self._lib_prompts:
            return
        self._lib_prompts.add(bot_id)
        try:
            answer = QMessageBox.question(
                self, f"Librerías de «{bot.name}»",
                f"{message}\n\n¿Abrir el gestor de librerías del bot para solucionarlo?")
        finally:
            self._lib_prompts.discard(bot_id)
        if answer == QMessageBox.Yes:
            self.open_libraries(bot)

    def check_schedules(self) -> None:
        for bot_id, action in self.tracker.evaluate(self.config.bots, datetime.now()):
            rt = self.manager.runtime(bot_id)
            if action == "start" and not rt.is_active:
                self.manager.schedule_start(bot_id, 0, "programación")
            elif action == "stop" and (rt.is_active or rt.pending_start_at):
                self.manager.stop(bot_id)

    def run_autostart(self) -> None:
        bots = [b for b in self.config.bots if b.autostart and not self.manager.runtime(b.id).is_active]
        if not bots:
            return
        for bot in bots:
            rt = self.manager.runtime(bot.id)
            rt.state = State.WAITING
            rt.message = "Esperando conexión a Internet…"

        def launch(*_):
            for bot in bots:
                rt = self.manager.runtime(bot.id)
                if rt.state == State.WAITING and rt.pending_start_at is None:
                    self.manager.schedule_start(bot.id, bot.start_delay, "inicio automático")

        if self.config.settings.wait_for_internet:
            timeout = self.config.settings.internet_timeout
            run_async(lambda: wait_for_internet(timeout), launch, self)
        else:
            launch()

    # ------------------------------------------------------------ acciones
    def _start(self, bot: BotConfig) -> None:
        try:
            self.manager.start(bot.id)
        except AlreadyRunning as exc:
            answer = QMessageBox.question(
                self, "El bot ya está abierto",
                f"«{bot.name}» ya se está ejecutando fuera de BotControl (PID {exc.pid}).\n\n"
                "¿Quieres que BotControl tome el control de ese proceso?\n"
                "(Si lo inicias otra vez, Telegram daría error por tener el bot duplicado).")
            if answer == QMessageBox.Yes:
                self.manager.adopt(bot.id, exc.pid)
        except LaunchError as exc:
            QMessageBox.warning(self, f"No se pudo iniciar «{bot.name}»", str(exc))

    def start_bot(self, bot: BotConfig) -> None:
        self.manager.runtime(bot.id).restart_times.clear()
        self._start(bot)
        self.tick()

    def restart_bot(self, bot: BotConfig) -> None:
        try:
            self.manager.restart(bot.id)
        except (LaunchError, AlreadyRunning) as exc:
            QMessageBox.warning(self, f"No se pudo reiniciar «{bot.name}»", str(exc))
        self.tick()

    def open_libraries(self, bot: BotConfig | None = None) -> None:
        if not isinstance(bot, BotConfig):
            selected = self.selected_bots()
            if len(selected) != 1:
                return
            bot = selected[0]
        if bot.kind not in ("python", "node"):
            QMessageBox.information(self, "Librerías", "La gestión de librerías es para bots de Python o Node.js.")
            return
        from botcontrol.ui.deps_dialog import DepsDialog

        DepsDialog(bot, self).exec()
        self.model.refresh()

    def start_selected(self) -> None:
        for bot in self.selected_bots():
            rt = self.manager.runtime(bot.id)
            if not rt.is_active:
                rt.restart_times.clear()
                self._start(bot)
        self.tick()

    def stop_selected(self) -> None:
        for bot in self.selected_bots():
            self.manager.stop(bot.id)
        self.tick()

    def restart_selected(self) -> None:
        for bot in self.selected_bots():
            try:
                self.manager.restart(bot.id)
            except (LaunchError, AlreadyRunning) as exc:
                QMessageBox.warning(self, f"No se pudo reiniciar «{bot.name}»", str(exc))
        self.tick()

    def start_all(self) -> None:
        errors = []
        for bot in self.config.bots:
            rt = self.manager.runtime(bot.id)
            if rt.is_active:
                continue
            rt.restart_times.clear()
            try:
                self.manager.start(bot.id)
            except AlreadyRunning as exc:
                self.manager.adopt(bot.id, exc.pid)
            except LaunchError as exc:
                errors.append(f"• {bot.name}: {exc}")
        if errors:
            QMessageBox.warning(self, "Algunos bots no se iniciaron", "\n".join(errors))
        self.tick()

    def stop_all(self) -> None:
        self.manager.stop_all()
        self.tick()

    def _names(self, exclude: BotConfig | None = None) -> set[str]:
        return {b.name for b in self.config.bots if b is not exclude}

    def add_bot(self) -> None:
        dialog = BotDialog(self, existing_names=self._names())
        if dialog.exec():
            self.config.bots.append(dialog.bot)
            self._after_bots_changed(select=dialog.bot)
            if dialog.bot.autostart and startup.supported() and not startup.is_enabled():
                self.offer_run_at_login()

    def edit_selected(self) -> None:
        selected = self.selected_bots()
        if len(selected) != 1:
            return
        bot = selected[0]
        dialog = BotDialog(self, bot=bot, existing_names=self._names())
        if dialog.exec():
            index = self.config.bots.index(bot)
            self.config.bots[index] = dialog.bot
            self.tracker.forget(bot.id)
            self._after_bots_changed(select=dialog.bot)
            if self.manager.runtime(bot.id).is_active:
                self.statusBar().showMessage("Los cambios se aplicarán la próxima vez que se inicie el bot.", 8000)

    def duplicate_selected(self) -> None:
        selected = self.selected_bots()
        if len(selected) != 1:
            return
        clone = copy.deepcopy(selected[0])
        clone.id = new_id()
        names = self._names()
        base, n = f"{clone.name} (copia)", 2
        clone.name = base
        while clone.name in names:
            clone.name, n = f"{base} {n}", n + 1
        self.config.bots.append(clone)
        self._after_bots_changed(select=clone)

    def delete_selected(self) -> None:
        selected = self.selected_bots()
        if not selected:
            return
        names = ", ".join(f"«{b.name}»" for b in selected)
        box = QMessageBox(QMessageBox.Question, "Eliminar", f"¿Eliminar {names} de BotControl?\n\n"
                          "Los archivos del bot no se borran.", QMessageBox.Yes | QMessageBox.No, self)
        stop = QCheckBox("Detener también los que estén en ejecución")
        stop.setChecked(True)
        if any(self.manager.runtime(b.id).is_active for b in selected):
            box.setCheckBox(stop)
        if box.exec() != QMessageBox.Yes:
            return
        for bot in selected:
            if stop.isChecked() and self.manager.runtime(bot.id).is_active:
                self.manager.stop(bot.id)
                self.manager.wait_all_stopped(10, QApplication.processEvents)
            self.config.bots.remove(bot)
            self.tracker.forget(bot.id)
            self.manager.remove_bot_files(bot.id)
        self._after_bots_changed()

    def _after_bots_changed(self, select: BotConfig | None = None) -> None:
        self.save()
        self.model.reset()
        self.update_empty_state()
        if select and select in self.config.bots:
            self.table.selectRow(self.config.bots.index(select))
        self.update_actions()
        self.check_schedules()

    def open_bot_folder(self) -> None:
        selected = self.selected_bots()
        if not selected:
            return
        bot = selected[0]
        folder = bot.workdir or (str(Path(bot.target).parent) if bot.kind != "command" else "")
        if folder and Path(folder).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_in_telegram(self) -> None:
        selected = self.selected_bots()
        if selected and selected[0].username:
            QDesktopServices.openUrl(QUrl(f"https://t.me/{selected[0].username}"))

    def _on_double_click(self, index) -> None:
        if index.column() != COL_AUTO:
            self.edit_selected()

    def show_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if index.isValid() and not self.table.selectionModel().isRowSelected(index.row(), QModelIndex()):
            self.table.selectRow(index.row())
        menu = QMenu(self)
        if self.selected_bots():
            for action in (self.act_start, self.act_stop, self.act_restart, None, self.act_edit,
                           self.act_libs, self.act_duplicate, self.act_folder, self.act_telegram, None,
                           self.act_delete):
                menu.addSeparator() if action is None else menu.addAction(action)
        else:
            menu.addAction(self.act_add)
            menu.addAction(self.act_detect)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # --------------------------------------------------------- detección
    def _known_scripts(self) -> dict[str, str]:
        return {scanner.norm(b.target): b.name for b in self.config.bots if b.target and b.kind != "command"}

    def detect_running(self) -> None:
        self.statusBar().showMessage("Buscando bots en ejecución…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(candidates, error):
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
            if error:
                QMessageBox.warning(self, "Detectar bots", f"No se pudo analizar los procesos: {error}")
                return
            own = {rt.pid for rt in self.manager.runtimes.values() if rt.is_active}
            candidates = [c for c in candidates if c.pid not in own]
            dialog = CandidatesDialog(
                "Bots abiertos en este PC",
                "Estos procesos parecen bots de Telegram. Elige cuáles quieres controlar desde BotControl "
                "(siguen funcionando, no se reinician):",
                candidates, self._known_scripts(), running=True, parent=self)
            if dialog.exec():
                self._add_candidates(dialog.selected(), adopt=True)

        run_async(scanner.find_running_bots, done, self)

    def scan_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Carpeta donde están tus bots", str(Path.home()))
        if not folder:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(candidates, error):
            QApplication.restoreOverrideCursor()
            if error:
                QMessageBox.warning(self, "Buscar en carpeta", f"No se pudo analizar la carpeta: {error}")
                return
            dialog = CandidatesDialog(
                "Bots encontrados", f"Scripts de bots de Telegram en {folder}:",
                candidates, self._known_scripts(), running=False, parent=self)
            if dialog.exec():
                self._add_candidates(dialog.selected(), adopt=False)

        run_async(lambda: scanner.scan_folder(folder), done, self)

    def _add_candidates(self, candidates: list[scanner.Candidate], adopt: bool) -> None:
        by_script = {scanner.norm(b.target): b for b in self.config.bots if b.kind != "command"}
        names = self._names()
        last = None
        for cand in candidates:
            bot = by_script.get(scanner.norm(cand.script))
            if bot is None:
                bot = cand.to_bot()
                base, n = bot.name or "Bot", 2
                while bot.name in names:
                    bot.name, n = f"{base} {n}", n + 1
                names.add(bot.name)
                self.config.bots.append(bot)
                by_script[scanner.norm(cand.script)] = bot
            if not bot.interpreter and cand.interpreter and scanner.interpreter_kind(cand.interpreter) == bot.kind:
                bot.interpreter = cand.interpreter  # el mismo Python con el que ya funcionaba
            if adopt and cand.pid and not self.manager.runtime(bot.id).is_active:
                try:
                    self.manager.adopt(bot.id, cand.pid)
                except Exception as exc:  # noqa: BLE001 - el proceso pudo terminar entretanto
                    log.warning("No se pudo adoptar %s: %s", cand.pid, exc)
            last = bot
        self._after_bots_changed(select=last)

    # ------------------------------------------------------- import/export
    def export_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar bots", str(Path.home() / "botcontrol-bots.json"),
                                              "JSON (*.json)")
        if path:
            try:
                export_config(self.config, Path(path))
                self.statusBar().showMessage(f"Exportado a {path} (sin tokens)", 8000)
            except OSError as exc:
                QMessageBox.warning(self, "Exportar", str(exc))

    def import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar bots", str(Path.home()), "JSON (*.json)")
        if not path:
            return
        try:
            bots = import_bots(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Importar", f"No se pudo importar: {exc}")
            return
        names, ids = self._names(), {b.id for b in self.config.bots}
        for bot in bots:
            if bot.id in ids:
                bot.id = new_id()
            base, n = bot.name, 2
            while bot.name in names:
                bot.name, n = f"{base} {n}", n + 1
            names.add(bot.name)
            self.config.bots.append(bot)
        self._after_bots_changed()
        self.statusBar().showMessage(f"{len(bots)} bots importados", 8000)

    # ------------------------------------------------------------ ajustes
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config.settings, self)
        if dialog.exec():
            dialog.settings.window_geometry = self.config.settings.window_geometry
            dialog.settings.tray_hint_shown = self.config.settings.tray_hint_shown
            self.config.settings = dialog.settings
            self.save()

    def offer_run_at_login(self) -> None:
        answer = QMessageBox.question(
            self, "Inicio con Windows",
            "Para que los bots marcados se abran al encender el PC, BotControl tiene que iniciarse con "
            "Windows.\n\n¿Activarlo ahora?")
        if answer == QMessageBox.Yes:
            try:
                startup.set_enabled(True)
                self.statusBar().showMessage("BotControl se iniciará con Windows.", 8000)
            except OSError as exc:
                QMessageBox.warning(self, "Inicio con Windows", str(exc))

    def about(self) -> None:
        QMessageBox.about(
            self, f"Acerca de {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Controla, programa y arranca automáticamente tus bots de Telegram.</p>"
            f"<p>Datos y registros: <code>{data_dir()}</code></p>")

    # -------------------------------------------------------- ventana/salir
    def show_window(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._quitting:
            event.accept()
            return
        if self.tray and self.config.settings.minimize_to_tray:
            event.ignore()
            self.hide()
            if not self.config.settings.tray_hint_shown:
                self.tray.showMessage(APP_NAME, "BotControl sigue funcionando aquí. Usa «Salir» del menú para "
                                      "cerrarlo del todo.", QSystemTrayIcon.Information, 6000)
                self.config.settings.tray_hint_shown = True
                self.save()
            return
        event.ignore()
        self.request_quit()

    def request_quit(self) -> None:
        active = self.manager.active_count()
        action = self.config.settings.exit_action
        if active and action == EXIT_ASK:
            self.show_window()
            box = QMessageBox(QMessageBox.Question, "Salir de BotControl",
                              f"Hay {active} bot(s) en ejecución. ¿Qué quieres hacer con ellos?", parent=self)
            stop_button = box.addButton("Detenerlos y salir", QMessageBox.AcceptRole)
            leave_button = box.addButton("Salir y dejarlos funcionando", QMessageBox.DestructiveRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            remember = QCheckBox("Recordar mi elección")
            box.setCheckBox(remember)
            box.exec()
            clicked = box.clickedButton()
            if clicked not in (stop_button, leave_button):
                return
            action = EXIT_STOP if clicked is stop_button else EXIT_LEAVE
            if remember.isChecked():
                self.config.settings.exit_action = action
        if active and action == EXIT_STOP:
            progress = QProgressDialog("Deteniendo bots…", None, 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            self.manager.stop_all()
            self.manager.wait_all_stopped(15, QApplication.processEvents)
            progress.close()
        self._quitting = True
        self._persist()
        if self.tray:
            self.tray.hide()
        QApplication.quit()
