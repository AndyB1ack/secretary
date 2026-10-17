"""Движки за интерфейсами. Новая модель — новый файл здесь и строка в config.yaml."""
from .base import LLM, STT, TTS, VAD


def make_llm(cfg: dict, models_dir) -> LLM:
    if cfg["engine"] == "llamacpp":
        from .llm_llamacpp import LlamaCppLLM
        return LlamaCppLLM(models_dir / cfg["model"], cfg)
    raise ValueError(f"неизвестный движок LLM: {cfg['engine']}")


def make_stt(cfg: dict, models_dir) -> STT:
    if cfg["engine"] == "whispercpp":
        from .stt_whispercpp import WhisperCppSTT
        return WhisperCppSTT(models_dir / cfg["model"], cfg)
    raise ValueError(f"неизвестный движок STT: {cfg['engine']}")


def make_vad(cfg: dict) -> VAD:
    if cfg["engine"] == "silero":
        from .vad_silero import SileroVAD
        return SileroVAD(cfg)
    raise ValueError(f"неизвестный движок VAD: {cfg['engine']}")


def make_tts(cfg: dict) -> TTS:
    if cfg["engine"] == "silero":
        from .tts_silero import SileroTTS
        return SileroTTS(cfg)
    raise ValueError(f"неизвестный движок TTS: {cfg['engine']}")
