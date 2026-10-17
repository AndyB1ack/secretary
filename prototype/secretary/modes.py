"""Смена режимов голосом (в прототипе без отпечатка и геозоны).

Правила:
- Команда срабатывает только на короткой фразе, а не внутри обычного предложения.
- Вход в приватный режим и «конец рабочего дня» никогда не происходят сразу: Мира
  нейтрально переспрашивает (если рядом кто-то есть, вопрос звучит безобидно) и
  переключается только после явного «да».
- Возврат к работе («паника», «за работу») — мгновенно, без вопросов.
"""
import re
from dataclasses import dataclass

MAX_WORDS = 8
PREFIX = r"^(мира,?\s*)?(всё,?\s*|так,?\s*|ну\s*)?"

# (шаблон, режим, нужен ли переспрос)
COMMANDS = [
    (r"(паника|стоп,? работа|за работу|рабочий режим)\b", "work", False),
    (r"(обед,? я один|я один,? можно|у меня (сейчас )?(обед|обеденный перерыв)|обеденный перерыв)\b", "private", True),
    (r"(рабочий день окончен|моё рабочее время закончилось|мое рабочее время закончилось|рабочее время закончилось"
     r"|еду домой|я могу идти домой|можно идти домой|конец работы)\b", "evening", True),
    (r"(сегодня выходной|выходной день)\b", "weekend", True),
]

# Голосовые команды практики иврита (без переспроса)
PRACTICE = [
    (r"(давай|поговорим|говорим)\s.*(на иврите|по-?еврейски)", "talk"),
    (r"(давай|сыграем)\s.*(сценк|диалог)", "scene"),
    (r"(проверь|поспрашивай|опрос)\s.*(слов|меня)", "quiz"),
    (r"(хватит|стоп|закончим)\s.*(иврит|урок|практик)", "off"),
]


def detect_practice(text: str) -> str | None:
    low = text.lower().strip(" .!?…")
    if len(low.split()) > MAX_WORDS:
        return None
    return next((m for p, m in PRACTICE if re.search(p, low)), None)


# Нейтральные вопросы: посторонний не поймёт, о чём речь
CONFIRM_QUESTION = {
    "private": "Перерыв? Мне переключиться?",
    "evening": "Заканчиваем на сегодня? Переключаюсь?",
    "weekend": "Сегодня без работы? Переключаюсь?",
}
YES = r"^(да|ага|угу|давай|конечно|переключай(ся)?|точно|верно|yes|кен)\b"
NO = r"^(нет|не надо|отмена|не сейчас|ошибся|оговорился)\b"


@dataclass
class ModeIntent:
    mode: str
    confirm: bool


def detect_mode_command(text: str) -> ModeIntent | None:
    low = text.lower().strip(" .!?…")
    if len(low.split()) > MAX_WORDS:
        return None
    for pattern, mode, confirm in COMMANDS:
        if re.search(PREFIX + pattern, low):
            return ModeIntent(mode, confirm)
    return None


class ModeSwitcher:
    """Держит ожидающее подтверждение между репликами."""

    def __init__(self) -> None:
        self.pending: str | None = None

    def handle(self, text: str, current: str) -> tuple[str | None, str | None, bool]:
        """Возвращает (новый режим или None, что сказать Мире или None, обработана ли реплика целиком)."""
        low = text.lower().strip(" .!?…")
        if self.pending:
            target, self.pending = self.pending, None
            if re.search(YES, low):
                return target, None, True
            if re.search(NO, low):
                return None, "Поняла, продолжаем.", True
            # ответил что-то другое — считаем, что не подтвердил, и разговор идёт дальше
        intent = detect_mode_command(text)
        if not intent or intent.mode == current:
            return None, None, False
        if not intent.confirm:
            return intent.mode, None, True
        self.pending = intent.mode
        return None, CONFIRM_QUESTION[intent.mode], True
