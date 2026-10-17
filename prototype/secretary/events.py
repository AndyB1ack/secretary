"""Простая шина событий. Модули не знают друг о друге, только о событиях."""
from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    def emit(self, event: str, **payload: Any) -> None:
        for handler in list(self._handlers[event]) + list(self._handlers["*"]):
            handler({"event": event, **payload})


# Имена событий, общие для прототипа и будущего Android-приложения
USER_SAID = "user.said"            # text, lang, stt_ms
ASSISTANT_TOKEN = "assistant.token"  # text
ASSISTANT_SENTENCE = "assistant.sentence"  # text
ASSISTANT_DONE = "assistant.done"  # text, first_token_ms
SPEAKING_STARTED = "speech.started"
SPEAKING_STOPPED = "speech.stopped"  # interrupted: bool
MODE_CHANGED = "mode.changed"      # mode
