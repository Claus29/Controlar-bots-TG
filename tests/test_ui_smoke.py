"""Prueba de humo de la interfaz (sin pantalla)."""

import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from botcontrol.models import AppConfig, BotConfig, Schedule  # noqa: E402
from botcontrol.process_manager import BotManager, State  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from botcontrol.ui.theme import apply_theme

    apply_theme(instance)
    yield instance


def test_main_window_lifecycle(app, tmp_path):
    from botcontrol.ui.bot_dialog import BotDialog
    from botcontrol.ui.main_window import MainWindow
    from botcontrol.ui.settings_dialog import SettingsDialog

    script = tmp_path / "bot.py"
    script.write_text("import time\nprint('hola', flush=True)\nwhile True: time.sleep(0.2)\n")
    bot = BotConfig(name="Demo", target=str(script), interpreter=sys.executable,
                    schedule=Schedule(enabled=True, start="00:00", stop="00:00"))
    cfg = AppConfig(bots=[bot])
    mgr = BotManager(cfg, tmp_path / "logs", tmp_path / "runtime.json")
    window = MainWindow(cfg, mgr)
    window.show()
    window.check_schedules()  # franja de día completo: debe programar el arranque
    for _ in range(30):
        window.tick()
        app.processEvents()
        if mgr.runtime(bot.id).state == State.RUNNING:
            break
        time.sleep(0.1)
    assert mgr.runtime(bot.id).state == State.RUNNING

    window.table.selectRow(0)
    window.update_actions()
    assert window.act_stop.isEnabled() and not window.act_start.isEnabled()
    for _ in range(20):
        app.processEvents()
        window.log_view.refresh()
        if "hola" in window.log_view.text.toPlainText():
            break
        time.sleep(0.1)
    assert "hola" in window.log_view.text.toPlainText()

    dialog = BotDialog(window, bot=bot, existing_names={"Demo"})
    collected = dialog._collect()
    assert collected.name == "Demo" and collected.schedule.enabled
    SettingsDialog(cfg.settings, window)

    window.stop_selected()
    assert mgr.wait_all_stopped(10)
    assert mgr.runtime(bot.id).state == State.STOPPED
    window._quitting = True
    window.close()
