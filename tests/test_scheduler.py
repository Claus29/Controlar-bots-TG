from datetime import datetime

import pytest

from botcontrol.models import BotConfig, Schedule
from botcontrol.scheduler import ScheduleTracker, in_window, parse_hhmm

MON = datetime(2026, 10, 19)  # lunes


def at(day_offset, hh, mm=0):
    return MON.replace(day=MON.day + day_offset, hour=hh, minute=mm)


def test_parse():
    assert parse_hhmm("08:30") == 510
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


def test_simple_window():
    s = Schedule(enabled=True, days=[0], start="09:00", stop="17:00")
    assert in_window(s, at(0, 9))
    assert not in_window(s, at(0, 17))
    assert not in_window(s, at(1, 10))


def test_overnight_window():
    s = Schedule(enabled=True, days=[0], start="22:00", stop="06:00")
    assert in_window(s, at(0, 23))
    assert in_window(s, at(1, 3))  # madrugada del martes pertenece al lunes
    assert not in_window(s, at(1, 23))
    assert not in_window(s, at(0, 3))


def test_tracker_only_acts_on_transitions():
    bot = BotConfig(name="x", schedule=Schedule(enabled=True, days=list(range(7)), start="09:00", stop="10:00"))
    tracker = ScheduleTracker()
    assert tracker.evaluate([bot], at(0, 8)) == []
    assert tracker.evaluate([bot], at(0, 9)) == [(bot.id, "start")]
    assert tracker.evaluate([bot], at(0, 9, 30)) == []
    assert tracker.evaluate([bot], at(0, 10)) == [(bot.id, "stop")]
    fresh = ScheduleTracker()
    assert fresh.evaluate([bot], at(0, 9, 15)) == [(bot.id, "start")]
