"""Долговременная память Миры (SQLite).

Уровни (docs/ARCHITECTURE.md, модуль 4): реплики → эпизоды (сводки разговоров) → факты → задачи.
У каждой записи есть область: work или private. В рабочем режиме приватное не видно (ADR 0003).
"""
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, ts TEXT, session TEXT, mode TEXT,
                                     scope TEXT, role TEXT, content TEXT);
CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, day TEXT, session TEXT, scope TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, scope TEXT, fact TEXT UNIQUE, updated TEXT);
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT, due TEXT, status TEXT DEFAULT 'open',
                                  created TEXT, done TEXT);
CREATE TABLE IF NOT EXISTS mood (day TEXT PRIMARY KEY, state TEXT, reason TEXT);
"""

PRIVATE_MODES = {"private"}


def scope_of(mode: str) -> str:
    return "private" if mode in PRIVATE_MODES else "work"


class Memory:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.session = datetime.now().strftime("%Y%m%d-%H%M%S")

    # --- реплики ---------------------------------------------------------
    def add_message(self, mode: str, role: str, content: str) -> None:
        self.db.execute("INSERT INTO messages (ts, session, mode, scope, role, content) VALUES (?,?,?,?,?,?)",
                        (datetime.now().isoformat(timespec="seconds"), self.session, mode, scope_of(mode),
                         role, content))
        self.db.commit()

    def session_messages(self, session: str | None = None) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM messages WHERE session=? ORDER BY id",
                               (session or self.session,)).fetchall()

    def unsummarized_sessions(self) -> list[str]:
        rows = self.db.execute("""SELECT DISTINCT session FROM messages
                                  WHERE session NOT IN (SELECT session FROM episodes)""").fetchall()
        return [r["session"] for r in rows]

    def last_contact(self) -> date | None:
        row = self.db.execute("SELECT max(ts) AS ts FROM messages WHERE session != ?", (self.session,)).fetchone()
        return date.fromisoformat(row["ts"][:10]) if row and row["ts"] else None

    def is_first_session_today(self) -> bool:
        row = self.db.execute("SELECT count(*) AS n FROM messages WHERE ts >= ? AND session != ?",
                              (date.today().isoformat(), self.session)).fetchone()
        return row["n"] == 0

    # --- эпизоды и факты --------------------------------------------------
    def add_episode(self, session: str, scope: str, summary: str) -> None:
        self.db.execute("INSERT INTO episodes (day, session, scope, summary) VALUES (?,?,?,?)",
                        (session[:4] + "-" + session[4:6] + "-" + session[6:8], session, scope, summary))
        self.db.commit()

    def add_fact(self, fact: str, scope: str = "work") -> None:
        fact = fact.strip().rstrip(".")
        if fact:
            self.db.execute("""INSERT INTO facts (scope, fact, updated) VALUES (?,?,?)
                               ON CONFLICT(fact) DO UPDATE SET updated=excluded.updated""",
                            (scope, fact, datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def forget(self, text: str) -> int:
        cur = self.db.execute("DELETE FROM facts WHERE fact LIKE ?", (f"%{text}%",))
        self.db.commit()
        return cur.rowcount

    def _scopes(self, mode: str) -> tuple[str, ...]:
        return ("work", "private") if scope_of(mode) == "private" else ("work",)

    def recent_episodes(self, mode: str, n: int = 3) -> list[sqlite3.Row]:
        q = f"SELECT * FROM episodes WHERE scope IN ({','.join('?' * len(self._scopes(mode)))}) ORDER BY id DESC LIMIT ?"
        return list(reversed(self.db.execute(q, (*self._scopes(mode), n)).fetchall()))

    def facts(self, mode: str, n: int = 30) -> list[str]:
        q = f"SELECT fact FROM facts WHERE scope IN ({','.join('?' * len(self._scopes(mode)))}) ORDER BY updated DESC LIMIT ?"
        return [r["fact"] for r in self.db.execute(q, (*self._scopes(mode), n)).fetchall()]

    # --- задачи -----------------------------------------------------------
    def add_task(self, title: str, due: str | None = None) -> int:
        exists = self.db.execute("SELECT id FROM tasks WHERE title=? AND status='open'", (title,)).fetchone()
        if exists:
            return exists["id"]
        cur = self.db.execute("INSERT INTO tasks (title, due, created) VALUES (?,?,?)",
                              (title.strip(), due, date.today().isoformat()))
        self.db.commit()
        return cur.lastrowid

    def open_tasks(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM tasks WHERE status='open' ORDER BY coalesce(due,'9999'), id").fetchall()

    def complete_task(self, task_id: int) -> bool:
        cur = self.db.execute("UPDATE tasks SET status='done', done=? WHERE id=? AND status='open'",
                              (date.today().isoformat(), task_id))
        self.db.commit()
        return cur.rowcount > 0

    # --- настроение -------------------------------------------------------
    def get_mood(self, day: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM mood WHERE day=?", (day,)).fetchone()

    def last_mood(self) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM mood ORDER BY day DESC LIMIT 1").fetchone()

    def set_mood(self, day: str, state: str, reason: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO mood (day, state, reason) VALUES (?,?,?)", (day, state, reason))
        self.db.commit()

    # --- контекст для промпта ---------------------------------------------
    def context_block(self, mode: str) -> str:
        parts = []
        eps = self.recent_episodes(mode)
        if eps:
            parts.append("Что было в прошлых разговорах:")
            parts += [f"- {e['day']}: {e['summary']}" for e in eps]
        facts = self.facts(mode)
        if facts:
            parts.append("Что ты знаешь об Андрее и его делах:")
            parts += [f"- {f}" for f in facts]
        tasks = self.open_tasks()
        if tasks:
            parts.append("Открытые задачи:")
            parts += [f"- [{t['id']}] {t['title']}" + (f" (срок {t['due']})" if t["due"] else "") for t in tasks]
        else:
            parts.append("Открытых задач нет.")
        return "\n".join(parts)


# --- «сон»: сводка разговора, факты и задачи ------------------------------

CONSOLIDATE_PROMPT = """Ниже разговор Андрея с его ассистенткой Мирой. Сделай выжимку для долговременной памяти.
Ответь ТОЛЬКО JSON без пояснений, по схеме:
{"summary": "1–2 предложения: о чём говорили и чем закончилось",
 "facts": ["короткие факты об Андрее, его работе, объектах, людях, которые он сам сообщил"],
 "tasks": [{"title": "что нужно сделать", "due": "YYYY-MM-DD или null"}]}
Правила: только то, что прямо сказано в разговоре; ничего не придумывай; если фактов или задач нет — пустые списки.
Сегодня {today}.

Разговор:
{dialog}"""


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def consolidate(memory: Memory, llm, session: str | None = None) -> dict | None:
    """Сжимает разговор в эпизод, факты и задачи. Запускается при выходе или «ночью»."""
    session = session or memory.session
    msgs = memory.session_messages(session)
    if len([m for m in msgs if m["role"] == "user"]) < 2:
        return None
    scope = "private" if any(m["scope"] == "private" for m in msgs) else "work"
    dialog = "\n".join(f"{'Андрей' if m['role'] == 'user' else 'Мира'}: {m['content']}" for m in msgs)[-12000:]
    prompt = CONSOLIDATE_PROMPT.replace("{today}", date.today().isoformat()).replace("{dialog}", dialog)
    text = "".join(llm.stream_chat([{"role": "user", "content": prompt}]))
    data = parse_json(text)
    if not data:
        return None
    if data.get("summary"):
        memory.add_episode(session, scope, str(data["summary"]))
    for f in data.get("facts") or []:
        memory.add_fact(str(f), scope)
    for t in data.get("tasks") or []:
        if isinstance(t, dict) and t.get("title"):
            due = t.get("due") if t.get("due") not in (None, "null", "") else None
            memory.add_task(str(t["title"]), due)
    return data
