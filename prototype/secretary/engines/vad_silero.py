import numpy as np
import torch

from .base import SAMPLE_RATE_IN


class SileroVAD:
    def __init__(self, cfg: dict) -> None:
        from silero_vad import VADIterator, load_silero_vad

        self._model = load_silero_vad()
        self._it = VADIterator(
            self._model,
            threshold=cfg.get("threshold", 0.5),
            sampling_rate=SAMPLE_RATE_IN,
            min_silence_duration_ms=cfg.get("min_silence_ms", 700),
        )

    def reset(self) -> None:
        self._it.reset_states()

    def process(self, chunk: np.ndarray) -> str | None:
        res = self._it(torch.from_numpy(chunk.astype(np.float32)))
        if not res:
            return None
        return "start" if "start" in res else "end"
