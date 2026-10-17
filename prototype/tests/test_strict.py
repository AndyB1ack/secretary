from pathlib import Path

from secretary.conversation import Conversation
from secretary.events import EventBus
from secretary.knowledge import Hit
from secretary.persona import Persona

CARD = Path(__file__).resolve().parents[2] / "persona" / "mira.yaml"


class SeqLLM:
    def __init__(self, *answers):
        self.answers = list(answers)

    def stream_chat(self, messages, temperature=None):
        yield self.answers.pop(0)


class FakeKB:
    empty = False

    def describe(self):
        return "пакет"

    def search(self, q):
        return [Hit("text", 0.9, "Инструкция", 12, "Код 21: проверка тормоза")]


def test_bad_citation_is_retried_then_falls_back_to_quote():
    c = Conversation(Persona.load(CARD), SeqLLM("Смотри стр. 99.", "Это на странице 77."), EventBus(), kb=FakeKB())
    out = " ".join(c.respond("Что значит код 21?"))
    assert "дословно" in out and "стр. 12" in out


def test_good_citation_passes():
    c = Conversation(Persona.load(CARD), SeqLLM("Код 21 — проверка тормоза, стр. 12."), EventBus(), kb=FakeKB())
    assert "стр. 12" in " ".join(c.respond("Код 21?"))
