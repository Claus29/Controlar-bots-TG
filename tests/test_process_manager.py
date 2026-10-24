import subprocess
import sys
import time

import pytest

from botcontrol.models import AppConfig, BotConfig
from botcontrol.process_manager import AlreadyRunning, BotManager, State, kill_tree

LOOP = "import time, sys\nimport telegram  # noqa\nprint('arrancado', flush=True)\nwhile True: time.sleep(0.2)\n"
CRASH = "import sys\nprint('fallo')\nsys.exit(3)\n"


def make(tmp_path, code, **kw):
    folder = tmp_path / f"bot{len(list(tmp_path.iterdir()))}"
    folder.mkdir()
    script = folder / "bot.py"
    script.write_text(code.replace("import telegram  # noqa\n", "# import telegram\n"))
    bot = BotConfig(name=folder.name, target=str(script), interpreter=sys.executable, **kw)
    cfg = AppConfig(bots=[bot])
    events = []
    mgr = BotManager(cfg, tmp_path / "logs", tmp_path / "runtime.json", lambda *e: events.append(e))
    return mgr, bot, events


def wait(pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_start_stop_and_logs(tmp_path):
    mgr, bot, events = make(tmp_path, LOOP)
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    assert rt.state == State.RUNNING and rt.pid
    assert wait(lambda: "arrancado" in mgr.log_path(bot.id).read_text(encoding="utf-8"))
    mgr.poll()
    mgr.stop(bot.id)
    assert mgr.wait_all_stopped(10)
    assert rt.state == State.STOPPED
    assert [e[1] for e in events] == ["started", "stopped"]


def test_auto_restart_and_give_up(tmp_path):
    mgr, bot, events = make(tmp_path, CRASH, max_restarts=1)
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    assert wait(lambda: (mgr.poll() or rt.state == State.CRASHED))
    assert rt.pending_start_at is not None
    rt.pending_start_at = time.monotonic()  # no esperar el retardo
    mgr.poll()
    assert wait(lambda: (mgr.poll() or rt.state == State.FAILED))
    assert "gave_up" in [e[1] for e in events]


def test_exit_zero_is_not_crash(tmp_path):
    mgr, bot, events = make(tmp_path, "print('fin')\n")
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    assert wait(lambda: (mgr.poll() or rt.state == State.STOPPED))
    assert rt.pending_start_at is None


def test_recover_and_duplicate_detection(tmp_path):
    mgr, bot, _ = make(tmp_path, LOOP)
    external = subprocess.Popen([sys.executable, bot.target], cwd=str(tmp_path))
    try:
        assert wait(lambda: mgr.find_duplicate(bot) == external.pid)
        with pytest.raises(AlreadyRunning):
            mgr.start(bot.id)
        assert mgr.recover() == [bot.id]
        rt = mgr.runtime(bot.id)
        assert rt.external and rt.pid == external.pid and rt.state == State.RUNNING
        mgr.stop(bot.id)
        external.wait(10)
        assert wait(lambda: (mgr.poll() or rt.state == State.STOPPED))
    finally:
        kill_tree(external.pid, 2)


def test_recover_from_runtime_file(tmp_path):
    mgr, bot, _ = make(tmp_path, LOOP)
    mgr.start(bot.id)
    pid = mgr.runtime(bot.id).pid
    try:
        mgr2 = BotManager(mgr.config, tmp_path / "logs", tmp_path / "runtime.json")
        assert mgr2.recover() == [bot.id]
        rt = mgr2.runtime(bot.id)
        assert rt.pid == pid and not rt.external
    finally:
        kill_tree(pid, 2)
        mgr.runtime(bot.id).popen.wait(5)


def test_scheduled_start(tmp_path):
    mgr, bot, _ = make(tmp_path, LOOP)
    mgr.schedule_start(bot.id, 0, "autostart")
    assert mgr.runtime(bot.id).state == State.WAITING
    mgr.poll()
    rt = mgr.runtime(bot.id)
    try:
        assert rt.state == State.RUNNING
    finally:
        mgr.stop(bot.id)
        mgr.wait_all_stopped(10)
