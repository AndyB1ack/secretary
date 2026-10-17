"""Эмоции голоса: Мира ставит в ответе метку тона [радостно], голос с эмоциями (Qwen3-TTS) её исполняет."""
import re

# метка (по-русски, так модели проще) → инструкция для Qwen3-TTS
EMOTIONS = {   # мягкие формулировки: Qwen легко переигрывает
    "спокойно": "natural relaxed conversational tone, not exaggerated",
    "радостно": "slightly happy, warm smile in the voice",
    "весело": "light playful tone, a hint of laughter",
    "нежно": "soft and tender, gentle",
    "грустно": "a little sad, quieter",
    "обиженно": "slightly offended, a bit sulky",
    "удивлённо": "mildly surprised",
    "строго": "calm and businesslike, firm",
    "устало": "a little tired, slower",
    "шёпотом": "whispering softly",
    "игриво": "playful, a little flirty",
}
DEFAULT = "спокойно"
MOOD_TO_EMOTION = {"отличное": "радостно", "ровное": "спокойно", "задумчивое": "спокойно",
                   "грустное": "грустно", "немного обиженное": "обиженно"}

PROMPT = ("Голос: твой ответ озвучивается живым голосом. Обычная речь — без меток. Только когда эмоция правда заметна, "
          "поставь перед фразой метку тона в квадратных скобках, одну из: " + ", ".join(f"[{k}]" for k in EMOTIONS) +
          ". Не больше одной метки на ответ, не переигрывай. Метку не произносят. Пример: «[весело] Ну ты даёшь!»")

_TAG = re.compile(r"\[\s*([а-яё]+)\s*\]", re.IGNORECASE)


def extract(sentence: str, current: str) -> tuple[str, str]:
    """Убирает метки из фразы; возвращает (чистая фраза, эмоция для неё)."""
    emo = current
    for m in _TAG.finditer(sentence):
        word = m.group(1).lower().replace("e", "е")
        if word in EMOTIONS:
            emo = word
    clean = _TAG.sub("", sentence)
    return re.sub(r"\s{2,}", " ", clean).strip(), emo


def strip(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _TAG.sub("", text)).strip()
