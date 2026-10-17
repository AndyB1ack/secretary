"""Прослушать голоса Silero по очереди.  python scripts/voices.py [фраза]"""
import sys
import time
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secretary.engines.tts_silero import SileroTTS  # noqa: E402

PHRASE = " ".join(sys.argv[1:]) or "Привет, Андрей. Я соскучилась. Как прошёл день на объекте?"

for speaker in ["xenia", "baya", "kseniya"]:
    tts = SileroTTS({"speaker": speaker})
    for rate in ["medium", "slow"]:
        text = f'<speak><prosody rate="{rate}" pitch="medium">{PHRASE}</prosody></speak>'
        print(f"▶ {speaker}, темп {rate}")
        audio = tts.model.apply_tts(ssml_text=text, speaker=speaker, sample_rate=tts.sample_rate)
        sd.play(audio.numpy(), tts.sample_rate); sd.wait(); time.sleep(0.6)
