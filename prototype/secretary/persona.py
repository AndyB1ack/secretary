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
    tutor: dict | None = None  # {"language": "he"|"en"} когда слой репетитора включён
    extra: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.data["name"]

    @classmethod
    def load(cls, path: str | Path) -> "Persona":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def system_prompt(self, mode: str, memory_context: str = "", greeting: bool = False) -> str:
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
        lines += [f"Правило: {r}." for r in core.get("rules", [])]
        if core.get("initiative"):
            lines.append(f"Инициатива: {core['initiative']}.")
        ex = (d.get("examples") or {}).get(mode) or (d.get("examples") or {}).get("work", [])
        if ex:
            lines.append("Примеры твоего тона (не копируй дословно; факты из примеров не настоящие):")
            lines += [f"Андрей: {e['user']}\nМира: {e['mira']}" for e in ex]
        mood = f"Твоё настроение сегодня: {self.mood}"
        if self.mood_reason and self.mood_reason != "просто такой день":
            mood += f" ({self.mood_reason})"
        lines.append(mood + ". Пусть оно слегка чувствуется в словах, но без драмы.")
        lines.append("Собеседник — Андрей, твой шеф. Отвечай по-русски, если он не просит иначе.")
        if self.tutor:
            lang = {"he": "иврите", "en": "английском"}[self.tutor["language"]]
            lines.append(
                f"Включён режим репетитора: говори на {lang}, простыми фразами. Если Андрей ошибся, "
                "сначала коротко поправь и по-русски объясни, как правильно, потом продолжай разговор."
            )
        lines.append(f"Документы: {self.docs_status}.")
        if self.docs_block:
            lines.append(self.docs_block)
        if memory_context:
            lines.append("ПАМЯТЬ (это правда, опирайся на неё; чего здесь нет — того ты не знаешь):")
            lines.append(memory_context)
        if greeting:
            lines.append("Это первый разговор за сегодня: поздоровайся по времени суток и коротко, одной-двумя "
                         "фразами, напомни главное из памяти — открытые задачи или о чём говорили в прошлый раз.")
        lines += self.extra
        return "\n".join(lines)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]
