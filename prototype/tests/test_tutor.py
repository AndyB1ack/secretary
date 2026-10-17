import sqlite3

from secretary.tutor import Tutor, plain


def test_pick_and_review():
    t = Tutor(sqlite3.connect(":memory:"))
    assert t.course["terms"], "курс должен загрузиться"
    cards = t.pick()
    assert len(cards) == 5 and "Слова для практики" in t.prompt_block("he")
    assert t.prompt_block("en") == ""
    used = t.after_user(f"Я сказал {plain(cards[0]['he'])} правильно?")
    assert used == [cards[0]["he"]]
    assert t.db.execute("SELECT reps FROM tutor_cards WHERE he=?", (cards[0]["he"],)).fetchone()[0] == 1


def test_practice_modes():
    from secretary.tutor import Practice
    t = Tutor(sqlite3.connect(":memory:"))
    p = Practice(t)
    assert "Свободный разговор" in p.prompt_block()
    first = t.course["scenarios"][0]
    assert p.set_scene(first["id"]) == first["title_ru"] and "Сценка «" in p.prompt_block()
    lesson = t.course["lessons"][0]
    assert p.set_lesson(lesson["id"]) == lesson["title"] and "Урок" in p.prompt_block()
    word = t.course["terms"][0]
    assert p.lookup(word["he"])[0]["ru"] == word["ru"]
