from botcontrol import secrets
from botcontrol.models import AppConfig, BotConfig, Schedule
from botcontrol.storage import export_config, import_bots, load_config, save_config


def test_roundtrip(tmp_path):
    cfg = AppConfig(bots=[BotConfig(name="A", target="a.py", env={"X": "1"},
                                    schedule=Schedule(enabled=True, days=[0, 2], start="09:00", stop="18:00"))])
    path = tmp_path / "config.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.bots[0].name == "A"
    assert loaded.bots[0].env == {"X": "1"}
    assert loaded.bots[0].schedule.days == [0, 2]
    assert loaded.bots[0].id == cfg.bots[0].id


def test_tolerates_unknown_and_corrupt(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path).bots == []
    assert list(tmp_path.glob("config.corrupt-*.json"))
    cfg = AppConfig.from_dict({"bots": [{"name": "B", "unknown": 1, "kind": "weird"}, {"nope": 1}],
                               "settings": {"exit_action": "bad"}})
    assert len(cfg.bots) == 1 and cfg.bots[0].kind == "python"
    assert cfg.settings.exit_action == "ask"


def test_export_strips_tokens(tmp_path):
    cfg = AppConfig(bots=[BotConfig(name="A", token_enc=secrets.protect("1:abc"))])
    path = tmp_path / "export.json"
    export_config(cfg, path)
    bots = import_bots(path)
    assert bots[0].name == "A" and bots[0].token_enc == ""


def test_secrets_roundtrip():
    enc = secrets.protect(" 123:ABC ")
    assert enc and "123:ABC" not in enc
    assert secrets.unprotect(enc) == "123:ABC"
    assert secrets.protect("") == ""
    assert secrets.unprotect("garbage") == ""


def test_schedule_describe():
    assert Schedule().describe() == "—"
    assert Schedule(enabled=True, days=[0, 1, 2, 3, 4]).describe().startswith("Lun-Vie")
