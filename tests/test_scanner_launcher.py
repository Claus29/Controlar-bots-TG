import sys

import pytest

from botcontrol import scanner
from botcontrol.launcher import LaunchError, build_launch, build_env
from botcontrol.models import BotConfig
from botcontrol import secrets


def test_script_from_cmdline(tmp_path):
    assert scanner.script_from_cmdline(["python.exe", "-u", "bot.py", "--x"], str(tmp_path)) == (
        "python", str(tmp_path / "bot.py"), ["--x"])
    assert scanner.script_from_cmdline(["C:/node.exe", "index.js"], str(tmp_path))[0] == "node"
    assert scanner.script_from_cmdline(["python", "-m", "pkg"], "") is None
    assert scanner.script_from_cmdline(["notepad.exe", "a.py"], "") is None


def test_scan_folder(tmp_path):
    (tmp_path / "bot1").mkdir()
    (tmp_path / "bot1" / "main.py").write_text("from telegram.ext import Application\napp.run_polling()\n")
    (tmp_path / "bot1" / "utils.py").write_text("import telegram\n")
    (tmp_path / "other.py").write_text("print('hola')\n")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "x.py").write_text("import telegram\n")
    found = scanner.scan_folder(tmp_path)
    names = [(c.name, c.likely_entry) for c in found]
    assert names == [("bot1", True), ("utils", False)]


def test_build_launch_python(tmp_path):
    script = tmp_path / "bot.py"
    script.write_text("print(1)")
    bot = BotConfig(name="b", target=str(script), interpreter=sys.executable, args='--a "b c"')
    spec = build_launch(bot)
    assert spec.command[:3] == [sys.executable, "-u", str(script)]
    assert spec.command[3:] == ["--a", "b c"]
    assert spec.cwd == str(tmp_path)


def test_build_launch_detects_venv(tmp_path):
    venv_py = tmp_path / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("")
    script = tmp_path / "bot.py"
    script.write_text("")
    spec = build_launch(BotConfig(name="b", target=str(script)))
    assert spec.command[0] == str(venv_py)


def test_build_launch_errors(tmp_path):
    with pytest.raises(LaunchError):
        build_launch(BotConfig(name="b", target=str(tmp_path / "missing.py")))
    with pytest.raises(LaunchError):
        build_launch(BotConfig(name="b", target=""))


def test_token_injection():
    bot = BotConfig(name="b", token_enc=secrets.protect("1:x"), inject_token=True, token_env="TOKEN")
    assert build_env(bot, {})["TOKEN"] == "1:x"
    bot.inject_token = False
    assert "TOKEN" not in build_env(bot, {})
