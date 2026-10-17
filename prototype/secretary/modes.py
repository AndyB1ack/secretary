"""Голосовые команды смены режима (в прототипе без отпечатка и геозоны).

Команда срабатывает, только если фраза короткая и начинается с командных слов,
чтобы «я один не справлюсь» не переключало режим.
"""
import re

COMMANDS = [
    (r"^(мира,?\s*)?(рабочий день окончен|еду домой|конец работы)\b", "evening"),
    (r"^(мира,?\s*)?(обед,? я один|я один,? можно)\b", "private"),
    (r"^(мира,?\s*)?(паника|стоп,? работа|за работу)\b", "work"),
    (r"^(мира,?\s*)?(сегодня выходной|выходной день)\b", "weekend"),
]
MAX_WORDS = 6


def detect_mode_command(text: str) -> str | None:
    low = text.lower().strip(" .!?")
    if len(low.split()) > MAX_WORDS:
        return None
    for pattern, mode in COMMANDS:
        if re.search(pattern, low):
            return mode
    return None
