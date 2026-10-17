import random
from datetime import date, timedelta

from secretary.memory import Memory, consolidate, parse_json
from secretary.mood import mood_for_today


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def stream_chat(self, messages):
        yield self.text


def test_scopes_and_tasks(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.add_fact("На объекте в Холоне лифт KONE", "work")
    m.add_fact("Секретное приватное", "private")
    assert m.facts("work") == ["На объекте в Холоне лифт KONE"]
    assert len(m.facts("private")) == 2
    t = m.add_task("Позвонить прорабу", "2026-10-20")
    assert m.add_task("Позвонить прорабу") == t  # без дублей
    assert "Позвонить прорабу" in m.context_block("work")
    assert m.complete_task(t) and not m.open_tasks()


def test_consolidate(tmp_path):
    m = Memory(tmp_path / "m.db")
    for role, text in [("user", "Завтра едем в Бат-Ям ставить KONE"), ("assistant", "Записала!"),
                       ("user", "Напомни взять ключи от шахты"), ("assistant", "Напомню.")]:
        m.add_message("work", role, text)
    llm = FakeLLM('Вот: {"summary": "Планировали Бат-Ям", "facts": ["Объект в Бат-Яме, лифт KONE"], '
                  '"tasks": [{"title": "Взять ключи от шахты", "due": null}]}')
    data = consolidate(m, llm)
    assert data["summary"] == "Планировали Бат-Ям"
    assert m.facts("work") == ["Объект в Бат-Яме, лифт KONE"]
    assert m.open_tasks()[0]["title"] == "Взять ключи от шахты"
    assert m.unsummarized_sessions() == []
    assert "Планировали Бат-Ям" in m.context_block("work")


def test_private_episode_hidden_at_work(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.add_episode("20261017-120000", "private", "приватный вечер")
    assert "приватный" not in m.context_block("work")
    assert "приватный" in m.context_block("private")


def test_parse_json_garbage():
    assert parse_json("нет json") is None


def test_mood_sulks_after_gap(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.db.execute("INSERT INTO messages (ts, session, mode, scope, role, content) VALUES (?,?,?,?,?,?)",
                 ((date.today() - timedelta(days=4)).isoformat() + "T10:00:00", "old", "work", "work", "user", "hi"))
    m.db.commit()
    state, _ = mood_for_today(m, random.Random(1))
    assert state == "немного обиженное"
    assert mood_for_today(m)[0] == state  # в течение дня не меняется
