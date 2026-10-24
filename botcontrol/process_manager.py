"""Gestión de los procesos de los bots (independiente de la interfaz)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

import psutil

from botcontrol import scanner
from botcontrol.launcher import IS_WINDOWS, LaunchError, build_launch
from botcontrol.models import AppConfig, BotConfig
from botcontrol.storage import read_json, write_json_atomic

log = logging.getLogger(__name__)

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class State(str, Enum):
    STOPPED = "stopped"
    WAITING = "waiting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"
    FAILED = "failed"


STATE_LABELS = {
    State.STOPPED: "Detenido",
    State.WAITING: "En espera",
    State.RUNNING: "En ejecución",
    State.STOPPING: "Deteniendo…",
    State.CRASHED: "Caído",
    State.FAILED: "Error",
}


class AlreadyRunning(Exception):
    def __init__(self, pid: int):
        super().__init__(f"Ya hay un proceso ejecutando este bot (PID {pid}).")
        self.pid = pid


@dataclass
class Runtime:
    state: State = State.STOPPED
    pid: int | None = None
    create_time: float | None = None
    popen: subprocess.Popen | None = None
    external: bool = False  # adoptado: no lo lanzó esta sesión de BotControl
    started_at: float | None = None
    stop_requested: bool = False
    restart_after_stop: bool = False
    pending_start_at: float | None = None
    pending_reason: str = ""
    restart_times: deque = field(default_factory=deque)
    restarts: int = 0
    last_exit: int | None = None
    message: str = ""
    cpu: float = 0.0
    memory: int = 0
    procs: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.state in (State.RUNNING, State.STOPPING)

    def uptime(self) -> float:
        if self.is_active and self.started_at:
            return max(0.0, time.time() - self.started_at)
        return 0.0


EventCallback = Callable[[str, str, str], None]  # (bot_id, tipo, mensaje)


class BotManager:
    def __init__(self, config: AppConfig, logs_dir: Path, runtime_path: Path,
                 on_event: EventCallback | None = None) -> None:
        self.config = config
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_path = Path(runtime_path)
        self.on_event = on_event or (lambda *_: None)
        self.runtimes: dict[str, Runtime] = {}
        self._lock = threading.RLock()
        self._snapshot: tuple[float, list[dict]] | None = None

    # ------------------------------------------------------------------ util
    def runtime(self, bot_id: str) -> Runtime:
        with self._lock:
            return self.runtimes.setdefault(bot_id, Runtime())

    def log_path(self, bot_id: str) -> Path:
        return self.logs_dir / f"{bot_id}.log"

    def _emit(self, bot_id: str, kind: str, message: str) -> None:
        log.info("[%s] %s: %s", bot_id, kind, message)
        try:
            self.on_event(bot_id, kind, message)
        except Exception:  # noqa: BLE001 - un fallo de la UI no debe parar la gestión
            log.exception("Error en on_event")

    def _note(self, bot_id: str, text: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_path(bot_id), "a", encoding="utf-8") as fh:
                fh.write(f"\n[BotControl {stamp}] {text}\n")
        except OSError:
            pass

    def _rotate_log(self, bot_id: str) -> None:
        path = self.log_path(bot_id)
        limit = max(1, self.config.settings.max_log_mb) * 1024 * 1024
        try:
            if not path.exists() or path.stat().st_size < limit:
                return
            for index in (2, 1):
                older = path.with_suffix(f".log.{index}")
                if older.exists():
                    os.replace(older, path.with_suffix(f".log.{index + 1}"))
            os.replace(path, path.with_suffix(".log.1"))
        except OSError:
            log.warning("No se pudo rotar el log de %s (¿en uso?)", bot_id)

    def remove_bot_files(self, bot_id: str) -> None:
        for path in self.logs_dir.glob(f"{bot_id}.log*"):
            try:
                path.unlink()
            except OSError:
                pass
        with self._lock:
            self.runtimes.pop(bot_id, None)
        self.save_runtime()

    # ------------------------------------------------------- persistencia PID
    def save_runtime(self) -> None:
        with self._lock:
            data = {
                bot_id: {"pid": rt.pid, "create_time": rt.create_time}
                for bot_id, rt in self.runtimes.items()
                if rt.is_active and rt.pid
            }
        try:
            write_json_atomic(self.runtime_path, data)
        except OSError:
            log.exception("No se pudo guardar runtime.json")

    def recover(self) -> list[str]:
        """Recupera los bots que siguen en marcha (de una sesión anterior o abiertos a mano)."""
        recovered = []
        saved = read_json(self.runtime_path, {})
        if not isinstance(saved, dict):
            saved = {}
        claimed: set[int] = set()
        for bot in self.config.bots:
            entry = saved.get(bot.id) or {}
            pid, ctime = entry.get("pid"), entry.get("create_time")
            if pid and self._pid_matches(pid, ctime):
                self._attach(bot.id, pid, external=False, message="Recuperado de la sesión anterior")
                claimed.add(pid)
                recovered.append(bot.id)
        processes = None
        for bot in self.config.bots:
            if bot.id in recovered:
                continue
            if processes is None:
                processes = self._processes()
            pid = scanner.find_process_for(bot, processes, exclude=claimed)
            if pid:
                self._attach(bot.id, pid, external=True, message="Ya estaba en ejecución")
                claimed.add(pid)
                recovered.append(bot.id)
        self.save_runtime()
        return recovered

    @staticmethod
    def _pid_matches(pid: int, create_time: float | None) -> bool:
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            return create_time is None or abs(proc.create_time() - create_time) < 1.0
        except (psutil.Error, OSError):
            return False

    def _attach(self, bot_id: str, pid: int, external: bool, message: str) -> None:
        proc = psutil.Process(pid)
        rt = self.runtime(bot_id)
        rt.state = State.RUNNING
        rt.pid = pid
        rt.create_time = proc.create_time()
        rt.started_at = rt.create_time
        rt.popen = None
        rt.external = external
        rt.stop_requested = False
        rt.pending_start_at = None
        rt.message = message
        rt.procs = {}
        self._emit(bot_id, "adopted", message)

    def adopt(self, bot_id: str, pid: int) -> None:
        self._attach(bot_id, pid, external=True, message=f"Adoptado (PID {pid})")
        self.save_runtime()

    # ------------------------------------------------------------ arranque
    def _processes(self) -> list[dict]:
        """Lista de procesos del sistema, reutilizada unos segundos (iniciar varios bots a la vez)."""
        now = time.monotonic()
        if self._snapshot is None or now - self._snapshot[0] > 3:
            self._snapshot = (now, scanner.iter_processes())
        return self._snapshot[1]

    def find_duplicate(self, bot: BotConfig) -> int | None:
        own = {rt.pid for rt in self.runtimes.values() if rt.is_active and rt.pid}
        pid = scanner.find_process_for(bot, self._processes(), exclude=own)
        if pid and not psutil.pid_exists(pid):  # la lista guardada estaba desfasada
            self._snapshot = None
            pid = scanner.find_process_for(bot, self._processes(), exclude=own)
        return pid

    def start(self, bot_id: str, reason: str = "manual", check_duplicates: bool = True) -> None:
        bot = self.config.get(bot_id)
        if bot is None:
            raise LaunchError("El bot no existe.")
        rt = self.runtime(bot_id)
        if rt.is_active:
            return
        if check_duplicates:
            pid = self.find_duplicate(bot)
            if pid:
                raise AlreadyRunning(pid)

        try:
            spec = build_launch(bot)
        except LaunchError as exc:
            rt.state = State.FAILED
            rt.message = str(exc)
            rt.pending_start_at = None
            self._note(bot_id, f"No se pudo iniciar: {exc}")
            self._emit(bot_id, "error", str(exc))
            raise

        self._rotate_log(bot_id)
        log_file = open(self.log_path(bot_id), "ab")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"\n===== [BotControl {stamp}] Iniciando ({reason}): {spec.display()} =====\n"
        log_file.write(header.encode("utf-8"))
        log_file.flush()
        try:
            popen = self._spawn(spec, log_file)
        except OSError as exc:
            log_file.close()
            rt.state = State.FAILED
            rt.message = f"No se pudo iniciar: {exc}"
            rt.pending_start_at = None
            self._note(bot_id, rt.message)
            self._emit(bot_id, "error", rt.message)
            raise LaunchError(rt.message) from exc
        log_file.close()

        rt.popen = popen
        rt.pid = popen.pid
        try:
            rt.create_time = psutil.Process(popen.pid).create_time()
        except (psutil.Error, OSError):
            rt.create_time = time.time()
        rt.started_at = time.time()
        rt.state = State.RUNNING
        rt.external = False
        rt.stop_requested = False
        rt.restart_after_stop = False
        rt.pending_start_at = None
        rt.last_exit = None
        rt.message = ""
        rt.procs = {}
        self.save_runtime()
        self._emit(bot_id, "started", f"Iniciado (PID {popen.pid})")

    @staticmethod
    def _spawn(spec, log_file) -> subprocess.Popen:
        kwargs = dict(
            cwd=spec.cwd, env=spec.env, shell=spec.shell,
            stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
        )
        if IS_WINDOWS:
            flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            with _default_dll_search():
                try:
                    # Fuera del "job" de BotControl: el bot sobrevive si se cierra la app.
                    return subprocess.Popen(spec.command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kwargs)
                except OSError:
                    return subprocess.Popen(spec.command, creationflags=flags, **kwargs)
        return subprocess.Popen(spec.command, start_new_session=True, **kwargs)

    def schedule_start(self, bot_id: str, delay: float, reason: str) -> None:
        rt = self.runtime(bot_id)
        if rt.is_active:
            return
        rt.state = State.WAITING
        rt.pending_start_at = time.monotonic() + max(0.0, delay)
        rt.pending_reason = reason
        rt.message = f"Inicio en {int(delay)} s" if delay >= 1 else "Iniciando…"

    # ------------------------------------------------------------- parada
    def stop(self, bot_id: str, timeout: float = 8.0, restart: bool = False) -> None:
        rt = self.runtime(bot_id)
        if rt.state == State.WAITING or (not rt.is_active and rt.pending_start_at):
            rt.pending_start_at = None
            rt.state = State.STOPPED
            rt.message = "Inicio cancelado"
            return
        if not rt.is_active or not rt.pid:
            if rt.state in (State.CRASHED, State.FAILED):
                rt.state = State.STOPPED
            return
        rt.stop_requested = True
        rt.restart_after_stop = restart
        rt.state = State.STOPPING
        threading.Thread(target=kill_tree, args=(rt.pid, timeout), daemon=True).start()

    def restart(self, bot_id: str) -> None:
        rt = self.runtime(bot_id)
        if rt.is_active:
            self.stop(bot_id, restart=True)
        else:
            rt.restart_times.clear()
            self.start(bot_id, reason="reinicio", check_duplicates=True)

    def stop_all(self, timeout: float = 8.0) -> None:
        for bot in self.config.bots:
            self.stop(bot.id, timeout)

    def active_count(self) -> int:
        return sum(1 for rt in self.runtimes.values() if rt.is_active)

    def wait_all_stopped(self, timeout: float = 12.0, tick: Callable[[], None] | None = None) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.poll(update_stats=False)
            if not any(rt.state == State.STOPPING for rt in self.runtimes.values()):
                return True
            if tick:
                tick()
            time.sleep(0.1)
        return False

    # ------------------------------------------------------------ sondeo
    def _alive(self, rt: Runtime) -> tuple[bool, int | None]:
        if rt.popen is not None:
            code = rt.popen.poll()
            return code is None, code
        return self._pid_matches(rt.pid, rt.create_time) if rt.pid else False, None

    def poll(self, update_stats: bool = True) -> None:
        now = time.monotonic()
        changed = False
        for bot in list(self.config.bots):
            rt = self.runtime(bot.id)
            if rt.pending_start_at is not None and not rt.is_active and now >= rt.pending_start_at:
                reason = rt.pending_reason or "programado"
                rt.pending_start_at = None
                try:
                    self.start(bot.id, reason=reason, check_duplicates=True)
                except AlreadyRunning as exc:
                    self.adopt(bot.id, exc.pid)
                except LaunchError:
                    pass
                changed = True
                continue
            if not rt.is_active:
                continue
            alive, code = self._alive(rt)
            if alive:
                if update_stats:
                    self._update_stats(rt)
                continue
            changed = True
            self._handle_exit(bot, rt, code)
        if changed:
            self.save_runtime()

    def _handle_exit(self, bot: BotConfig, rt: Runtime, code: int | None) -> None:
        rt.last_exit = code
        rt.popen = None
        rt.pid = None
        rt.cpu = 0.0
        rt.memory = 0
        rt.procs = {}
        code_text = f" (código {code})" if code is not None else ""
        if rt.stop_requested:
            rt.stop_requested = False
            rt.state = State.STOPPED
            rt.message = "Detenido"
            self._note(bot.id, "Detenido por el usuario")
            self._emit(bot.id, "stopped", "Detenido")
            if rt.restart_after_stop:
                rt.restart_after_stop = False
                rt.restart_times.clear()
                try:
                    self.start(bot.id, reason="reinicio")
                except (LaunchError, AlreadyRunning) as exc:
                    rt.message = str(exc)
            return

        if code == 0:
            rt.state = State.STOPPED
            rt.message = "Finalizó por sí mismo"
            self._note(bot.id, "El proceso terminó normalmente")
            self._emit(bot.id, "exited", rt.message)
            return

        rt.state = State.CRASHED
        self._note(bot.id, f"El proceso se cerró inesperadamente{code_text}")
        if not bot.auto_restart:
            rt.message = f"Se cerró{code_text}"
            self._emit(bot.id, "crashed", f"Se ha caído{code_text}")
            return
        now = time.monotonic()
        while rt.restart_times and now - rt.restart_times[0] > bot.restart_window:
            rt.restart_times.popleft()
        if len(rt.restart_times) >= max(0, bot.max_restarts):
            rt.state = State.FAILED
            rt.message = f"Demasiados fallos: reinicio automático desactivado{code_text}"
            self._note(bot.id, rt.message)
            self._emit(bot.id, "gave_up", f"Se ha caído {len(rt.restart_times) + 1} veces seguidas; no se reinicia más")
            return
        delay = min(60, 3 * 2 ** len(rt.restart_times))
        rt.restart_times.append(now)
        rt.restarts += 1
        rt.pending_start_at = now + delay
        rt.pending_reason = "reinicio automático"
        rt.message = f"Caído{code_text}; reinicio en {delay} s"
        self._emit(bot.id, "crashed", f"Se ha caído{code_text}; se reiniciará en {delay} s")

    def _update_stats(self, rt: Runtime) -> None:
        try:
            root = rt.procs.get(rt.pid) or psutil.Process(rt.pid)
            tree = [root, *root.children(recursive=True)]
        except (psutil.Error, OSError):
            return
        cpu, mem, current = 0.0, 0, {}
        for proc in tree:
            cached = rt.procs.get(proc.pid, proc)
            current[proc.pid] = cached
            try:
                cpu += cached.cpu_percent(None)
                mem += cached.memory_info().rss
            except (psutil.Error, OSError):
                continue
        rt.procs = current
        rt.cpu = cpu / (psutil.cpu_count() or 1)
        rt.memory = mem


@contextmanager
def _default_dll_search():
    """Evita que los bots hereden la carpeta de DLLs del ejecutable empaquetado (PyInstaller)."""
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


def kill_tree(pid: int, timeout: float = 8.0) -> None:
    """Termina un proceso y todos sus hijos (primero con suavidad, luego a la fuerza)."""
    try:
        root = psutil.Process(pid)
        procs = [root, *root.children(recursive=True)]
    except (psutil.Error, OSError):
        return
    for proc in reversed(procs):
        try:
            proc.terminate()
        except (psutil.Error, OSError):
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.Error, OSError):
            pass
    psutil.wait_procs(alive, timeout=3)

