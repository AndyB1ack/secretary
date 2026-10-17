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
        # осторожная выборка: при высокой «температуре» модель бормочет лишние слова
        self.gen = dict(temperature=cfg.get("temperature", 0.6), top_p=cfg.get("top_p", 0.85), top_k=30,
                        repetition_penalty=1.1, subtalker_temperature=cfg.get("temperature", 0.6),
                        subtalker_top_p=cfg.get("top_p", 0.85))
        self.sample_rate = 24000
        self.synthesize("Привет.")  # прогрев, заодно узнаём частоту

    def synthesize(self, text: str, emotion: str | None = None) -> np.ndarray:
        tone = EMOTIONS.get(emotion or DEFAULT, EMOTIONS[DEFAULT])
        if self.style:
            tone = f"{self.style}; {tone}"
        # предел длины звука по длине текста (~12 кадров/с), чтобы не договаривала «от себя» после фразы
        gen = dict(self.gen, max_new_tokens=int(len(text) * 1.3) + 24)
        if self.design:
            wavs, sr = self.model.generate_voice_design(text=text, language="Russian",
                                                        instruct=f"{self.voice}. Emotion: {tone}.", **gen)
        else:
            wavs, sr = self.model.generate_custom_voice(text=text, language="Russian", speaker=self.speaker,
                                                        instruct=tone, **gen)
        self.sample_rate = sr
        return np.asarray(wavs[0], dtype=np.float32)
