"""Construcción de la línea de comandos de cada bot."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from botcontrol import secrets
from botcontrol.models import BotConfig

IS_WINDOWS = sys.platform == "win32"
VENV_NAMES = ("venv", ".venv", "env", ".env", "virtualenv")


class LaunchError(Exception):
    """Error comprensible para el usuario al preparar el arranque de un bot."""


@dataclass
class LaunchSpec:
    command: list[str] | str
    cwd: str
    env: dict[str, str]
    shell: bool = False

    def display(self) -> str:
        if isinstance(self.command, str):
            return self.command
        return subprocess.list2cmdline(self.command) if IS_WINDOWS else shlex.join(self.command)


def split_args(args: str) -> list[str]:
    args = (args or "").strip()
    if not args:
        return []
    try:
        return _split_windows(args) if IS_WINDOWS else shlex.split(args)
    except ValueError as exc:
        raise LaunchError(f"Argumentos mal formados: {exc}") from exc


def _split_windows(args: str) -> list[str]:
    parts = shlex.split(args, posix=False)
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]


def _venv_python(folder: Path) -> Path | None:
    for name in VENV_NAMES:
        venv = folder / name
        candidates = (
            [venv / "Scripts" / "python.exe"] if IS_WINDOWS else [venv / "bin" / "python3", venv / "bin" / "python"]
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def find_python(script: Path) -> list[str]:
    """Busca el intérprete adecuado: venv junto al script o Python del sistema."""
    folder = script.parent
    for _ in range(3):
        found = _venv_python(folder)
        if found:
            return [str(found)]
        if folder.parent == folder:
            break
        folder = folder.parent
    if IS_WINDOWS:
        python = shutil.which("python")
        # El "python.exe" de WindowsApps es un acceso a la Microsoft Store.
        if python and "windowsapps" not in python.lower():
            return [python]
        launcher = shutil.which("py")
        if launcher:
            return [launcher, "-3"]
        if python:
            return [python]
    else:
        for name in ("python3", "python"):
            python = shutil.which(name)
            if python:
                return [python]
    raise LaunchError(
        "No se encontró Python. Instálalo desde python.org (marcando «Add to PATH») "
        "o indica la ruta del intérprete en la configuración del bot."
    )


def find_node() -> list[str]:
    node = shutil.which("node")
    if not node:
        raise LaunchError("No se encontró Node.js. Instálalo o indica la ruta de node.exe.")
    return [node]


def resolve_interpreter(bot: BotConfig) -> list[str]:
    if bot.interpreter.strip():
        interp = bot.interpreter.strip()
        if not Path(interp).is_file() and not shutil.which(interp):
            raise LaunchError(f"No existe el intérprete indicado: {interp}")
        return [interp]
    if bot.kind == "python":
        return find_python(Path(bot.target))
    if bot.kind == "node":
        return find_node()
    return []


def clean_environ() -> dict[str, str]:
    """Entorno del sistema sin las variables internas de PyInstaller."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for key in list(env):
            if key.startswith(("_PYI_", "_MEIPASS")) or key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
                del env[key]
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            original = env.pop(var + "_ORIG", None)
            if original is not None:
                env[var] = original
            else:
                env.pop(var, None)
    return env


def build_env(bot: BotConfig, base: dict[str, str] | None = None) -> dict[str, str]:
    env = clean_environ() if base is None else dict(base)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Sin colores en la salida (el registro es un archivo). Ojo: FORCE_COLOR los *activa*
    # con cualquier valor en Python 3.13+, así que se quita.
    env.pop("FORCE_COLOR", None)
    env["NO_COLOR"] = "1"
    env["PYTHON_COLORS"] = "0"
    env.update(bot.env)
    if bot.inject_token and bot.token_env.strip():
        token = secrets.unprotect(bot.token_enc)
        if token:
            env[bot.token_env.strip()] = token
    return env


def build_launch(bot: BotConfig) -> LaunchSpec:
    target = bot.target.strip()
    if not target:
        raise LaunchError("No se ha indicado qué ejecutar.")
    args = split_args(bot.args)

    if bot.kind == "command":
        cwd = bot.workdir.strip() or str(Path.home())
        if not Path(cwd).is_dir():
            raise LaunchError(f"No existe la carpeta de trabajo: {cwd}")
        command = target + (" " + bot.args.strip() if bot.args.strip() else "")
        return LaunchSpec(command=command, cwd=cwd, env=build_env(bot), shell=True)

    path = Path(target)
    if not path.is_file():
        raise LaunchError(f"No existe el archivo: {target}")
    cwd = bot.workdir.strip() or str(path.parent)
    if not Path(cwd).is_dir():
        raise LaunchError(f"No existe la carpeta de trabajo: {cwd}")

    if bot.kind == "exe":
        command = [str(path), *args]
    elif bot.kind == "python":
        command = [*resolve_interpreter(bot), "-u", str(path), *args]
    else:  # node
        command = [*resolve_interpreter(bot), str(path), *args]
    return LaunchSpec(command=command, cwd=cwd, env=build_env(bot))
