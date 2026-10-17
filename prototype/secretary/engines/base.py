"""Интерфейсы движков. Android-версия реализует те же интерфейсы на Kotlin."""
from typing import Iterator, Protocol

import numpy as np

SAMPLE_RATE_IN = 16000  # микрофон, VAD и распознавание работают на 16 кГц


class STT(Protocol):
    def transcribe(self, audio: np.ndarray, language: str | None = None) -> str: ...


class LLM(Protocol):
    def stream_chat(self, messages: list[dict]) -> Iterator[str]: ...


class TTS(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> np.ndarray: ...


class VAD(Protocol):
    def reset(self) -> None: ...

    def process(self, chunk: np.ndarray) -> str | None:
        """Принимает кусок из 512 сэмплов. Возвращает 'start', 'end' или None."""
        ...
