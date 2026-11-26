from pathlib import Path

from backend.envfile import load_env, parse

ROOT = Path(__file__).resolve().parents[1]


def test_parse_handles_comments_quotes_and_export():
    d = parse('# c\nA=1\nexport B = "two words"\nC=x # note\nEMPTY=\nnot a line\n')
    assert d == {"A": "1", "B": "two words", "C": "x", "EMPTY": ""}


def test_shell_wins_and_empty_values_are_skipped(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("HP_TEST_A=from_file\nHP_TEST_B=from_file\nHP_TEST_C=\n")
    monkeypatch.setenv("HP_TEST_A", "from_shell")
    monkeypatch.delenv("HP_TEST_B", raising=False)
    monkeypatch.delenv("HP_TEST_C", raising=False)
    done = load_env(f, force=True)
    import os
    assert os.environ["HP_TEST_A"] == "from_shell" and os.environ["HP_TEST_B"] == "from_file"
    assert "HP_TEST_C" not in os.environ and done == {"HP_TEST_B": "from_file"}
    monkeypatch.delenv("HP_TEST_B")


def test_not_loaded_under_pytest(tmp_path):
    f = tmp_path / ".env"
    f.write_text("HP_TEST_D=1\n")
    assert load_env(f) == {}


def test_env_example_lists_every_setting_and_no_secret():
    d = parse((ROOT / ".env.example").read_text(encoding="utf-8"))
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "HYDROPIN_NOTIFY", "HYDROPIN_MQTT", "HYDROPIN_DB"):
        assert k in d
    assert d["TELEGRAM_BOT_TOKEN"] == "" and d["TELEGRAM_CHAT_ID"] == ""
