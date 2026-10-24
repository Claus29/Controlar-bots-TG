"""Librerías (dependencias) de cada bot: detección, instalación y entornos aislados.

Cada bot usa sus propias librerías en *su* intérprete (Python o Node). BotControl
nunca las mete dentro de sí mismo: las instala en el Python/carpeta del bot.
"""

from __future__ import annotations

import ast
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from botcontrol.launcher import IS_WINDOWS, LaunchError, build_env, resolve_interpreter
from botcontrol.models import BotConfig
from botcontrol.proc_utils import run_capture, run_streaming
from botcontrol.scanner import SKIP_DIRS

LineCallback = Callable[[str], None] | None

# Nombre con el que se importa -> nombre del paquete en PyPI (sólo los que difieren).
PIP_NAMES = {
    "cv2": "opencv-python", "PIL": "Pillow", "yaml": "PyYAML", "dotenv": "python-dotenv",
    "telegram": "python-telegram-bot", "telebot": "pyTelegramBotAPI", "sklearn": "scikit-learn",
    "skimage": "scikit-image", "bs4": "beautifulsoup4", "dateutil": "python-dateutil",
    "Crypto": "pycryptodome", "Cryptodome": "pycryptodomex", "jwt": "PyJWT", "magic": "python-magic",
    "docx": "python-docx", "pptx": "python-pptx", "fitz": "PyMuPDF", "serial": "pyserial", "usb": "pyusb",
    "win32api": "pywin32", "win32con": "pywin32", "win32gui": "pywin32", "win32com": "pywin32",
    "pywintypes": "pywin32", "pythoncom": "pywin32", "OpenSSL": "pyOpenSSL",
    "googleapiclient": "google-api-python-client", "dns": "dnspython", "gi": "PyGObject", "attr": "attrs",
    "MySQLdb": "mysqlclient", "psycopg2": "psycopg2-binary", "discord": "discord.py", "nacl": "PyNaCl",
    "Levenshtein": "python-Levenshtein", "speech_recognition": "SpeechRecognition", "socks": "PySocks",
    "ffmpeg": "ffmpeg-python", "websocket": "websocket-client", "apscheduler": "APScheduler",
    "tgcrypto": "TgCrypto", "gtts": "gTTS", "yt_dlp": "yt-dlp", "deep_translator": "deep-translator",
    "sqlalchemy": "SQLAlchemy", "flask": "Flask", "xlsxwriter": "XlsxWriter", "markdown": "Markdown",
    "jinja2": "Jinja2", "decouple": "python-decouple", "babel": "Babel", "telethon": "Telethon",
    "openai": "openai", "anthropic": "anthropic", "pyrogram": "pyrogram", "aiogram": "aiogram",
    "mpl_toolkits": "matplotlib", "pkg_resources": "setuptools", "dotmap": "dotmap",
    "Bio": "biopython", "kivy": "Kivy", "pygame": "pygame", "wx": "wxPython", "zmq": "pyzmq",
    "jose": "python-jose", "multipart": "python-multipart", "slugify": "python-slugify",
    "telegraph": "telegraph", "pymysql": "PyMySQL", "pydantic_settings": "pydantic-settings",
    "google_auth_oauthlib": "google-auth-oauthlib", "fake_useragent": "fake-useragent",
    "dateparser": "dateparser", "imageio_ffmpeg": "imageio-ffmpeg", "moviepy": "moviepy",
}

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PY_MISSING = re.compile(r"(?:ModuleNotFoundError|ImportError): No module named ['\"]?([A-Za-z_][\w.]*)['\"]?")
NODE_MISSING = re.compile(r"Cannot find module '([^']+)'")
PROBE_INFO = (
    "import sys, json; print(json.dumps({'version': sys.version.split()[0], 'executable': sys.executable,"
    " 'prefix': sys.prefix, 'base_prefix': getattr(sys, 'base_prefix', sys.prefix)}))"
)
PROBE_MISSING = (
    "import sys, json, importlib.util\n"
    "data = json.loads(sys.stdin.read())\n"
    "sys.path.insert(0, data['path'])\n"
    "missing = []\n"
    "for name in data['modules']:\n"
    "    try:\n"
    "        if importlib.util.find_spec(name) is None:\n"
    "            missing.append(name)\n"
    "    except (ImportError, ValueError):\n"
    "        missing.append(name)\n"
    "    except Exception:\n"
    "        pass\n"
    "print(json.dumps(missing))\n"
)


class DepsError(Exception):
    """Error comprensible al gestionar librerías."""


@dataclass
class ImportInfo:
    optional: bool = True
    files: set[str] = field(default_factory=set)


@dataclass
class MissingItem:
    module: str
    package: str
    optional: bool
    files: list[str]


@dataclass
class PythonInstall:
    path: str
    version: str

    @property
    def label(self) -> str:
        return f"Python {self.version} — {self.path}"


# --------------------------------------------------------------- utilidades
def pip_name(module: str) -> str:
    top = module.split(".")[0]
    return PIP_NAMES.get(top, top)


def bot_folder(bot: BotConfig) -> Path:
    if bot.kind in ("python", "node") and bot.target.strip():
        return Path(bot.target.strip()).parent
    return Path(bot.workdir.strip() or ".")


def manifest_file(bot: BotConfig) -> Path | None:
    """``requirements.txt`` (Python) o ``package.json`` (Node) del bot, si existe."""
    if bot.kind not in ("python", "node"):
        return None
    name = "requirements.txt" if bot.kind == "python" else "package.json"
    for folder in dict.fromkeys([bot_folder(bot), Path(bot.workdir.strip()) if bot.workdir.strip() else None]):
        if folder is not None and (folder / name).is_file():
            return folder / name
    return None


def pip_env(bot: BotConfig) -> dict[str, str]:
    env = build_env(bot)
    env.update({"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1", "PIP_NO_WARN_SCRIPT_LOCATION": "1"})
    return env


def fingerprint(bot: BotConfig) -> str:
    """Huella de lo que hay que tener instalado. Vacía si no hay nada que gestionar."""
    manifest = manifest_file(bot)
    if manifest is None and not bot.extra_packages:
        return ""
    digest = hashlib.sha256()
    try:
        digest.update(" ".join(resolve_interpreter(bot)).encode())
    except LaunchError:
        return ""
    if manifest is not None:
        try:
            digest.update(manifest.read_bytes())
        except OSError:
            pass
    digest.update("\n".join(sorted(bot.extra_packages)).encode())
    return digest.hexdigest()[:16]


def needs_sync(bot: BotConfig) -> bool:
    if not bot.auto_install or bot.kind not in ("python", "node"):
        return False
    current = fingerprint(bot)
    if not current:
        return False
    if bot.kind == "node" and manifest_file(bot) and not (manifest_file(bot).parent / "node_modules").is_dir():
        return True
    return current != bot.deps_hash


def missing_module_from_log(text: str, kind: str) -> str | None:
    """Nombre del módulo que falta según el error que imprimió el bot (el último)."""
    text = ANSI.sub("", text)
    if kind == "python":
        found = PY_MISSING.findall(text)
        return found[-1].split(".")[0] if found else None
    if kind == "node":
        for name in reversed(NODE_MISSING.findall(text)):
            if name.startswith((".", "/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", name) or name.startswith("node:"):
                continue
            parts = name.split("/")
            return "/".join(parts[:2]) if name.startswith("@") else parts[0]
    return None


def local_module_names(folder: Path, max_files: int = 5000) -> set[str]:
    """Módulos propios del bot (archivos .py y carpetas): no se instalan desde PyPI."""
    names: set[str] = set()
    count = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        names.update(dirnames)
        for filename in filenames:
            count += 1
            if count > max_files:
                return names
            if filename.endswith((".py", ".pyw", ".pyd", ".so")):
                names.add(filename.split(".")[0])
    return names


def is_local_module(bot: BotConfig, module: str) -> bool:
    return bot.kind == "python" and module in local_module_names(bot_folder(bot))


# --------------------------------------------------------- análisis imports
def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    names = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
    kind = handler.type
    if kind is None:
        return True
    if isinstance(kind, ast.Name):
        return kind.id in names
    if isinstance(kind, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in names for e in kind.elts)
    return False


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: dict[str, bool] = {}  # módulo -> ¿todas sus apariciones son opcionales?
        self._optional = 0

    def visit_Try(self, node):  # noqa: N802
        guarded = any(_catches_import_error(h) for h in node.handlers)
        self._optional += guarded
        for child in node.body:
            self.visit(child)
        self._optional -= guarded
        for child in [*node.handlers, *node.orelse, *node.finalbody]:
            self.visit(child)

    visit_TryStar = visit_Try  # noqa: N815

    def _add(self, name: str) -> None:
        optional = self._optional > 0
        self.found[name] = self.found.get(name, True) and optional

    def visit_Import(self, node):  # noqa: N802
        for alias in node.names:
            self._add(alias.name.split(".")[0])

    def visit_ImportFrom(self, node):  # noqa: N802
        if node.level == 0 and node.module:
            self._add(node.module.split(".")[0])


def scan_imports(folder: Path, max_files: int = 2000) -> dict[str, ImportInfo]:
    """Imports de primer nivel de todos los .py del bot (sin ejecutar nada)."""
    result: dict[str, ImportInfo] = {}
    count = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith((".py", ".pyw")):
                continue
            count += 1
            if count > max_files:
                break
            path = Path(dirpath) / filename
            try:
                tree = ast.parse(path.read_bytes(), filename=str(path))
            except (SyntaxError, ValueError, OSError):
                continue
            visitor = _ImportVisitor()
            visitor.visit(tree)
            rel = str(path.relative_to(folder))
            for name, optional in visitor.found.items():
                info = result.setdefault(name, ImportInfo())
                info.optional = info.optional and optional
                info.files.add(rel)
    local = local_module_names(folder)
    for name in list(result):
        if name in local or name == "__future__":
            del result[name]
    return result


# ------------------------------------------------------------ intérpretes
def interpreter_info(interp: list[str], env: dict[str, str] | None = None) -> dict:
    code, out = run_capture([*interp, "-c", PROBE_INFO], env=env, timeout=20)
    if code != 0:
        raise DepsError(f"No se pudo ejecutar el intérprete {' '.join(interp)}:\n{out.strip()[-500:]}")
    try:
        info = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise DepsError(f"Respuesta inesperada del intérprete: {out[-300:]}") from exc
    info["is_venv"] = os.path.normcase(info["prefix"]) != os.path.normcase(info["base_prefix"])
    return info


def find_missing(interp: list[str], modules: list[str], path: str, env: dict[str, str] | None = None) -> list[str]:
    if not modules:
        return []
    payload = json.dumps({"modules": sorted(modules), "path": path})
    code, out = run_capture([*interp, "-c", PROBE_MISSING], cwd=path or None, env=env,
                            input_text=payload, timeout=60)
    if code != 0:
        raise DepsError(f"No se pudo comprobar las librerías:\n{out.strip()[-500:]}")
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise DepsError(f"Respuesta inesperada al comprobar librerías: {out[-300:]}") from exc


def analyze(bot: BotConfig) -> list[MissingItem]:
    """Librerías que usa el bot y que faltan en su Python."""
    if bot.kind != "python":
        raise DepsError("El análisis de imports sólo está disponible para bots de Python.")
    interp = resolve_interpreter(bot)
    folder = bot_folder(bot)
    imports = scan_imports(folder)
    missing = find_missing(interp, list(imports), str(folder), pip_env(bot))
    items = [MissingItem(m, pip_name(m), imports[m].optional, sorted(imports[m].files)) for m in missing]
    return sorted(items, key=lambda i: (i.optional, i.module.lower()))


def _python_candidates() -> list[str]:
    paths: list[str] = []
    if IS_WINDOWS:
        launcher = shutil.which("py")
        if launcher:
            code, out = run_capture([launcher, "-0p"], timeout=10)
            if code == 0:
                paths += re.findall(r"([A-Za-z]:\\[^\r\n]*?\.exe)\s*$", out, re.MULTILINE)
        for base in filter(None, [os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"),
                                  os.environ.get("ProgramFiles(x86)")]):
            paths += glob.glob(os.path.join(base, "Programs", "Python", "Python3*", "python.exe"))
            paths += glob.glob(os.path.join(base, "Python3*", "python.exe"))
        paths += glob.glob(r"C:\Python3*\python.exe")
        for name in ("python", "python3"):
            found = shutil.which(name)
            if found and "windowsapps" not in found.lower():
                paths.append(found)
    else:
        for name in ("python3", "python"):
            found = shutil.which(name)
            if found:
                paths.append(found)
        paths += sorted(glob.glob("/usr/bin/python3.[0-9]*")) + sorted(glob.glob("/usr/local/bin/python3.[0-9]*"))
    if not getattr(sys, "frozen", False):
        paths.append(sys.executable)
    return list(dict.fromkeys(paths))


def find_pythons() -> list[PythonInstall]:
    """Pythons instalados en el sistema (se comprueba que funcionan)."""
    result: list[PythonInstall] = []
    seen: set[str] = set()
    for path in _python_candidates():
        if path.lower().endswith(("-config", ".py")):
            continue
        code, out = run_capture([path, "-c", "import sys; print(sys.version.split()[0]); print(sys.executable)"],
                                timeout=10)
        lines = out.strip().splitlines()
        if code != 0 or len(lines) < 2:
            continue
        key = os.path.normcase(os.path.realpath(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(PythonInstall(path=path, version=lines[-2].strip()))
    return result


# -------------------------------------------------------------- pip / npm
def ensure_pip(interp: list[str], env: dict[str, str], on_line: LineCallback = None,
               cancel: threading.Event | None = None) -> None:
    code, _ = run_capture([*interp, "-m", "pip", "--version"], env=env, timeout=60)
    if code == 0:
        return
    if on_line:
        on_line("pip no está disponible en este Python; instalándolo con ensurepip…")
    run_streaming([*interp, "-m", "ensurepip", "--upgrade"], None, env, on_line, cancel)
    code, out = run_capture([*interp, "-m", "pip", "--version"], env=env, timeout=60)
    if code != 0:
        raise DepsError("Este Python no tiene pip y no se pudo instalar. Reinstala Python marcando «pip».")


def pip_install(interp: list[str], env: dict[str, str], packages: list[str] | tuple = (),
                requirements: Path | None = None, cwd: str | None = None, on_line: LineCallback = None,
                cancel: threading.Event | None = None, upgrade: bool = False) -> None:
    if not packages and requirements is None:
        return
    ensure_pip(interp, env, on_line, cancel)
    command = [*interp, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    if upgrade:
        command.append("--upgrade")
    if requirements is not None:
        command += ["-r", str(requirements)]
    command += list(packages)
    if on_line:
        on_line("$ " + " ".join(command))
    if run_streaming(command, cwd, env, on_line, cancel) != 0:
        what = ", ".join(packages) if packages else requirements.name
        raise DepsError(f"pip no pudo instalar {what}. Revisa el nombre del paquete y tu conexión a Internet.")


def pip_uninstall(interp: list[str], env: dict[str, str], packages: list[str], on_line: LineCallback = None,
                  cancel: threading.Event | None = None) -> None:
    command = [*interp, "-m", "pip", "uninstall", "-y", *packages]
    if on_line:
        on_line("$ " + " ".join(command))
    if run_streaming(command, None, env, on_line, cancel) != 0:
        raise DepsError(f"No se pudo desinstalar {', '.join(packages)}.")


def pip_list(interp: list[str], env: dict[str, str]) -> list[tuple[str, str]]:
    code, out = run_capture([*interp, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                            env=env, timeout=90)
    if code != 0:
        raise DepsError("No se pudo obtener la lista de paquetes (¿tiene pip este Python?).")
    for line in reversed(out.strip().splitlines()):
        if line.startswith("["):
            return sorted(((p["name"], p["version"]) for p in json.loads(line)), key=lambda p: p[0].lower())
    return []


def npm_command() -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        raise DepsError("No se encontró npm (se instala junto con Node.js).")
    return [npm]


def npm_install(folder: Path, env: dict[str, str], packages: list[str] | tuple = (), on_line: LineCallback = None,
                cancel: threading.Event | None = None) -> None:
    command = [*npm_command(), "install", "--no-fund", "--no-audit", *packages]
    if on_line:
        on_line("$ " + " ".join(command))
    if run_streaming(command, str(folder), env, on_line, cancel) != 0:
        raise DepsError("npm no pudo instalar las librerías.")


# --------------------------------------------------------- operaciones bot
def sync(bot: BotConfig, on_line: LineCallback = None, cancel: threading.Event | None = None) -> str:
    """Instala ``requirements.txt``/``package.json`` y las librerías adicionales. Devuelve la nueva huella."""
    env = pip_env(bot)
    manifest = manifest_file(bot)
    if bot.kind == "python":
        interp = resolve_interpreter(bot)
        pip_install(interp, env, requirements=manifest, cwd=str(bot_folder(bot)), on_line=on_line, cancel=cancel)
        pip_install(interp, env, bot.extra_packages, on_line=on_line, cancel=cancel)
    elif bot.kind == "node":
        folder = manifest.parent if manifest else bot_folder(bot)
        if manifest:
            npm_install(folder, env, on_line=on_line, cancel=cancel)
        if bot.extra_packages:
            npm_install(folder, env, bot.extra_packages, on_line=on_line, cancel=cancel)
    return fingerprint(bot)


def install_missing(bot: BotConfig, module: str, on_line: LineCallback = None,
                    cancel: threading.Event | None = None) -> str:
    """Instala la librería que falta. Devuelve el nombre del paquete instalado."""
    env = pip_env(bot)
    if bot.kind == "python":
        package = pip_name(module)
        pip_install(resolve_interpreter(bot), env, [package], on_line=on_line, cancel=cancel)
        return package
    if bot.kind == "node":
        npm_install(bot_folder(bot), env, [module], on_line=on_line, cancel=cancel)
        return module
    raise DepsError("Este tipo de bot no admite instalación de librerías.")


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def isolated_env_path(bot: BotConfig, data_dir: Path) -> Path:
    """Dónde crear el entorno aislado: ``.venv`` junto al bot, o en los datos de BotControl."""
    folder = bot_folder(bot)
    if os.access(folder, os.W_OK):
        return folder / ".venv"
    return data_dir / "envs" / bot.id


def create_isolated_env(bot: BotConfig, data_dir: Path, base: list[str] | None = None,
                        include: list[str] | tuple = (), on_line: LineCallback = None,
                        cancel: threading.Event | None = None) -> Path:
    """Crea (o reutiliza) un venv propio del bot e instala todo lo que necesita.

    Devuelve la ruta del ``python`` del entorno; hay que guardarla en ``bot.interpreter``.
    """
    if bot.kind != "python":
        raise DepsError("Los entornos aislados son para bots de Python (Node ya instala por carpeta).")
    target = isolated_env_path(bot, data_dir)
    python = venv_python(target)
    env = pip_env(bot)
    if not python.is_file():
        base = base or resolve_interpreter(bot)
        target.parent.mkdir(parents=True, exist_ok=True)
        if on_line:
            on_line(f"Creando entorno aislado en {target} …")
        if run_streaming([*base, "-m", "venv", str(target)], None, env, on_line, cancel) != 0 or not python.is_file():
            raise DepsError("No se pudo crear el entorno aislado (venv).")
    elif on_line:
        on_line(f"Usando el entorno aislado existente: {target}")
    isolated = BotConfig.from_dict({**bot.to_dict(), "interpreter": str(python)})
    interp = [str(python)]
    pip_install(interp, env, requirements=manifest_file(isolated), cwd=str(bot_folder(bot)),
                on_line=on_line, cancel=cancel)
    packages = list(dict.fromkeys([*isolated.extra_packages, *include]))
    if packages:
        pip_install(interp, env, packages, on_line=on_line, cancel=cancel)
    # Lo que use el código del bot y aún falte (salvo imports opcionales).
    try:
        missing = [i.package for i in analyze(isolated) if not i.optional]
    except (DepsError, LaunchError) as exc:
        missing = []
        if on_line:
            on_line(f"Aviso: no se pudo analizar el código del bot: {exc}")
    if missing:
        if on_line:
            on_line("Librerías que usa el código del bot: " + ", ".join(missing))
        pip_install(interp, env, list(dict.fromkeys(missing)), on_line=on_line, cancel=cancel)
    return python
