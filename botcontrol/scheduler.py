"""Programación horaria de bots."""

from __future__ import annotations

from datetime import datetime

from botcontrol.models import BotConfig, Schedule


def parse_hhmm(value: str) -> int:
    """Convierte "HH:MM" en minutos desde medianoche."""
    try:
        hours, minutes = value.strip().split(":")
        h, m = int(hours), int(minutes)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Hora no válida: {value!r}") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Hora no válida: {value!r}")
    return h * 60 + m


def in_window(schedule: Schedule, now: datetime) -> bool:
    """¿Debe estar el bot en marcha en ``now`` según su programación?"""
    start, stop = parse_hhmm(schedule.start), parse_hhmm(schedule.stop)
    minute = now.hour * 60 + now.minute
    day = now.weekday()
    if start == stop:
        return day in schedule.days
    if start < stop:
        return day in schedule.days and start <= minute < stop
    # Franja que cruza la medianoche (p. ej. 22:00-06:00): la parte de la
    # madrugada pertenece al día en que empezó la franja.
    if minute >= start:
        return day in schedule.days
    if minute < stop:
        return (day - 1) % 7 in schedule.days
    return False


class ScheduleTracker:
    """Detecta los cambios de franja para actuar sólo en las transiciones.

    Así, si el usuario detiene a mano un bot dentro de su franja, no se
    vuelve a arrancar hasta la siguiente franja.
    """

    def __init__(self) -> None:
        self._previous: dict[str, bool] = {}

    def forget(self, bot_id: str) -> None:
        self._previous.pop(bot_id, None)

    def evaluate(self, bots: list[BotConfig], now: datetime) -> list[tuple[str, str]]:
        actions: list[tuple[str, str]] = []
        active_ids = set()
        for bot in bots:
            if not bot.schedule.enabled:
                self._previous.pop(bot.id, None)
                continue
            active_ids.add(bot.id)
            try:
                should_run = in_window(bot.schedule, now)
            except ValueError:
                continue
            previous = self._previous.get(bot.id)
            self._previous[bot.id] = should_run
            if previous is None:
                if should_run:
                    actions.append((bot.id, "start"))
            elif previous != should_run:
                actions.append((bot.id, "start" if should_run else "stop"))
        for stale in set(self._previous) - active_ids:
            del self._previous[stale]
        return actions
