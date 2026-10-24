"""Arranque automático de BotControl al iniciar sesión en Windows."""

from __future__ import annotations

import sys
from pathlib import Path

from botcontrol import APP_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_ARG = "--autostart"


def supported() -> bool:
    return sys.platform == "win32"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {AUTOSTART_ARG}'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    return f'"{interpreter}" -m botcontrol {AUTOSTART_ARG}'


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    if not supported():
        raise OSError("El inicio automático sólo está disponible en Windows.")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
