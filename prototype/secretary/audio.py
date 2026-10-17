"""Микрофон и динамик."""
import queue
import threading
import time
from typing import Iterator

import numpy as np
import sounddevice as sd

from .engines.base import SAMPLE_RATE_IN

CHUNK = 512  # 32 мс при 16 кГц — размер, который ждёт Silero VAD


class Microphone:
    def __init__(self) -> None:
        self._q: queue.Queue[np.ndarray] = queue.Queue()

    def chunks(self) -> Iterator[np.ndarray]:
        def callback(indata, frames, t, status):  # noqa: ARG001
            self._q.put(indata[:, 0].copy())

        with sd.InputStream(samplerate=SAMPLE_RATE_IN, channels=1, dtype="float32",
                            blocksize=CHUNK, callback=callback):
            while True:
                yield self._q.get()


class Speaker:
    """Проигрывает фразы по очереди. stop() мгновенно обрывает речь (перебивание, «паника»)."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._q: queue.Queue[np.ndarray | None] = queue.Queue()
        self._stop = threading.Event()
        self._playing = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    def enqueue(self, audio: np.ndarray) -> None:
        self._q.put(audio)

    @property
    def busy(self) -> bool:
        return self._playing.is_set() or not self._q.empty()

    def stop(self) -> None:
        self._stop.set()
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        sd.stop()

    def _worker(self) -> None:
        while True:
            audio = self._q.get()
            if audio is None:
                continue
            self._stop.clear()
            self._playing.set()
            sd.play(audio, self.sample_rate)
            duration = len(audio) / self.sample_rate
            started = time.monotonic()
            while time.monotonic() - started < duration + 0.1:
                if self._stop.is_set():
                    break
                time.sleep(0.02)
            if self._q.empty():
                time.sleep(0.25)  # хвост, чтобы микрофон не поймал конец собственной фразы
            self._playing.clear()
