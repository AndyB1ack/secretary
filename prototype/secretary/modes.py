"""Голосовые команды смены режима (в прототипе без отпечатка и геозоны)."""
import re

COMMANDS = [
    (r"\b(рабочий день окончен|еду домой|конец работы)\b", "evening"),
    (r"\b(обед,? я один|я один)\b", "private"),
    (r"\b(паника|стоп,? работа|за работу)\b", "work"),
    (r"\b(выходной|сегодня суббота)\b", "weekend"),
]


def detect_mode_command(text: str) -> str | None:
    low = text.lower()
    for pattern, mode in COMMANDS:
        if re.search(pattern, low):
            return mode
    return None
