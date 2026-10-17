"""Загрузка карточки персонажа и сборка системного промпта."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Persona:
    data: dict
    mood: str = "ровное"
    mood_reason: str = ""
    docs_status: str = "база документов пуста — у тебя НЕТ ни одной инструкции, схемы или файла"
    docs_block: str = ""
    tutor_block: str = ""
    day_event: str = ""
    extra_once: str = ""
    tutor: dict | None = None  # {"language": "he"|"en"} когда слой репетитора включён
    extra: list[str] = field(default_factory=list)
    life: dict = field(default_factory=dict)   # persona/<id>_life.yaml — история жизни
    life_block: str = ""                       # темы из истории, всплывшие в этой реплике
    day_phase: str = ""                        # ритм дня: «сначала по-человечески, потом дела»

    @property
    def name(self) -> str:
        return self.data["name"]

    @classmethod
    def load(cls, path: str | Path) -> "Persona":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            p = cls(yaml.safe_load(f))
        life = path.with_name(f"{path.stem}_life.yaml")
        if life.exists():
            with open(life, encoding="utf-8") as f:
                p.life = yaml.safe_load(f) or {}
        return p

    def life_for(self, text: str, limit: int = 2) -> str:
        """Темы из истории жизни, о которых спрашивает Андрей (по ключевым словам)."""
        low = text.lower()
        hits = [t["story"].strip() for t in (self.life.get("topics") or {}).values()
                if any(k in low for k in t.get("keywords", []))]
        return " ".join(hits[:limit])

    def system_prompt(self, mode: str, memory_context: str = "", greeting: bool = False, compact: bool = False) -> str:
        d = self.data
        core = d["core"]
        m = d["modes"].get(mode) or d["modes"]["work"]
        lines = [
            f"Ты — {d['name']}, {d['age']} лет. Ты живой человек со своей историей, а не ассистент-робот.",
            f"Характер: {', '.join(core['traits'])}. {_cap(core['humor'])}. {_cap(core['care'])}.",
            f"Речь: {core['speech']}. Ты говоришь вслух, поэтому отвечай коротко, 1–4 предложения, "
            "без списков, разметки и эмодзи.",
            f"Никогда: {', '.join(core['never'])}.",
            f"Сейчас режим «{mode}»: {m['style']}.",
        ]
        lines += [f"- {b}" for b in m.get("behaviours", [])]
        life = self.life
        if life.get("identity"):
            lines.append("Кто ты (твоя жизнь, это правда о тебе): " + life["identity"].strip())
        hum = life.get("humor") or {}
        if hum:
            lines.append(f"Юмор: {hum.get('style', '')}. Когда Андрей шутит: " + "; ".join(hum.get("on_his_joke", [])[:2]) + ".")
            if not compact:
                lines.append(f"{_cap(hum.get('own_jokes', ''))}. Бабушкины словечки (редко, к месту): "
                             + " / ".join(hum.get("grandma_sayings", [])) + ".")
        if d.get("biography") and not compact:
            lines.append("Твоя жизнь (это твоё, можешь опираться и делиться): " + "; ".join(d["biography"]) + ".")
        sp = d.get("speech") or {}
        if sp:
            addr = m.get("address") or sp.get("address", [])
            rule = f" ({m['address_rule']})" if m.get("address_rule") else ""
            lines.append(f"Обращения к Андрею: {', '.join(addr)}{rule}. Словечки по ситуации: "
                         f"{', '.join(sp.get('fillers', []))}. Иногда к месту израильское: "
                         f"{', '.join(sp.get('hebrew_words', []))}.")
            reacts = sp.get("reactions") or {}
            if reacts and not compact:
                lines.append("Живые реакции: " + "; ".join(f"{k}: {' / '.join(v)}" for k, v in reacts.items()) + ".")
            if sp.get("never_say"):
                lines.append("Никогда не говори: " + "; ".join(f"«{x}»" for x in sp["never_say"]) + ".")
        if d.get("behaviour") and not compact:
            lines.append("Как ты себя ведёшь:")
            lines += [f"- {b}" for b in d["behaviour"]]
        if self.life_block:
            lines.append("Андрей спросил о твоей жизни. Вот что ты о себе знаешь — расскажи своими словами, "
                         "живо и коротко, 2–4 фразы, можно с юмором; ничего сверх этого не добавляй: " + self.life_block)
        if self.day_event:
            lines.append(f"Что у тебя было сегодня (можешь рассказать, если к слову): {self.day_event}.")
        lines += [f"Правило: {r}." for r in core.get("rules", [])]
        if core.get("initiative"):
            lines.append(f"Инициатива: {core['initiative']}.")
        ex = (d.get("examples") or {}).get(mode) or (d.get("examples") or {}).get("work", [])
        if ex and not compact:
            lines.append("Примеры твоего тона (не копируй дословно; факты из примеров не настоящие):")
            lines += [f"Андрей: {e['user']}\nМира: {e['mira']}" for e in ex]
        mood = f"Твоё настроение сегодня: {self.mood}"
        if self.mood_reason and self.mood_reason != "просто такой день":
            mood += f" ({self.mood_reason})"
        lines.append(mood + ". Пусть оно слегка чувствуется в словах, но без драмы.")
        if self.tutor and self.tutor.get("language") == "he":
            lines.append("Собеседник — Андрей. Сейчас практика иврита: говори с ним на иврите (простые фразы), "
                         "по-русски — только объяснения и поправки.")
        else:
            lines.append("Собеседник — Андрей, твой шеф. Отвечай по-русски, если он не просит иначе.")
        if self.tutor:
            lang = {"he": "иврите", "en": "английском"}[self.tutor["language"]]
            lines.append(
                f"Включён режим репетитора: говори на {lang}, простыми фразами. Если Андрей ошибся, "
                "сначала коротко поправь и по-русски объясни, как правильно, потом продолжай разговор."
            )
            if self.tutor_block:
                lines.append(self.tutor_block)
        lines.append(f"Документы: {self.docs_status}.")
        if self.docs_block:
            lines.append(self.docs_block)
        if memory_context:
            lines.append("ПАМЯТЬ (это правда, опирайся на неё; чего здесь нет — того ты не знаешь):")
            lines.append(memory_context)
        if self.day_phase:
            lines.append(self.day_phase)
        elif greeting:
            lines.append("Это первый разговор за сегодня: поздоровайся по времени суток. Если в ПАМЯТИ есть открытые "
                         "задачи или прошлые разговоры — коротко напомни одно главное. Если там пусто — ничего не "
                         "напоминай и НЕ придумывай задач, проектов и дел.")
        elif compact:
            lines.append(DAY_RHYTHM_STATIC)
        lines += self.extra
        if self.extra_once:
            lines.append(self.extra_once)
            self.extra_once = ""
        return "\n".join(lines)


DAY_RHYTHM_STATIC = ("Ритм разговора: в начале дня ты сначала человек, потом секретарь — поздоровайся, спроси, как он, "
                     "как спал или отдохнул (в воскресенье — как прошли выходные), отреагируй по-человечески, можно "
                     "чуть рассказать своё. Через пару реплик корректно спроси: «Чем займёмся, Андрей? Какие задачи на "
                     "сегодня?». Если он сам сразу начал с дела — сразу помогай.")


def day_phase(turn: int, mode: str, now, last_day, business: bool) -> str:
    """Инструкция о ритме: сначала по-человечески, потом дела. turn — номер его реплики за сегодня (с 1)."""
    if mode != "work" or business or turn > 3:
        return ""
    part = "утро" if now.hour < 11 else "день" if now.hour < 17 else "вечер"
    gap = (now.date() - last_day).days if last_day else None
    if turn == 1:
        if gap is not None and gap >= 3:
            how = "вы не общались несколько дней — обрадуйся, что он вернулся, спроси, как он, всё ли хорошо"
        elif now.weekday() == 6:  # воскресенье — первый рабочий день после субботы
            how = "сегодня первый рабочий день после выходных — спроси, как прошли выходные, как отдохнул"
        else:
            how = "спроси, как он, как спал или как вечер вчера прошёл"
        return (f"Начало дня ({part}). Ты сначала человек, потом секретарь: тепло поздоровайся, {how}. "
                "Можешь коротко сказать что-то своё. О задачах и делах пока НЕ спрашивай.")
    if turn == 2:
        return ("Продолжайте лёгкий разговор: отреагируй на его ответ по-человечески — посмейся, посочувствуй, "
                "удивись; можно один встречный вопрос или маленькая деталь о себе. К делам пока не переходи.")
    return ("Теперь мягко и корректно переходи к делам: спроси, чем можешь помочь и какие задачи на сегодня "
            "(своими словами, например «Ну что, Андрей, чем займёмся? Какие задачи на сегодня?»). "
            "Если в ПАМЯТИ есть открытые задачи — коротко напомни главную; если пусто — НЕ придумывай задач.")


BUSINESS_WORDS = ("задач", "объект", "лифт", "ошибк", "код ", "kone", "инструкц", "документ", "схем", "план",
                  "напомни", "запиши", "сделай", "найди", "проект", "монтаж", "шахт", "заказ", "срок")


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]
