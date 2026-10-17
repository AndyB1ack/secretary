"""«Кэш голоса»: Мак наговаривает голосом Qwen3-TTS (Serena) набор фраз с эмоциями — на нём потом
обучаем свой лёгкий голос для телефона (Piper/VITS, эмоция = отдельный «диктор»).

  cd ~/Projects/secretary && source prototype/.venv/bin/activate
  python tools/voice_dataset.py            # ставь на ночь: ~3–4 часа, можно прерывать и продолжать

Шаги (каждый продолжается с места остановки):
  1. фразы  — пишет Gemma (локально), живая разговорная речь Миры, по эмоциям и темам → voice_dataset/sentences.tsv
  2. голос  — Qwen3-TTS озвучивает каждую фразу с нужной эмоцией → voice_dataset/wavs/*.wav (22 050 Гц)
  3. проверка — Whisper распознаёт запись; если она не совпала с текстом (бормотание, пропуски) — выбрасываем
  Итог: voice_dataset/metadata.csv в формате Piper: «файл|эмоция|текст».
"""
import csv
import random
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype"))
OUT = ROOT / "voice_dataset"
WAVS = OUT / "wavs"
SENT = OUT / "sentences.tsv"
META = OUT / "metadata.csv"
SR = 22050

from secretary.emotion import EMOTIONS  # noqa: E402

COUNTS = {"спокойно": 900}           # обычная речь — основа голоса
DEFAULT_COUNT = 120                   # каждой эмоции по ~10 минут
TOPICS = ["утро и кофе", "дорога на работу", "монтаж лифтов на объекте", "напоминание о задаче", "погода и море",
          "семья и мама", "кот Шницель", "выходные и отдых", "шутка про начальника", "еда и выпечка",
          "иврит и новые слова", "усталость после работы", "планы на вечер", "покупки и бытовые дела",
          "новости и технологии", "кино и музыка", "здоровье и спорт", "поездка и путешествие",
          "документы и бюрократия", "поддержка и забота", "вопросы собеседнику", "числа, время и даты"]


def make_sentences() -> None:
    from secretary.engines import make_llm
    cfg = yaml.safe_load(open(ROOT / "prototype" / "config.yaml", encoding="utf-8"))
    llm = make_llm(cfg["llm"], (ROOT / "prototype" / cfg["models_dir"]).resolve())
    have = {}
    if SENT.exists():
        for row in csv.reader(open(SENT, encoding="utf-8"), delimiter="\t"):
            have.setdefault(row[0], set()).add(row[1])
    f = open(SENT, "a", encoding="utf-8", newline="")
    w = csv.writer(f, delimiter="\t")
    for emo in EMOTIONS:
        need = COUNTS.get(emo, DEFAULT_COUNT)
        got = have.setdefault(emo, set())
        tries = 0
        while len(got) < need and tries < need:   # страховка от бесконечного цикла
            tries += 1
            topic = random.choice(TOPICS)
            prompt = (f"Напиши 10 разных реплик молодой женщины в живом разговоре с близким знакомым Андреем. "
                      f"Тема: {topic}. Тон: {emo}. Каждая реплика — 1–2 предложения, 5–25 слов, разговорная речь, "
                      "разные по построению: вопросы, восклицания, короткие и длинные. Числа пиши словами. "
                      "Только русские буквы, без латиницы, эмодзи и кавычек. Выведи списком, по одной на строке.")
            text = "".join(llm.stream_chat([{"role": "user", "content": prompt}], 0.95))
            added = 0
            for line in text.splitlines():
                s = re.sub(r"^\s*[\d\-–•*.)]+\s*", "", line).strip().strip('"«»')
                if not (15 <= len(s) <= 200) or re.search(r"[A-Za-z\d<>\[\]{}#*_]", s) or s in got:
                    continue
                if not re.search(r"[.!?…]$", s):
                    s += "."
                got.add(s); w.writerow([emo, s]); added += 1
            f.flush()
            print(f"  {emo}: {len(got)}/{need} (+{added}, тема «{topic}»)")
    f.close()


def norm(t: str) -> str:
    return " ".join(re.sub(r"[^а-я ]", " ", t.lower().replace("ё", "е")).split())


def synth_and_check() -> None:
    import librosa
    import torch
    from qwen_tts import Qwen3TTSModel
    from secretary.engines import make_stt

    cfg = yaml.safe_load(open(ROOT / "prototype" / "config.yaml", encoding="utf-8"))
    qc = cfg["tts"].get("qwen", {})
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        tts = Qwen3TTSModel.from_pretrained(qc.get("model", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"),
                                            device_map=dev, dtype=torch.float32, attn_implementation="sdpa")
    except Exception:
        tts = Qwen3TTSModel.from_pretrained(qc.get("model", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"),
                                            device_map="cpu", dtype=torch.float32, attn_implementation="sdpa")
    stt = make_stt(cfg["stt"], (ROOT / "prototype" / cfg["models_dir"]).resolve())
    WAVS.mkdir(parents=True, exist_ok=True)
    done = set()
    if META.exists():
        done = {r.split("|")[2].strip() for r in open(META, encoding="utf-8") if r.count("|") >= 2}
    rejected = OUT / "rejected.tsv"
    if rejected.exists():
        done |= {r.split("\t")[1].strip() for r in open(rejected, encoding="utf-8") if "\t" in r}
    rows = [r for r in csv.reader(open(SENT, encoding="utf-8"), delimiter="\t") if r[1] not in done]
    print(f"Озвучить: {len(rows)} фраз")
    speaker = qc.get("speaker", "Serena")
    style = qc.get("style", "")
    gen = dict(temperature=0.6, top_p=0.85, top_k=30, repetition_penalty=1.1,
               subtalker_temperature=0.6, subtalker_top_p=0.85)
    n0 = sum(1 for _ in open(META, encoding="utf-8")) if META.exists() else 0
    t_start = time.time()
    for i, (emo, text) in enumerate(rows):
        tone = f"{style}; {EMOTIONS[emo]}" if style else EMOTIONS[emo]
        wavs, sr = tts.generate_custom_voice(text=text, language="Russian", speaker=speaker, instruct=tone,
                                             max_new_tokens=int(len(text) * 1.3) + 24, **gen)
        audio = np.asarray(wavs[0], dtype=np.float32)
        heard = stt.transcribe(librosa.resample(audio, orig_sr=sr, target_sr=16000), "ru")
        score = SequenceMatcher(None, norm(text), norm(heard)).ratio()
        if score < 0.85:
            with open(rejected, "a", encoding="utf-8") as r:
                r.write(f"{emo}\t{text}\t{heard}\t{score:.2f}\n")
            print(f"  ✗ {score:.2f} {text[:50]} → {heard[:50]}")
            continue
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
        audio = audio / max(1e-6, float(np.abs(audio).max())) * 0.9
        name = f"m{n0:05d}"
        sf.write(WAVS / f"{name}.wav", audio, SR)
        with open(META, "a", encoding="utf-8") as m:
            m.write(f"{name}|{emo}|{text}\n")
        n0 += 1
        left = (time.time() - t_start) / (i + 1) * (len(rows) - i - 1) / 60
        print(f"  ✓ [{emo}] {text[:60]}  (осталось ~{left:.0f} мин)")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print("== 1. Фразы (Gemma)")
    make_sentences()
    print("== 2–3. Голос и проверка (Qwen3-TTS + Whisper)")
    synth_and_check()
    n = sum(1 for _ in open(META, encoding="utf-8"))
    print(f"\nГотово: {n} записей в {OUT}. Дальше — обучение голоса (скажи Claude).")
