"""Настроение дня: меняется раз в сутки, с инерцией и поводами (persona/mira.yaml → mood)."""
import random
from datetime import date

from .memory import Memory

STATES = ["отличное", "ровное", "задумчивое", "грустное", "немного обиженное"]
# вероятности перехода «вчера → сегодня»: настроение тянется, но не застревает
DRIFT = {
    "отличное": [0.45, 0.35, 0.12, 0.05, 0.03],
    "ровное": [0.25, 0.45, 0.18, 0.08, 0.04],
    "задумчивое": [0.2, 0.4, 0.25, 0.1, 0.05],
    "грустное": [0.25, 0.4, 0.2, 0.12, 0.03],
    "немного обиженное": [0.3, 0.45, 0.15, 0.08, 0.02],  # обида не держится дольше дня
}


def event_for_today(memory: Memory, events: list[str], rng: random.Random | None = None) -> str:
    """Одна «новость дня» из её жизни; не повторяется два дня подряд."""
    if not events:
        return ""
    today = date.today().isoformat()
    row = memory.db.execute("SELECT reason FROM mood WHERE day=?", ("event:" + today,)).fetchone()
    if row:
        return row["reason"]
    last = memory.db.execute("SELECT reason FROM mood WHERE day LIKE 'event:%' ORDER BY day DESC LIMIT 1").fetchone()
    choices = [e for e in events if not last or e != last["reason"]] or events
    ev = (rng or random.Random()).choice(choices)
    memory.set_mood("event:" + today, "event", ev)
    return ev


def mood_for_today(memory: Memory, rng: random.Random | None = None, today: date | None = None) -> tuple[str, str]:
    rng = rng or random.Random()
    today = today or date.today()
    saved = memory.get_mood(today.isoformat())  # события дня хранятся с префиксом event: и сюда не попадают
    if saved:
        return saved["state"], saved["reason"]

    last_contact = memory.last_contact()
    gap = (today - last_contact).days if last_contact else None
    prev = memory.last_mood()
    if gap is not None and gap >= 3:
        state, reason = "немного обиженное", f"Андрей не заходил {gap} дня — соскучилась и чуть обижена"
    else:
        weights = DRIFT.get(prev["state"] if prev else "ровное", DRIFT["ровное"])
        state = rng.choices(STATES, weights=weights)[0]
        reason = "просто такой день"
    memory.set_mood(today.isoformat(), state, reason)
    return state, reason
