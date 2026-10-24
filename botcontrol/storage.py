"""Lectura y escritura atómica de la configuración."""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from botcontrol.models import AppConfig

log = logging.getLogger(__name__)


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
        log.error("No se pudo leer %s (%s); copia en %s", path, exc, backup)
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass
        return default


def load_config(path: Path) -> AppConfig:
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    return AppConfig.from_dict(data)


def save_config(config: AppConfig, path: Path) -> None:
    write_json_atomic(path, config.to_dict())


def export_config(config: AppConfig, path: Path) -> None:
    """Exporta los bots sin tokens (los tokens cifrados no sirven en otro PC)."""
    data = config.to_dict()
    for bot in data["bots"]:
        bot["token_enc"] = ""
    data.pop("settings", None)
    write_json_atomic(path, data)


def import_bots(path: Path) -> list:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("El archivo no tiene el formato de BotControl")
    return AppConfig.from_dict(data).bots
