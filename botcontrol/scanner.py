"""Detección de bots de Telegram: en procesos en ejecución y en carpetas."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import psutil

from botcontrol.models import BotConfig

TELEGRAM_MARKERS = re.compile(
    rb"(?:^|\W)(?:import\s+telegram|from\s+telegram|aiogram|telebot|pyrogram|telethon|"
    rb"api\.telegram\.org|telegraf|node-telegram-bot-api|grammy)",
    re.IGNORECASE,
)
ENTRY_MARKERS = re.compile(
    rb"(__name__\s*==\s*['\"]__main__['\"]|run_polling|infinity_polling|start_polling|"
    rb"run_until_disconnected|run_webhook|\.polling\(|\.launch\(|executor\.start|asyncio\.run\(|app\.run\()",
)
PY_EXT = (".py", ".pyw")
JS_EXT = (".js", ".mjs", ".cjs", ".ts")
SKIP_DIRS = {
    "venv", ".venv", "env", ".env", "virtualenv", "node_modules", ".git", "__pycache__",
    "site-packages", "dist-packages", "lib", "Lib", "Scripts", "build", "dist", ".idea", ".vscode",
}
GENERIC_STEMS = {"main", "bot", "app", "run", "index", "__main__", "start", "server"}


def norm(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def read_head(path: Path, limit: int = 256 * 1024) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(limit)
    except OSError:
        return b""


def is_telegram_script(path: Path) -> bool:
    return bool(TELEGRAM_MARKERS.search(read_head(path)))


def guess_name(script: str) -> str:
    path = Path(script)
    stem = path.stem
    if stem.lower() in GENERIC_STEMS and path.parent.name:
        return path.parent.name
    return stem


@dataclass
class Candidate:
    kind: str
    script: str
    name: str
    is_telegram: bool = True
    likely_entry: bool = True
    pid: int | None = None
    interpreter: str = ""
    cwd: str = ""
    args: str = ""
    cmdline: str = ""

    def to_bot(self) -> BotConfig:
        return BotConfig(
            name=self.name,
            kind=self.kind,
            target=self.script,
            interpreter="",
            workdir=self.cwd if self.cwd and norm(self.cwd) != norm(Path(self.script).parent) else "",
            args=self.args,
        )


def _interpreter_kind(exe_or_name: str) -> str | None:
    name = Path(exe_or_name).name.lower()
    for suffix in (".exe",):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    if name in ("py", "pyw") or name.startswith("python"):
        return "python"
    if name in ("node", "nodejs", "bun", "deno"):
        return "node"
    return None


def script_from_cmdline(cmdline: list[str], cwd: str = "") -> tuple[str, str, list[str]] | None:
    """Devuelve ``(tipo, script, argumentos)`` si el proceso ejecuta un script."""
    if not cmdline:
        return None
    kind = _interpreter_kind(cmdline[0])
    if not kind:
        return None
    extensions = PY_EXT if kind == "python" else JS_EXT
    rest = cmdline[1:]
    for index, arg in enumerate(rest):
        if kind == "python" and arg in ("-m", "-c"):
            return None
        if arg.lower().endswith(extensions):
            script = arg
            if not os.path.isabs(script) and cwd:
                script = os.path.join(cwd, script)
            return kind, os.path.abspath(script), rest[index + 1:]
    return None


def _proc_info(proc: psutil.Process) -> dict | None:
    try:
        with proc.oneshot():
            cmdline = proc.cmdline()
            if not cmdline:
                return None
            return {
                "pid": proc.pid,
                "ppid": proc.ppid(),
                "cmdline": cmdline,
                "exe": _safe(proc.exe),
                # La carpeta sólo hace falta para resolver scripts con ruta relativa.
                "cwd": _safe(proc.cwd) if _interpreter_kind(cmdline[0]) else "",
                "create_time": proc.create_time(),
            }
    except (psutil.Error, OSError):
        return None


def _safe(func) -> str:
    try:
        return func() or ""
    except (psutil.Error, OSError):
        return ""


def iter_processes(exclude: set[int] | None = None) -> list[dict]:
    exclude = exclude or set()
    own = os.getpid()
    result = []
    for proc in psutil.process_iter():
        if proc.pid in exclude or proc.pid == own:
            continue
        info = _proc_info(proc)
        if info:
            result.append(info)
    return result


def _topmost(matches: list[dict]) -> list[dict]:
    """Quita los procesos hijos de otro proceso que también coincide (p. ej. py.exe → python.exe)."""
    pids = {m["pid"] for m in matches}
    return [m for m in matches if m["ppid"] not in pids]


def find_running_bots(processes: list[dict] | None = None, only_telegram: bool = True) -> list[Candidate]:
    processes = iter_processes() if processes is None else processes
    matches: list[dict] = []
    for info in processes:
        parsed = script_from_cmdline(info["cmdline"], info["cwd"])
        if not parsed:
            continue
        kind, script, args = parsed
        telegram = is_telegram_script(Path(script))
        if only_telegram and not telegram:
            continue
        info = dict(info, kind=kind, script=script, args=args, telegram=telegram)
        matches.append(info)

    candidates = []
    for info in _topmost(matches):
        candidates.append(
            Candidate(
                kind=info["kind"],
                script=info["script"],
                name=guess_name(info["script"]),
                is_telegram=info["telegram"],
                pid=info["pid"],
                interpreter=info["exe"] or info["cmdline"][0],
                cwd=info["cwd"],
                args=" ".join(_quote(a) for a in info["args"]),
                cmdline=" ".join(info["cmdline"]),
            )
        )
    return candidates


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def process_matches_bot(info: dict, bot: BotConfig) -> bool:
    target = bot.target.strip()
    if not target or bot.kind == "command":
        return False
    if bot.kind == "exe":
        return bool(info["exe"]) and norm(info["exe"]) == norm(target)
    parsed = script_from_cmdline(info["cmdline"], info["cwd"])
    return bool(parsed) and norm(parsed[1]) == norm(target)


def find_process_for(bot: BotConfig, processes: list[dict] | None = None,
                     exclude: set[int] | None = None) -> int | None:
    """PID del proceso (el de más arriba en el árbol) que ejecuta ese bot, si existe."""
    processes = iter_processes(exclude) if processes is None else processes
    matches = [p for p in processes if process_matches_bot(p, bot) and p["pid"] not in (exclude or set())]
    top = _topmost(matches)
    return top[0]["pid"] if top else None


def scan_folder(folder: str | os.PathLike, max_depth: int = 4, max_files: int = 20000) -> list[Candidate]:
    root = Path(folder)
    candidates: list[Candidate] = []
    seen = 0
    root_depth = len(root.resolve().parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).resolve().parts) - root_depth
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        if depth >= max_depth:
            dirnames[:] = []
        for filename in filenames:
            seen += 1
            if seen > max_files:
                return _sort(candidates)
            lower = filename.lower()
            if lower.endswith(PY_EXT):
                kind = "python"
            elif lower.endswith(JS_EXT):
                kind = "node"
            else:
                continue
            path = Path(dirpath) / filename
            head = read_head(path)
            if not TELEGRAM_MARKERS.search(head):
                continue
            candidates.append(
                Candidate(
                    kind=kind,
                    script=str(path.resolve()),
                    name=guess_name(str(path)),
                    likely_entry=bool(ENTRY_MARKERS.search(head)),
                )
            )
    return _sort(candidates)


def _sort(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda c: (not c.likely_entry, c.script.lower()))
