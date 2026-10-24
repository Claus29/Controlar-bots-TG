"""Punto de entrada: instancia única, arranque y bucle de la aplicación."""

from __future__ import annotations

import argparse
import getpass
import logging
import re
import sys
import traceback
from logging.handlers import RotatingFileHandler

from botcontrol import APP_NAME, __version__
from botcontrol.paths import app_log_file, config_file, logs_dir, runtime_file
from botcontrol.process_manager import BotManager
from botcontrol.startup import AUTOSTART_ARG
from botcontrol.storage import load_config

log = logging.getLogger("botcontrol")


def setup_logging() -> None:
    handler = RotatingFileHandler(app_log_file(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument(AUTOSTART_ARG, dest="autostart", action="store_true",
                        help="Lanzado al iniciar sesión en Windows")
    parser.add_argument("--minimized", action="store_true", help="Arrancar oculto en la bandeja")
    parser.add_argument("--selftest", metavar="ARCHIVO", help="Comprobación de arranque (para CI)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return f"{APP_NAME}-" + re.sub(r"[^A-Za-z0-9_-]", "_", user)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging()
    log.info("Iniciando %s %s (autostart=%s)", APP_NAME, __version__, args.autostart)

    from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QMessageBox

    from botcontrol.ui.main_window import MainWindow
    from botcontrol.ui.theme import app_icon, apply_theme

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.App")
        except (AttributeError, OSError):
            pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Spain))
    translator = QTranslator(app)
    if translator.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    apply_theme(app)

    # Instancia única: si ya está abierta, se le pide que se muestre y salimos.
    name = server_name()
    if not args.selftest:
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(500):
            if not args.autostart:
                socket.write(b"show")
                socket.flush()
                socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            log.info("Ya hay una instancia en ejecución")
            return 0
    server = QLocalServer()
    QLocalServer.removeServer(name)
    server.listen(name)

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Error no controlado:\n%s", text)
        try:
            QMessageBox.critical(None, APP_NAME, f"Se produjo un error inesperado:\n\n{exc}\n\n"
                                                 f"Detalles en {app_log_file()}")
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = excepthook

    config = load_config(config_file())
    manager = BotManager(config, logs_dir(), runtime_file())
    window = MainWindow(config, manager, launched_at_boot=args.autostart)
    recovered = manager.recover()
    if recovered:
        log.info("Bots recuperados: %s", recovered)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(300)
            conn.readAll()
            conn.disconnectFromServer()
            window.show_window()

    server.newConnection.connect(on_connection)

    if args.selftest:
        window.show()
        window.tick()
        with open(args.selftest, "w", encoding="utf-8") as fh:
            fh.write(f"ok {__version__} bots={len(config.bots)}\n")
        QTimer.singleShot(300, app.quit)
        return app.exec()

    hidden = args.minimized or (args.autostart and config.settings.start_minimized_on_boot)
    if hidden and window.tray:
        window.hide()
    else:
        window.show()

    window.check_schedules()
    window.run_autostart()
    code = app.exec()
    server.close()
    log.info("BotControl cerrado")
    return code
