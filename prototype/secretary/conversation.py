"""Оркестратор диалога: собирает промпт, ведёт историю, стримит ответ по предложениям."""
import time
from typing import Iterator

from . import events as ev
from .engines.base import LLM
from .engines.llm_llamacpp import _strip_think
from .events import EventBus
from .persona import Persona
from .sentences import SentenceSplitter


class Conversation:
    def __init__(self, persona: Persona, llm: LLM, bus: EventBus, mode: str = "work",
                 history_turns: int = 20) -> None:
        self.persona = persona
        self.llm = llm
        self.bus = bus
        self.mode = mode
        self.history: list[dict] = []
        self.history_turns = history_turns
        self.cancelled = False

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.bus.emit(ev.MODE_CHANGED, mode=mode)

    def respond(self, user_text: str) -> Iterator[str]:
        """Отдаёт ответ по предложениям по мере генерации."""
        self.cancelled = False
        messages = [{"role": "system", "content": self.persona.system_prompt(self.mode)}]
        messages += self.history[-self.history_turns * 2:]
        messages.append({"role": "user", "content": user_text})

        splitter = SentenceSplitter()
        full = ""
        t0 = time.monotonic()
        first_token_ms = None
        for piece in _strip_think(self.llm.stream_chat(messages)):
            if self.cancelled:
                break
            if first_token_ms is None and piece.strip():
                first_token_ms = int((time.monotonic() - t0) * 1000)
            full += piece
            self.bus.emit(ev.ASSISTANT_TOKEN, text=piece)
            for sentence in splitter.feed(piece):
                self.bus.emit(ev.ASSISTANT_SENTENCE, text=sentence)
                yield sentence
        if not self.cancelled:
            for sentence in splitter.flush():
                self.bus.emit(ev.ASSISTANT_SENTENCE, text=sentence)
                yield sentence

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": full.strip() + (" …" if self.cancelled else "")})
        self.bus.emit(ev.ASSISTANT_DONE, text=full, first_token_ms=first_token_ms)

    def cancel(self) -> None:
        self.cancelled = True
