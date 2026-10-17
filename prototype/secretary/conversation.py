"""Оркестратор диалога: собирает промпт, ведёт историю, стримит ответ по предложениям."""
import time
from typing import Iterator

from . import events as ev
from .engines.base import LLM
from .engines.llm_llamacpp import _strip_think
from .events import EventBus
from .knowledge import KnowledgeBase, check_citations
from .memory import Memory
from .tutor import Practice, Tutor
from .persona import Persona
from .sentences import SentenceSplitter


class Conversation:
    def __init__(self, persona: Persona, llm: LLM, bus: EventBus, mode: str = "work",
                 history_turns: int = 20, memory: Memory | None = None,
                 kb: KnowledgeBase | None = None) -> None:
        self.persona = persona
        self.llm = llm
        self.bus = bus
        self.mode = mode
        self.history: list[dict] = []
        self.history_turns = history_turns
        self.cancelled = False
        self.memory = memory
        self.kb = kb
        self.tutor = Tutor(memory.db) if memory else None
        self.practice = Practice(self.tutor) if self.tutor else None
        self.last_hits = []
        if kb:
            persona.docs_status = kb.describe()
        self.greeting = bool(memory and memory.is_first_session_today())

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.bus.emit(ev.MODE_CHANGED, mode=mode)

    def respond(self, user_text: str) -> Iterator[str]:
        """Отдаёт ответ по предложениям по мере генерации."""
        self.cancelled = False
        self.last_hits = []
        self.persona.docs_block = ""
        if self.kb and not self.kb.empty and self.mode == "work":
            self.last_hits = self.kb.search(user_text)
            self.persona.docs_block = KnowledgeBase.prompt_block(self.last_hits)
        if self.tutor and self.persona.tutor:
            self.tutor.after_user(user_text)
            lang = self.persona.tutor["language"]
            self.persona.tutor_block = self.practice.prompt_block() if lang == "he" else ""
        ctx = self.memory.context_block(self.mode) if self.memory else ""
        greeting, self.greeting = self.greeting, False
        messages = [{"role": "system", "content": self.persona.system_prompt(self.mode, ctx, greeting)}]
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

        answer = full.strip() + (" …" if self.cancelled else "")
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": answer})
        if self.memory:
            self.memory.add_message(self.mode, "user", user_text)
            self.memory.add_message(self.mode, "assistant", answer)
        self.bus.emit(ev.ASSISTANT_DONE, text=full, first_token_ms=first_token_ms)
        self.unknown_he = []
        if self.practice and self.persona.tutor:
            from .tutor import unknown_hebrew
            self.unknown_he = unknown_hebrew(full, self.practice._idx)
        self.bad_citations = check_citations(full, self.last_hits) if self.kb and not self.kb.empty else []

    def cancel(self) -> None:
        self.cancelled = True
