import numpy as np
import torch


class SileroTTS:
    def __init__(self, cfg: dict) -> None:
        self.sample_rate = cfg.get("sample_rate", 48000)
        self.speaker = cfg.get("speaker", "xenia")
        torch.set_num_threads(4)
        self.model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language=cfg.get("language", "ru"),
            speaker=cfg.get("model_id", "v4_ru"),
            trust_repo=True,
        )

    def synthesize(self, text: str) -> np.ndarray:
        audio = self.model.apply_tts(text=text, speaker=self.speaker, sample_rate=self.sample_rate)
        return audio.numpy().astype(np.float32)
