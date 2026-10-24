"""Llamadas mínimas a la API de Telegram."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

API = "https://api.telegram.org"


class TelegramError(Exception):
    pass


def get_me(token: str, timeout: float = 10) -> dict:
    """Devuelve la información del bot (``id``, ``username``, ``first_name``...)."""
    token = token.strip()
    if not token or ":" not in token:
        raise TelegramError("El token no tiene un formato válido (123456:ABC...).")
    url = f"{API}/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 404):
            raise TelegramError("Telegram rechaza el token (no válido o revocado).") from exc
        raise TelegramError(f"Error HTTP {exc.code} de Telegram.") from exc
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        raise TelegramError(f"No se pudo conectar con Telegram: {exc}") from exc
    except ValueError as exc:
        raise TelegramError("Respuesta no válida de Telegram.") from exc
    if not data.get("ok"):
        raise TelegramError(data.get("description") or "Telegram devolvió un error.")
    return data["result"]


def internet_available(host: str = "api.telegram.org", port: int = 443, timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_internet(max_seconds: float, should_abort=lambda: False) -> bool:
    deadline = time.monotonic() + max_seconds
    while True:
        if internet_available():
            return True
        if should_abort() or time.monotonic() >= deadline:
            return False
        time.sleep(2)
