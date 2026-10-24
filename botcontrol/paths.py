"""Rutas de datos de la aplicación."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from botcontrol import APP_NAME

IS_WINDOWS = sys.platform == "win32"


def data_dir() -> Path:
    """Carpeta de datos del usuario (%APPDATA%\\BotControl en Windows)."""
    override = os.environ.get("BOTCONTROL_HOME")
    if override:
        base = Path(override)
    elif IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return data_dir() / "config.json"


def runtime_file() -> Path:
    return data_dir() / "runtime.json"


def app_log_file() -> Path:
    return data_dir() / "botcontrol.log"


def resource_path(relative: str) -> Path:
    """Ruta a un recurso empaquetado (funciona también con PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
