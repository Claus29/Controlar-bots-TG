"""Ejecución de procesos sin ventana, seguros desde el ejecutable empaquetado."""

from __future__ import annotations

import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


@contextmanager
def default_dll_search():
    """Evita que los procesos hijos hereden la carpeta de DLLs de PyInstaller."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not (IS_WINDOWS and getattr(sys, "frozen", False) and meipass):
        yield
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetDllDirectoryW(None)
    try:
        yield
    finally:
        kernel32.SetDllDirectoryW(meipass)


def hidden_popen(command, **kwargs) -> subprocess.Popen:
    """``Popen`` sin ventana de consola."""
    if IS_WINDOWS:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
    with default_dll_search():
        return subprocess.Popen(command, **kwargs)


class Cancelled(Exception):
    pass


def run_streaming(command: list[str], cwd: str | None, env: dict[str, str] | None,
                  on_line: Callable[[str], None] | None = None,
                  cancel: threading.Event | None = None, timeout: float | None = None) -> int:
    """Ejecuta un comando, envía cada línea de salida a ``on_line`` y devuelve el código de salida."""
    proc = hidden_popen(
        command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    killer = None
    if cancel is not None or timeout:
        def watch():
            waited = 0.0
            while proc.poll() is None:
                if (cancel is not None and cancel.is_set()) or (timeout and waited >= timeout):
                    proc.kill()
                    return
                threading.Event().wait(0.2)
                waited += 0.2

        killer = threading.Thread(target=watch, daemon=True)
        killer.start()
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if on_line:
            on_line(line)
    code = proc.wait()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    return code


def run_capture(command: list[str], cwd: str | None = None, env: dict[str, str] | None = None,
                input_text: str | None = None, timeout: float = 30) -> tuple[int, str]:
    """Ejecuta un comando corto y devuelve ``(código, salida)``."""
    proc = hidden_popen(
        command, cwd=cwd, env=env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        out, _ = proc.communicate(input_text.encode("utf-8") if input_text is not None else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return -1, "Tiempo de espera agotado"
    return proc.returncode, out.decode("utf-8", errors="replace")
