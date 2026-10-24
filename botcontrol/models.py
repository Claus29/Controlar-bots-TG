"""Modelos de configuración: bots, programación y ajustes."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

KINDS = {
    "python": "Python",
    "node": "Node.js",
    "exe": "Ejecutable",
    "command": "Comando",
}

DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _filter_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Schedule:
    """Franja horaria en la que el bot debe estar en marcha."""

    enabled: bool = False
    days: list[int] = field(default_factory=lambda: list(range(7)))  # 0 = lunes
    start: str = "08:00"
    stop: str = "23:00"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Schedule":
        if not data:
            return cls()
        sched = cls(**_filter_kwargs(cls, data))
        sched.days = sorted({int(d) for d in sched.days if 0 <= int(d) <= 6})
        return sched

    def describe(self) -> str:
        if not self.enabled:
            return "—"
        if len(self.days) == 7:
            days = "Todos los días"
        elif self.days == [0, 1, 2, 3, 4]:
            days = "Lun-Vie"
        elif self.days == [5, 6]:
            days = "Fin de semana"
        elif not self.days:
            days = "Ningún día"
        else:
            days = ",".join(DAY_NAMES[d] for d in self.days)
        return f"{days} {self.start}-{self.stop}"


@dataclass
class BotConfig:
    name: str
    kind: str = "python"
    target: str = ""  # script, ejecutable o comando
    args: str = ""
    workdir: str = ""
    interpreter: str = ""  # vacío = autodetectar
    env: dict[str, str] = field(default_factory=dict)
    token_enc: str = ""  # token cifrado (ver secrets.py)
    token_env: str = "BOT_TOKEN"
    inject_token: bool = False
    username: str = ""  # @usuario devuelto por getMe
    autostart: bool = False
    start_delay: int = 0
    auto_restart: bool = True
    max_restarts: int = 5
    restart_window: int = 600  # segundos
    schedule: Schedule = field(default_factory=Schedule)
    auto_install: bool = True  # instalar requirements/librerías que falten automáticamente
    extra_packages: list[str] = field(default_factory=list)  # librerías adicionales (sintaxis pip/npm)
    deps_hash: str = ""  # huella de la última instalación correcta de librerías
    notes: str = ""
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BotConfig":
        data = dict(data)
        schedule = Schedule.from_dict(data.pop("schedule", None))
        bot = cls(**_filter_kwargs(cls, data))
        bot.schedule = schedule
        bot.env = {str(k): str(v) for k, v in (bot.env or {}).items()}
        bot.extra_packages = [str(p).strip() for p in (bot.extra_packages or []) if str(p).strip()]
        if bot.kind not in KINDS:
            bot.kind = "python"
        if not bot.id:
            bot.id = new_id()
        return bot

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EXIT_ASK = "ask"
EXIT_STOP = "stop"
EXIT_LEAVE = "leave"


@dataclass
class AppSettings:
    minimize_to_tray: bool = True
    start_minimized_on_boot: bool = True
    wait_for_internet: bool = True
    internet_timeout: int = 90
    notify_crash: bool = True
    exit_action: str = EXIT_ASK
    max_log_mb: int = 5
    tray_hint_shown: bool = False
    window_geometry: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppSettings":
        settings = cls(**_filter_kwargs(cls, data or {}))
        if settings.exit_action not in (EXIT_ASK, EXIT_STOP, EXIT_LEAVE):
            settings.exit_action = EXIT_ASK
        return settings


@dataclass
class AppConfig:
    bots: list[BotConfig] = field(default_factory=list)
    settings: AppSettings = field(default_factory=AppSettings)

    def get(self, bot_id: str) -> BotConfig | None:
        for bot in self.bots:
            if bot.id == bot_id:
                return bot
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "bots": [b.to_dict() for b in self.bots],
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        bots = []
        seen: set[str] = set()
        for raw in data.get("bots", []):
            if not isinstance(raw, dict) or not raw.get("name"):
                continue
            bot = BotConfig.from_dict(raw)
            if bot.id in seen:
                bot.id = new_id()
            seen.add(bot.id)
            bots.append(bot)
        return cls(bots=bots, settings=AppSettings.from_dict(data.get("settings")))
