"""Librerías de los bots: análisis, detección del error, instalación y recuperación automática.

No usan Internet: se instala un paquete .whl construido aquí mismo.
"""

import sys
import time
import zipfile

import pytest

from botcontrol import deps
from botcontrol.models import AppConfig, BotConfig
from botcontrol.process_manager import BotManager, State


def make_wheel(folder, module):
    """Crea ``<module>-1.0-py3-none-any.whl`` con un módulo que imprime su nombre."""
    folder.mkdir(parents=True, exist_ok=True)
    dist = f"{module}-1.0.dist-info"
    path = folder / f"{module}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as whl:
        whl.writestr(f"{module}/__init__.py", f"NAME = {module!r}\n")
        whl.writestr(f"{dist}/METADATA", f"Metadata-Version: 2.1\nName: {module}\nVersion: 1.0\n")
        whl.writestr(f"{dist}/WHEEL", "Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        whl.writestr(f"{dist}/RECORD", f"{module}/__init__.py,,\n{dist}/METADATA,,\n{dist}/WHEEL,,\n{dist}/RECORD,,\n")
    return path


OFFLINE = lambda wheels: {"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(wheels)}  # noqa: E731


def test_pip_names_and_log_parsing():
    assert deps.pip_name("cv2") == "opencv-python"
    assert deps.pip_name("telebot") == "pyTelegramBotAPI"
    assert deps.pip_name("matplotlib.pyplot") == "matplotlib"
    assert deps.pip_name("requests") == "requests"
    log = "Traceback...\n  import matplotlib.pyplot as plt\nModuleNotFoundError: No module named 'matplotlib'\n"
    assert deps.missing_module_from_log(log, "python") == "matplotlib"
    assert deps.missing_module_from_log("ModuleNotFoundError: No module named 'a.b'", "python") == "a"
    assert deps.missing_module_from_log("todo bien", "python") is None
    node = "Error: Cannot find module './config'\nError: Cannot find module '@grammyjs/menu/out'\n"
    assert deps.missing_module_from_log(node, "node") == "@grammyjs/menu"
    assert deps.missing_module_from_log("Error: Cannot find module './x'", "node") is None


def test_scan_imports(tmp_path):
    (tmp_path / "bot.py").write_text(
        "import os, json\nimport matplotlib.pyplot as plt\nfrom telegram.ext import Application\n"
        "from . import algo\nfrom utils import helper\n"
        "try:\n    import ujson\nexcept ImportError:\n    ujson = None\n"
        "try:\n    import numpy\nexcept ValueError:\n    pass\n"
    )
    (tmp_path / "utils.py").write_text("import requests\n")
    (tmp_path / "roto.py").write_text("print 'python2'\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("import nunca\n")
    found = deps.scan_imports(tmp_path)
    assert set(found) == {"os", "json", "matplotlib", "telegram", "ujson", "numpy", "requests"}
    assert found["ujson"].optional and not found["numpy"].optional and not found["matplotlib"].optional
    assert found["requests"].files == {"utils.py"}


def test_analyze_reports_missing(tmp_path):
    (tmp_path / "bot.py").write_text("import json\nimport libreria_que_no_existe_bc\nimport propio\n")
    (tmp_path / "propio.py").write_text("")
    bot = BotConfig(name="b", target=str(tmp_path / "bot.py"), interpreter=sys.executable)
    items = deps.analyze(bot)
    assert [(i.module, i.package) for i in items] == [("libreria_que_no_existe_bc", "libreria_que_no_existe_bc")]
    assert deps.interpreter_info([sys.executable])["version"] == sys.version.split()[0]


def test_fingerprint_and_needs_sync(tmp_path):
    bot = BotConfig(name="b", target=str(tmp_path / "bot.py"), interpreter=sys.executable)
    (tmp_path / "bot.py").write_text("")
    assert not deps.needs_sync(bot)  # nada que gestionar
    (tmp_path / "requirements.txt").write_text("requests\n")
    assert deps.needs_sync(bot)
    bot.deps_hash = deps.fingerprint(bot)
    assert not deps.needs_sync(bot)
    (tmp_path / "requirements.txt").write_text("requests\nPillow\n")
    assert deps.needs_sync(bot)
    bot.auto_install = False
    assert not deps.needs_sync(bot)


@pytest.fixture(scope="module")
def venv_python(tmp_path_factory):
    """Un venv real, compartido por los tests que instalan paquetes."""
    base = tmp_path_factory.mktemp("venvbase")
    bot = BotConfig(name="v", target=str(base / "bot.py"), interpreter=sys.executable)
    (base / "bot.py").write_text("")
    return deps.create_isolated_env(bot, base)


def test_isolated_env_installs_requirements(tmp_path, venv_python):
    wheels = tmp_path / "wheels"
    make_wheel(wheels, "libreq_bc")
    make_wheel(wheels, "libextra_bc")
    make_wheel(wheels, "libcodigo_bc")
    folder = tmp_path / "bot"
    folder.mkdir()
    (folder / "bot.py").write_text("import libcodigo_bc\n")
    (folder / "requirements.txt").write_text("libreq_bc\n")
    bot = BotConfig(name="b", target=str(folder / "bot.py"), interpreter=sys.executable,
                    extra_packages=["libextra_bc"], env=OFFLINE(wheels))
    lines = []
    python = deps.create_isolated_env(bot, tmp_path / "data", base=[str(venv_python)], on_line=lines.append)
    assert python == deps.venv_python(folder / ".venv") and python.is_file()
    names = {name.lower() for name, _ in deps.pip_list([str(python)], deps.pip_env(bot))}
    assert {"libreq-bc", "libextra-bc", "libcodigo-bc"} <= {n.replace("_", "-") for n in names}
    assert any("libcodigo_bc" in line for line in lines)


def test_bot_recovers_from_missing_library(tmp_path, venv_python):
    """El caso del error real: el bot se cae por «No module named …» y BotControl lo arregla solo."""
    wheels = tmp_path / "wheels"
    make_wheel(wheels, "libfalta_bc")
    folder = tmp_path / "bot"
    folder.mkdir()
    (folder / "bot.py").write_text(
        "import time\nimport libfalta_bc\nprint('cargada', libfalta_bc.NAME, flush=True)\n"
        "while True: time.sleep(0.2)\n")
    bot = BotConfig(name="b", target=str(folder / "bot.py"), interpreter=str(venv_python), env=OFFLINE(wheels))
    events = []
    mgr = BotManager(AppConfig(bots=[bot]), tmp_path / "logs", tmp_path / "rt.json", lambda *e: events.append(e[1]))
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    deadline = time.time() + 120
    while time.time() < deadline and "cargada libfalta_bc" not in mgr.log_path(bot.id).read_text("utf-8"):
        mgr.poll()
        time.sleep(0.1)
    try:
        assert rt.state == State.RUNNING, rt.message
        assert "deps" in events and "deps_installed" in events
        assert "libfalta_bc" in rt.dep_attempts
    finally:
        mgr.stop(bot.id)
        mgr.wait_all_stopped(10)


def test_missing_library_not_retried_forever(tmp_path, venv_python):
    folder = tmp_path / "bot"
    folder.mkdir()
    (folder / "bot.py").write_text("import libreria_inexistente_bc\n")
    bot = BotConfig(name="b", target=str(folder / "bot.py"), interpreter=str(venv_python),
                    env=OFFLINE(tmp_path / "vacio"))
    (tmp_path / "vacio").mkdir()
    events = []
    mgr = BotManager(AppConfig(bots=[bot]), tmp_path / "logs", tmp_path / "rt.json", lambda *e: events.append(e[1]))
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    deadline = time.time() + 120
    while time.time() < deadline and rt.state != State.FAILED:
        mgr.poll()
        time.sleep(0.1)
    assert rt.state == State.FAILED
    assert "missing_module" in events
    assert not rt.busy and rt.pending_start_at is None


def _run_until(mgr, rt, predicate, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        mgr.poll()
        time.sleep(0.1)
    return predicate()


def test_requirements_installed_before_start(tmp_path, venv_python):
    wheels = tmp_path / "wheels"
    make_wheel(wheels, "libsync_bc")
    folder = tmp_path / "bot"
    folder.mkdir()
    (folder / "requirements.txt").write_text("libsync_bc\n")
    (folder / "bot.py").write_text("import time, libsync_bc\nprint('ok sync', flush=True)\nwhile True: time.sleep(0.2)\n")
    bot = BotConfig(name="b", target=str(folder / "bot.py"), interpreter=str(venv_python), env=OFFLINE(wheels))
    events = []
    mgr = BotManager(AppConfig(bots=[bot]), tmp_path / "logs", tmp_path / "rt.json", lambda *e: events.append(e[1]))
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    assert rt.state == State.WAITING and rt.busy  # instalando antes de arrancar
    try:
        assert _run_until(mgr, rt, lambda: "ok sync" in mgr.log_path(bot.id).read_text("utf-8"))
        assert rt.state == State.RUNNING
        assert bot.deps_hash == deps.fingerprint(bot) and not deps.needs_sync(bot)
        assert "crashed" not in events
    finally:
        mgr.stop(bot.id)
        mgr.wait_all_stopped(10)


def test_failed_sync_still_starts_bot(tmp_path, venv_python):
    (tmp_path / "vacio").mkdir()
    folder = tmp_path / "bot"
    folder.mkdir()
    (folder / "requirements.txt").write_text("paquete_que_no_existe_bc\n")
    (folder / "bot.py").write_text("import time\nprint('arrancado', flush=True)\nwhile True: time.sleep(0.2)\n")
    bot = BotConfig(name="b", target=str(folder / "bot.py"), interpreter=str(venv_python),
                    env=OFFLINE(tmp_path / "vacio"))
    events = []
    mgr = BotManager(AppConfig(bots=[bot]), tmp_path / "logs", tmp_path / "rt.json", lambda *e: events.append(e[1]))
    mgr.start(bot.id)
    rt = mgr.runtime(bot.id)
    try:
        assert _run_until(mgr, rt, lambda: rt.state == State.RUNNING)
        assert "deps_failed" in events and bot.deps_hash == ""
    finally:
        mgr.stop(bot.id)
        mgr.wait_all_stopped(10)
