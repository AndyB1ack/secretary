"""Прослушивание женских русских офлайн-голосов на одной фразе — чтобы выбрать голос Миры.

  cd ~/Projects/secretary && source prototype/.venv/bin/activate
  pip install vosk-tts sherpa-onnx        # один раз
  python tools/voice_audition.py          → папка voice_samples/, открывается сама
  pip install -U qwen-tts                 # для «мощного» голоса с эмоциями (скачает ~6 ГБ моделей)
  python tools/voice_audition.py --qwen   → только Qwen3-TTS: придуманный голос + эмоции, с замером скорости

Кандидаты: Vosk TTS (все дикторы), Silero v5/v4 (baya, kseniya, xenia), Piper Irina (для сравнения).
"""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "voice_samples"
OUT.mkdir(exist_ok=True)
PHRASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else (
    "Андрей, по объекту Аргаман всё готово. Завтра в шесть утра бригада на месте. "
    "Слушай, а вечером ты свободен? Я бы с тобой поболтала. Ну что, договорились?")


def save(name: str, audio, sr: int, took: float) -> None:
    wav = OUT / f"{name}.wav"
    sf.write(wav, np.asarray(audio, dtype=np.float32), sr)
    mp3 = wav.with_suffix(".mp3")
    if subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-b:a", "128k", str(mp3)]).returncode == 0:
        wav.unlink()
    print(f"  ✓ {name}  (синтез {took:.1f} с)")


def vosk() -> None:
    print("Vosk TTS…")
    try:
        from vosk_tts import Model, Synth
        model = Model(lang="ru")
        synth = Synth(model)
        for sid in range(0, 6):
            try:
                t = time.time()
                tmp = OUT / "_tmp.wav"
                synth.synth(PHRASE, str(tmp), speaker_id=sid)
                a, sr = sf.read(tmp); tmp.unlink()
                save(f"vosk_{sid}", a, sr, time.time() - t)
            except Exception as e:  # дикторов меньше — выходим
                if sid == 0:
                    print("  ✗", e)
                break
    except Exception as e:
        print("  ✗ Vosk не получилось:", e)


def silero() -> None:
    print("Silero…")
    import torch
    for ver in ("v5_6_ru", "v5_ru"):
        try:
            model, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru", speaker=ver,
                                      trust_repo=True, force_reload=(ver == "v5_6_ru"))
        except Exception as e:
            print(f"  ✗ {ver}: {e}")
            continue
        for spk in ("baya", "kseniya", "xenia"):
            try:
                t = time.time()
                a = model.apply_tts(text=PHRASE, speaker=spk, sample_rate=48000, put_accent=True, put_yo=True)
                save(f"silero_{ver}_{spk}", a.numpy(), 48000, time.time() - t)
            except Exception as e:
                print(f"  ✗ {ver} {spk}: {e}")
        break  # достаточно самой новой версии


def piper() -> None:
    print("Piper Irina (то, что сейчас на телефоне)…")
    d = ROOT / "models" / "voice" / "vits-piper-ru_RU-irina-medium"
    if not d.exists():
        print("  — нет модели (появится после build_and_install.sh)"); return
    try:
        import sherpa_onnx
        tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(d / "ru_RU-irina-medium.onnx"),
                                                       tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data")))))
        t = time.time()
        a = tts.generate(PHRASE, sid=0, speed=1.0)
        save("piper_irina", a.samples, a.sample_rate, time.time() - t)
    except Exception as e:
        print("  ✗", e)


QWEN_VOICE = ("A young woman about 25, warm and lively, slightly playful, clear soft voice, "
              "natural conversational Russian, not a radio announcer")
QWEN_EMOTIONS = {
    "спокойно": ("Андрей, по объекту Аргаман всё готово. Завтра в шесть утра бригада на месте.", "calm, friendly"),
    "радостно": ("Ура, мы закрыли объект! Я так рада, честно, прямо прыгать хочется!", "very happy, excited, laughing a little"),
    "грустно": ("Ты сегодня совсем пропал... Я ждала, а ты даже не написал.", "sad, quiet, a bit hurt"),
    "обиженно": ("Ну и пожалуйста. Сам разбирайся со своими лифтами.", "offended, pouting, sulky"),
    "шёпотом": ("Тише... Иди сюда, я тебе кое-что скажу.", "whispering, intimate, soft"),
}


def qwen() -> None:
    print("Qwen3-TTS (придуманный голос + эмоции)…")
    import torch
    from qwen_tts import Qwen3TTSModel
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    for model_id, kind in (("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "design"),
                           ("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", "custom")):
        m = None
        for d in ([dev, "cpu"] if dev != "cpu" else ["cpu"]):
            try:
                print(f"  загружаю {model_id} на {d} (первый раз долго — скачивание)")
                m = Qwen3TTSModel.from_pretrained(model_id, device_map=d, dtype=torch.float32, attn_implementation="sdpa")
                break
            except Exception as e:
                print(f"  ✗ на {d}: {e}")
        if m is None:
            continue
        for name, (text, emo) in QWEN_EMOTIONS.items():
            try:
                t = time.time()
                if kind == "design":
                    wavs, sr = m.generate_voice_design(text=text, language="Russian", instruct=f"{QWEN_VOICE}. Emotion: {emo}.")
                else:
                    wavs, sr = m.generate_custom_voice(text=text, language="Russian", speaker="Serena", instruct=emo)
                took = time.time() - t
                save(f"qwen_{kind}_{name}", wavs[0], sr, took)
                print(f"     звук {len(wavs[0]) / sr:.1f} с — скорость {len(wavs[0]) / sr / took:.2f}× реального времени")
            except Exception as e:
                print(f"  ✗ {name}: {e}")
        del m


if __name__ == "__main__":
    if "--qwen" in sys.argv:
        sys.argv.remove("--qwen")
        qwen()
    else:
        vosk(); silero(); piper()
    print(f"\nГотово: {OUT}")
    subprocess.run(["open", str(OUT)])
