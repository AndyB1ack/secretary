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

    @property
    def name(self) -> str:
        return self.data["name"]

    @classmethod
    def load(cls, path: str | Path) -> "Persona":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def system_prompt(self, mode: str, memory_context: str = "", greeting: bool = False, compact: bool = False) -> str:
        d = self.data
        core = d["core"]
        m = d["modes"].get(mode) or d["modes"]["work"]
        lines = [
            f"Ты — {d['name']}, {d['age']} лет. Ты живой персонаж, а не ассистент-робот.",
            f"Характер: {', '.join(core['traits'])}. {_cap(core['humor'])}. {_cap(core['care'])}.",
            f"Речь: {core['speech']}. Ты говоришь вслух, поэтому отвечай коротко, 1–4 предложения, "
            "без списков, разметки и эмодзи.",
            f"Никогда: {', '.join(core['never'])}.",
            f"Сейчас режим «{mode}»: {m['style']}.",
        ]
        lines += [f"- {b}" for b in m.get("behaviours", [])]
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
        if greeting:
            lines.append("Это первый разговор за сегодня: поздоровайся по времени суток. Если в ПАМЯТИ есть открытые "
                         "задачи или прошлые разговоры — коротко напомни одно главное. Если там пусто — ничего не "
                         "напоминай и НЕ придумывай задач, проектов и дел.")
        lines += self.extra
        if self.extra_once:
            lines.append(self.extra_once)
            self.extra_once = ""
        return "\n".join(lines)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]
