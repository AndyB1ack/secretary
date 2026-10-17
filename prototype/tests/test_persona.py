from pathlib import Path

from secretary.persona import Persona

CARD = Path(__file__).resolve().parents[2] / "persona" / "mira.yaml"


def test_prompt_contains_character_and_mode():
    p = Persona.load(CARD)
    prompt = p.system_prompt("work")
    assert "Мира" in prompt and "собранная" in prompt and "Андрей" in prompt


def test_tutor_layer():
    p = Persona.load(CARD)
    p.tutor = {"language": "he"}
    assert "иврите" in p.system_prompt("evening")
