"""Слой репетитора: слова и уроки из Ivrit Trainer + интервальное повторение (ADR 0005)."""
import gzip
import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

COURSE = Path(__file__).resolve().parents[2] / "persona" / "tutor" / "he_course.json.gz"
NIKUD = re.compile(r"[֑-ׇ]")

SCHEMA = """CREATE TABLE IF NOT EXISTS tutor_cards (he TEXT PRIMARY KEY, ru TEXT, tr TEXT, nikud TEXT, track TEXT,
             due TEXT, interval INTEGER DEFAULT 0, reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0, seen TEXT);"""


def plain(he: str) -> str:
    return NIKUD.sub("", he or "")


class Tutor:
    def __init__(self, db: sqlite3.Connection, tracks=("CORE", "MDA"), per_session: int = 5) -> None:
        self.db = db
        self.db.executescript(SCHEMA)
        self.tracks = tracks
        self.per_session = per_session
        self.course = json.load(gzip.open(COURSE, "rt", encoding="utf-8")) if COURSE.exists() else {"terms": []}
        self.today: list[dict] = []

    def pick(self) -> list[dict]:
        """Сначала слова, которые пора повторить, потом новые из выбранных треков."""
        rows = self.db.execute("SELECT * FROM tutor_cards WHERE due <= ? ORDER BY due LIMIT ?",
                               (date.today().isoformat(), self.per_session)).fetchall()
        cards = [dict(zip([c[0] for c in self.db.execute("SELECT * FROM tutor_cards LIMIT 0").description], r))
                 for r in rows]
        known = {r[0] for r in self.db.execute("SELECT he FROM tutor_cards")}
        for t in self.course["terms"]:
            if len(cards) >= self.per_session:
                break
            if t["track"] in self.tracks and t["he"] not in known and len(t["he"]) > 1:
                cards.append({"he": t["he"], "ru": t["ru"], "tr": t["tr"], "nikud": t["nikud"], "track": t["track"]})
                self.db.execute("INSERT OR IGNORE INTO tutor_cards (he, ru, tr, nikud, track, due, seen) "
                                "VALUES (?,?,?,?,?,?,?)", (t["he"], t["ru"], t["tr"], t["nikud"], t["track"],
                                                           date.today().isoformat(), date.today().isoformat()))
        self.db.commit()
        self.today = cards
        return cards

    def prompt_block(self, language: str) -> str:
        if language != "he" or not (self.today or self.pick()):
            return ""
        words = "; ".join(f"{c['nikud'] or c['he']} ({c['tr']}) — {c['ru']}" for c in self.today)
        return ("Слова для практики сегодня (вплетай их в разговор естественно, по одному, проси Андрея "
                f"употребить; иврит пиши с огласовками и русской транслитерацией с ударением): {words}")

    def after_user(self, text: str) -> list[str]:
        """Слово из сегодняшних употреблено — интервал растёт. Возвращает употреблённые."""
        msg = plain(text)
        used = [c["he"] for c in self.today if plain(c["he"]) and plain(c["he"]) in msg]
        for he in used:
            row = self.db.execute("SELECT interval, reps FROM tutor_cards WHERE he=?", (he,)).fetchone()
            interval = max(1, int((row[0] or 0) * 2.3)) if row else 1
            self.db.execute("UPDATE tutor_cards SET interval=?, reps=reps+1, due=? WHERE he=?",
                            (interval, (date.today() + timedelta(days=interval)).isoformat(), he))
        self.db.commit()
        return used
