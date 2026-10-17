import os
from pathlib import Path

import numpy as np


class WhisperCppSTT:
    def __init__(self, model_path: Path, cfg: dict) -> None:
        from pywhispercpp.model import Model

        if not model_path.exists():
            raise FileNotFoundError(f"нет модели {model_path}. Запусти scripts/download_models.py")
        self.language = cfg.get("language", "ru")
        self.model = Model(
            str(model_path),
            n_threads=max(4, (os.cpu_count() or 8) - 2),
            print_progress=False,
            print_realtime=False,
        )

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> str:
        lang = language or self.language
        segments = self.model.transcribe(audio.astype(np.float32), language=lang)
        return " ".join(s.text.strip() for s in segments).strip()
