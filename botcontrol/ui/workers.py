"""Ejecución de tareas lentas fuera del hilo de la interfaz."""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

_alive: set["_Task"] = set()


class _Task(QObject):
    finished = Signal(object, object)  # (resultado, excepción)


def run_async(func: Callable[[], Any], on_done: Callable[[Any, BaseException | None], None],
              parent: QObject | None = None) -> None:
    """Ejecuta ``func`` en un hilo y llama a ``on_done`` en el hilo de la interfaz."""
    task = _Task(parent)
    _alive.add(task)

    def deliver(result, error):
        _alive.discard(task)
        on_done(result, error)
        task.deleteLater()

    task.finished.connect(deliver)

    def worker():
        try:
            result, error = func(), None
        except BaseException as exc:  # noqa: BLE001
            result, error = None, exc
        try:
            task.finished.emit(result, error)
        except RuntimeError:  # el diálogo que lo pidió ya se cerró
            _alive.discard(task)

    threading.Thread(target=worker, daemon=True).start()
