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
        self.day_turn = 0 if self.greeting else 99   # ритм дня включается только в первом разговоре за сегодня
        self.business = False
        self.last_day = memory.last_day_before_today() if memory else None

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.bus.emit(ev.MODE_CHANGED, mode=mode)

    def strict(self) -> bool:
        """Работа и учёба: только проверенные данные, без выдумок (ADR 0010)."""
        return self.mode == "work" or bool(self.persona.tutor)

    def _generate(self, messages: list[dict], temperature: float | None) -> str:
        return "".join(_strip_think(self.llm.stream_chat(messages, temperature)))

    def _validate(self, text: str) -> list[str]:
        problems = []
        if self.kb and not self.kb.empty and self.mode == "work":
            bad = check_citations(text, self.last_hits)
            if bad:
                problems.append(f"ссылки на страницы {', '.join(bad)}, которых нет в найденных фрагментах")
        if self.practice and self.persona.tutor:
            from .tutor import unknown_hebrew
            unk = unknown_hebrew(text, self.practice._idx)
            if unk:
                problems.append(f"слова на иврите не из словаря курса: {', '.join(unk)}")
        return problems

    def respond_strict(self, messages: list[dict]) -> str:
        """Генерирует, проверяет; при нарушении — одна переделка с указанием ошибок; не помогло — честный отказ."""
        text = self._generate(messages, 0.3)
        problems = self._validate(text)
        if problems:
            fix = messages + [{"role": "assistant", "content": text},
                              {"role": "user", "content": "СИСТЕМНАЯ ПРОВЕРКА: в ответе " + "; ".join(problems) +
                               ". Перепиши ответ, используя только данные из блоков «Документы»/«Словарь»/списков слов. "
                               "Чего там нет — честно скажи, что не знаешь."}]
            text = self._generate(fix, 0.2)
            problems = self._validate(text)
        self.strict_problems = problems
        if problems:
            if self.mode == "work" and self.last_hits:
                h = self.last_hits[0]
                return f"Не буду гадать. Вот что дословно в документе {h.ref()}: {h.text[:400]}"
            return "Тут я не уверена и не хочу тебя учить неправильному. Давай проверим по словарю или спросим облако."
        return text

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
            from .tutor import word_question
            asked = word_question(user_text)
            if asked:
                hits = self.practice.lookup(asked)
                if not hits:
                    self.practice.lookups = []
                    self.persona.extra_once = (f"Андрей спросил про «{asked}». В словаре курса этого нет: честно скажи, "
                                               "что в курсе этого слова нет и ты не хочешь гадать; предложи проверить через облако.")
            lang = self.persona.tutor["language"]
            self.persona.tutor_block = self.practice.prompt_block() if lang == "he" else ""
        self.persona.life_block = self.persona.life_for(user_text)
        from datetime import datetime
        from .persona import BUSINESS_WORDS, day_phase
        self.day_turn += 1
        self.business = self.business or any(w in user_text.lower() for w in BUSINESS_WORDS)
        self.persona.day_phase = day_phase(self.day_turn, self.mode, datetime.now(), self.last_day, self.business)
        ctx = self.memory.context_block(self.mode) if self.memory else ""
        greeting, self.greeting = self.greeting, False
        messages = [{"role": "system", "content": self.persona.system_prompt(self.mode, ctx, greeting)}]
        messages += self.history[-self.history_turns * 2:]
        messages.append({"role": "user", "content": user_text})

        splitter = SentenceSplitter()
        full = ""
        t0 = time.monotonic()
        first_token_ms = None
        self.strict_problems = []
        if self.strict():
            stream = iter([self.respond_strict(messages)])
        else:
            stream = _strip_think(self.llm.stream_chat(messages))
        for piece in stream:
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
