"""Qwen3-TTS: живой голос с эмоциями по инструкции (Apache 2.0). Модель качается с Hugging Face один раз.

CustomVoice — готовые голоса (Serena и др.) + инструкция тона; VoiceDesign (1.7B) — голос по описанию.
"""
import numpy as np

from ..emotion import DEFAULT, EMOTIONS


class QwenTTS:
    emotional = True

    def __init__(self, cfg: dict) -> None:
        import torch
        from qwen_tts import Qwen3TTSModel

        self.model_id = cfg.get("model", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
        self.speaker = cfg.get("speaker", "Serena")
        self.voice = cfg.get("voice_description", "")
        self.style = cfg.get("style", "")           # постоянная добавка к тону: «young woman, lively»
        self.design = "VoiceDesign" in self.model_id
        dev = cfg.get("device") or ("mps" if torch.backends.mps.is_available() else "cpu")
        try:
            self.model = Qwen3TTSModel.from_pretrained(self.model_id, device_map=dev, dtype=torch.float32,
                                                       attn_implementation="sdpa")
        except Exception:
            self.model = Qwen3TTSModel.from_pretrained(self.model_id, device_map="cpu", dtype=torch.float32,
                                                       attn_implementation="sdpa")
        self.sample_rate = 24000
        self.synthesize("Привет.")  # прогрев, заодно узнаём частоту

    def synthesize(self, text: str, emotion: str | None = None) -> np.ndarray:
        tone = EMOTIONS.get(emotion or DEFAULT, EMOTIONS[DEFAULT])
        if self.style:
            tone = f"{self.style}; {tone}"
        if self.design:
            wavs, sr = self.model.generate_voice_design(text=text, language="Russian",
                                                        instruct=f"{self.voice}. Emotion: {tone}.")
        else:
            wavs, sr = self.model.generate_custom_voice(text=text, language="Russian", speaker=self.speaker,
                                                        instruct=tone)
        self.sample_rate = sr
        return np.asarray(wavs[0], dtype=np.float32)
