from datetime import date, datetime
from pathlib import Path

from secretary.persona import Persona, day_phase

P = Path(__file__).resolve().parents[2] / "persona" / "mira.yaml"


def test_life_topics_found():
    p = Persona.load(P)
    assert "Ирина" in p.life_for("расскажи про маму")
    assert "Тёма" in p.life_for("у тебя есть брат?")
    assert p.life_for("какие задачи на сегодня") == ""


def test_identity_in_prompt():
    p = Persona.load(P)
    assert "Одесс" in p.system_prompt("work", compact=True)


def test_day_rhythm():
    sunday = datetime(2026, 10, 18, 6, 0)
    first = day_phase(1, "work", sunday, date(2026, 10, 16), False)
    assert "выходн" in first and "НЕ спрашивай" in first
    assert "задачи на сегодня" in day_phase(3, "work", sunday, date(2026, 10, 16), False)
    assert day_phase(1, "work", sunday, None, True) == ""          # сам начал с дела
    assert day_phase(1, "private", sunday, None, False) == ""
    assert "несколько дней" in day_phase(1, "work", datetime(2026, 10, 20, 6), date(2026, 10, 14), False)
