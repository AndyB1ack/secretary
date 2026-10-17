"""Эмоции голоса: Мира ставит в ответе метку тона [радостно], голос с эмоциями (Qwen3-TTS) её исполняет."""
import re

# метка (по-русски, так модели проще) → инструкция для Qwen3-TTS
EMOTIONS = {
    "спокойно": "calm, warm, friendly",
    "радостно": "happy, cheerful, smiling",
    "весело": "playful, laughing a little, joking",
    "нежно": "tender, soft, affectionate",
    "грустно": "sad, quiet, a little down",
    "обиженно": "offended, pouting, sulky",
    "удивлённо": "surprised, amazed",
    "строго": "serious, firm, businesslike",
    "устало": "tired, slow, sighing",
    "шёпотом": "whispering, intimate, very soft",
    "игриво": "flirty, playful, teasing",
}
DEFAULT = "спокойно"
MOOD_TO_EMOTION = {"отличное": "радостно", "ровное": "спокойно", "задумчивое": "спокойно",
                   "грустное": "грустно", "немного обиженное": "обиженно"}

PROMPT = ("Голос: твой ответ озвучивается живым голосом с эмоциями. В начале ответа (и там, где тон меняется) "
          "ставь метку тона в квадратных скобках, одну из: " + ", ".join(f"[{k}]" for k in EMOTIONS) +
          ". Метку не произносят и не объясняют. Пример: «[весело] Ну ты даёшь! [нежно] Я рада, что ты пришёл.»")

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
