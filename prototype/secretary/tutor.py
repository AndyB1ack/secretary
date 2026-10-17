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


# --- практика: разговор, сценки, уроки, словарь -----------------------------

TUTOR_MODES = {
    "talk": ("Свободный разговор на иврите на бытовую или рабочую тему. Говори короткими простыми фразами, "
             "в основном словами, которые Андрей уже знает (список ниже), и понемногу добавляй новые."),
    "scene": ("Сценка: разыгрываете ситуацию по ролям. Ты играешь одну или несколько ролей (мужчину, женщину, "
              "группу людей) — перед репликой пиши роль в скобках, например (врач, муж.): … Соблюдай род и число "
              "в глаголах и прилагательных. Андрей играет свою роль. Ошибки поправляй после его реплики."),
    "lesson": ("Урок: объясни материал по-русски, коротко и с примерами на иврите, потом задай 2–3 вопроса "
               "на проверку и разбери ответы."),
    "quiz": ("Опрос: по очереди спрашивай пройденные слова и фразы (с русского на иврит и обратно), "
             "по одному за раз; хвали за правильные, разбирай ошибки."),
}


def _course_index(course: dict) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for t in course.get("terms", []):
        idx.setdefault(plain(t["he"]), []).append(t)
    return idx


class Practice:
    """Надстройка над Tutor: режимы практики, известный лексикон, новые слова, сценки, уроки, словарь."""

    def __init__(self, tutor: Tutor) -> None:
        self.t = tutor
        self.mode = "talk"
        self.topic = ""
        self.scene: dict | None = None
        self.lesson: dict | None = None
        self.lookups: list[dict] = []
        self._idx = _course_index(tutor.course)

    def known(self, n: int = 40) -> list[dict]:
        rows = self.t.db.execute("SELECT he, nikud, tr, ru FROM tutor_cards WHERE reps > 0 "
                                 "ORDER BY reps DESC, random() LIMIT ?", (n,)).fetchall()
        return [dict(zip(("he", "nikud", "tr", "ru"), r)) for r in rows]

    def set_scene(self, query: str = "") -> str:
        scenes = self.t.course.get("scenarios", [])
        q = query.lower()
        match = next((s for s in scenes if q and (q in s.get("id", "").lower() or q in s.get("title_ru", "").lower())), None)
        self.mode, self.scene, self.topic = "scene", match, ("" if match else query)
        return match["title_ru"] if match else (query or "свободная сценка")

    def set_lesson(self, lesson_id: str) -> str | None:
        self.lesson = next((l for l in self.t.course.get("lessons", []) if l["id"].lower() == lesson_id.lower()), None)
        if self.lesson:
            self.mode = "lesson"
            return self.lesson["title"]
        return None

    def lookup(self, word: str) -> list[dict]:
        w = plain(word.strip())
        hits = self._idx.get(w, [])
        if not hits:
            low = word.lower().strip()
            hits = [t for t in self.t.course.get("terms", []) if low and low in t["ru"].lower()][:5]
        self.lookups = hits[:5]
        return self.lookups

    def sync_from_app(self, url: str, token: str) -> int:
        """Подтягивает пройденное из Ivrit Trainer (GET /api/mira/progress). Нужна сеть."""
        import urllib.request

        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        data = json.load(urllib.request.urlopen(req, timeout=20))
        for t in data.get("terms", []):
            self.t.db.execute("""INSERT INTO tutor_cards (he, ru, tr, nikud, track, due, interval, reps, seen)
                                 VALUES (?,?,?,?,?,?,?,?,?)
                                 ON CONFLICT(he) DO UPDATE SET reps=max(reps, excluded.reps)""",
                              (t["he"], t["ru"], t.get("tr", ""), t.get("nikud", ""), "APP",
                               (t.get("due") or date.today().isoformat())[:10], int(t.get("stability") or 1),
                               int(t.get("reps") or 1), date.today().isoformat()))
        self.t.db.commit()
        return len(data.get("terms", []))

    def prompt_block(self) -> str:
        lines = [f"Режим практики: {TUTOR_MODES[self.mode]}"]
        known = self.known()
        if known:
            lines.append("Андрей уже знает: " + "; ".join(f"{k['nikud'] or k['he']} — {k['ru']}" for k in known) + ".")
        else:
            lines.append("Пройденных слов пока мало — начинай с самых простых фраз.")
        new = self.t.today or self.t.pick()
        lines.append("Новые слова на сегодня (вводи по одному, объясняй, проси повторить): " +
                     "; ".join(f"{c['nikud'] or c['he']} ({c['tr']}) — {c['ru']}" for c in new) + ".")
        if self.mode == "scene" and self.scene:
            script = " / ".join(f"{l.get('speaker')}: {l.get('he')}" for l in self.scene.get("lines", [])[:12])
            lines.append(f"Сценка «{self.scene.get('title_ru')}». Цель: {self.scene.get('goal_ru', '')}. "
                         f"Образец реплик (используй как опору, не читай подряд): {script}")
        elif self.mode == "scene" and self.topic:
            lines.append(f"Тема сценки: {self.topic}. Придумай ситуацию и роли сама.")
        if self.mode == "lesson" and self.lesson:
            lines.append(f"Урок {self.lesson['id']} «{self.lesson['title']}». Цель: {self.lesson['goal']}. "
                         f"Материал:\n{self.lesson['grammar'][:2500]}")
        if self.lookups:
            lines.append("Словарь (точные данные из курса, опирайся на них — огласовки, ударение, перевод): " +
                         "; ".join(f"{t['nikud']} ({t['tr']}) — {t['ru']}" for t in self.lookups))
        lines.append("Используй слова из списков выше и из словаря курса. Если нужно слово, которого там нет, — "
                     "проверь себя: пиши только то, в чём уверена, и никогда не придумывай значения слов.")
        lines.append("Иврит всегда с огласовками и русской транслитерацией с ударением. Если слова нет в словаре "
                     "и ты не уверена в огласовке или ударении — так и скажи, не выдумывай.")
        return "\n".join(lines)


HEB_WORD = re.compile(r"[א-ת֑-ׇ]+")
PREFIXES = "והבלמשכ"
FINALS = str.maketrans({"כ": "ך", "מ": "ם", "נ": "ן", "פ": "ף", "צ": "ץ"})


def unknown_hebrew(text: str, index: dict[str, list[dict]]) -> list[str]:
    """Слова на иврите из ответа, которых нет в словаре курса (с учётом приставок ו ה ב ל מ ש כ)."""
    out = []
    for raw in HEB_WORD.findall(text):
        w = plain(raw)
        if len(w) < 2:
            continue
        stems = {w} | {w[i:] for i in range(1, 3) if all(c in PREFIXES for c in w[:i]) and len(w) - i >= 2}
        cands = set(stems)
        for st in stems:  # мн. число и женский род: ים / ות / ה / ת, конечные буквы
            for suf in ("ים", "ות", "ה", "ת"):
                if st.endswith(suf) and len(st) - len(suf) >= 2:
                    base = st[: -len(suf)]
                    cands |= {base, base + "ה", base.translate(FINALS)}
        if not any(c in index for c in cands) and raw not in out:
            out.append(raw)
    return out


WORD_Q = re.compile(r"(?:что (?:значит|означает)|как переводится|перевод слова|как (?:сказать|будет)(?: на иврите)?|"
                    r"какое ударение в|как пишется)\s*(?:слово\s*)?[«\"']?([^«»\"'?!.]+)", re.I)


def word_question(text: str) -> str | None:
    m = WORD_Q.search(text)
    return m.group(1).strip() if m else None
