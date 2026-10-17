"""Сравнение голосов на одной фразе: Silero (xenia) и F5-TTS (живой, по образцу).

  python scripts/voice_compare.py --record     — записать образец голоса (15 секунд)
  python scripts/voice_compare.py --from файл.mp3 [--start 60]  — взять образец из готовой записи
                                                (вырезает 15 с с указанной секунды и распознаёт текст)
  python scripts/voice_compare.py              — сравнить
  python scripts/voice_compare.py "своя фраза"
"""
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
VOICES = HERE.parent / "persona" / "voices"
REF_WAV, REF_TXT = VOICES / "mira_ref.wav", VOICES / "mira_ref.txt"

REF_SCRIPT = ("Привет! Меня зовут Мира. Сегодня отличный день, и я рада тебя слышать. "
              "Давай посмотрим, что у нас по плану, а потом немного отдохнём.")
PHRASE = "Привет, Андрей. Я соскучилась. Как прошёл день на объекте? Рассказывай, я вся внимание."


def record() -> None:
    VOICES.mkdir(parents=True, exist_ok=True)
    print("Прочитай спокойно и с улыбкой, когда начнётся запись:\n\n  " + REF_SCRIPT + "\n")
    for i in (3, 2, 1):
        print(f"  {i}…"); time.sleep(1)
    print("● Запись 15 секунд")
    audio = sd.rec(int(15 * 24000), samplerate=24000, channels=1, dtype="float32"); sd.wait()
    audio = audio[:, 0]
    idx = np.where(np.abs(audio) > 0.02)[0]  # обрезаем тишину по краям
    if len(idx):
        audio = audio[max(0, idx[0] - 2400): idx[-1] + 4800]
    sf.write(REF_WAV, audio, 24000)
    REF_TXT.write_text(REF_SCRIPT, encoding="utf-8")
    print(f"✓ Сохранено {REF_WAV.name} ({len(audio) / 24000:.1f} с). Прослушиваю:")
    sd.play(audio, 24000); sd.wait()


def from_file(path: str, start: float) -> None:
    import librosa

    VOICES.mkdir(parents=True, exist_ok=True)
    if path.startswith("http"):
        import urllib.request
        local = VOICES / Path(path).name
        if not local.exists():
            print(f"↓ скачиваю {local.name}…")
            urllib.request.urlretrieve(path, local)
        path = str(local)
    audio, _ = librosa.load(path, sr=24000, mono=True, offset=start, duration=15)
    audio = audio / max(1e-6, float(np.abs(audio).max())) * 0.9
    sf.write(REF_WAV, audio, 24000)
    print(f"✓ Вырезал {len(audio) / 24000:.1f} с начиная с {start:.0f}-й секунды. Распознаю текст…")
    import yaml
    from secretary.engines import make_stt

    cfg = yaml.safe_load(open(HERE / "config.yaml", encoding="utf-8"))
    stt = make_stt(cfg["stt"], (HERE / cfg["models_dir"]).resolve())
    text = stt.transcribe(librosa.resample(audio, orig_sr=24000, target_sr=16000), "ru")
    REF_TXT.write_text(text, encoding="utf-8")
    print(f"Текст образца: {text}\nСлушаем образец:")
    sd.play(audio, 24000); sd.wait()


def compare(phrase: str, nfe: int | None = None, only_f5: bool = False) -> None:
    import yaml
    from secretary.engines import make_tts

    cfg = yaml.safe_load(open(HERE / "config.yaml", encoding="utf-8"))
    models = (HERE / cfg["models_dir"]).resolve()
    if not REF_WAV.exists():
        print("Нет образца голоса. Сначала: python scripts/voice_compare.py --record"); return
    for engine in (["f5"] if only_f5 else ["silero", "f5"]):
        c = dict(cfg["tts"], engine=engine)
        c["f5"] = {**c["f5"], "ref_audio": REF_WAV, "ref_text": REF_TXT}
        if nfe:
            c["f5"]["nfe_step"] = nfe
        print(f"\nЗагружаю {engine}…")
        tts = make_tts(c, models)
        tts.synthesize("Тест.")  # прогрев
        t = time.monotonic()
        audio = tts.synthesize(phrase)
        dt = time.monotonic() - t
        label = f"{engine} (nfe {c['f5']['nfe_step']})" if engine == "f5" else engine
        print(f"▶ {label}: синтез {dt:.1f} с на {len(audio) / tts.sample_rate:.1f} с речи")
        sd.play(audio, tts.sample_rate); sd.wait(); time.sleep(0.8)


if __name__ == "__main__":
    if "--record" in sys.argv:
        record()
    elif "--from" in sys.argv:
        a = sys.argv
        start = float(a[a.index("--start") + 1]) if "--start" in a else 30.0
        from_file(a[a.index("--from") + 1], start)
    else:
        a = sys.argv[1:]
        nfe = int(a[a.index("--nfe") + 1]) if "--nfe" in a else None
        words = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--nfe")]
        compare(" ".join(words) or PHRASE, nfe, only_f5="--f5" in a)
