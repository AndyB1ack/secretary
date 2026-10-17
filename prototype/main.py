"""Запуск прототипа Миры.

  python main.py              — голосовой режим (микрофон → Мира → динамик)
  python main.py --text       — переписка в терминале (удобно для отладки промптов)
  python main.py --text --speak  — переписка, но Мира отвечает голосом
  --mode work|evening|private|weekend   стартовый режим
  --tutor he|en                         включить слой репетитора
"""
import argparse
import collections
import queue
import threading
import time
from pathlib import Path

import numpy as np
import yaml

from secretary import events as ev
from secretary.conversation import Conversation
from secretary.engines import make_llm, make_stt, make_tts, make_vad
from secretary.events import EventBus
from secretary.memory import Memory, consolidate
from secretary.mood import mood_for_today
from secretary.modes import detect_mode_command
from secretary.persona import Persona

HERE = Path(__file__).resolve().parent


def load_config() -> dict:
    with open(HERE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build(cfg: dict, mode: str, tutor: str | None) -> tuple[Conversation, EventBus]:
    persona = Persona.load(HERE / cfg["persona"])
    if tutor:
        persona.tutor = {"language": tutor}
    models_dir = (HERE / cfg["models_dir"]).resolve()
    print(f"Загружаю языковую модель {cfg['llm']['model']}…")
    llm = make_llm(cfg["llm"], models_dir)
    memory = Memory(HERE / cfg.get("memory_db", "data/mira.db"))
    pending = memory.unsummarized_sessions()
    if pending:  # «сон»: дожимаем разговоры, которые не успели сжать
        print(f"Разбираю память за прошлые разговоры ({len(pending)})…")
        for s in pending:
            consolidate(memory, llm, s)
    persona.mood, persona.mood_reason = mood_for_today(memory)
    print(f"Настроение Миры сегодня: {persona.mood}")
    bus = EventBus()
    return Conversation(persona, llm, bus, mode, cfg.get("history_turns", 20), memory), bus


def finish(conv: Conversation) -> None:
    """При выходе сжимаем разговор в память."""
    if conv.memory:
        print("\nЗапоминаю разговор…")
        data = consolidate(conv.memory, conv.llm)
        if data:
            n_f, n_t = len(data.get("facts") or []), len(data.get("tasks") or [])
            print(f"✓ {data.get('summary', '')}  [фактов: {n_f}, задач: {n_t}]")


def text_loop(conv: Conversation, cfg: dict, speak: bool) -> None:
    speaker = tts = None
    if speak:
        from secretary.audio import Speaker
        tts = make_tts(cfg["tts"], (HERE / cfg["models_dir"]).resolve())
        speaker = Speaker(tts.sample_rate)
    print(f"\n{conv.persona.name} на связи (режим {conv.mode}). Команды: /mode <режим>, /tutor he|en|off, "
          "/tasks, /done N, /remember факт, /forget слово, /memory, /quit\n")
    while True:
        try:
            text = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text.startswith("/mode "):
            conv.set_mode(text.split(maxsplit=1)[1]); print(f"[режим: {conv.mode}]"); continue
        if text in ("/tasks", "/memory", "/mood") or text.split()[0] in ("/done", "/remember", "/forget", "/task"):
            memory_command(conv, text); continue
        if text.startswith("/tutor"):
            arg = text.split()[-1]
            conv.persona.tutor = None if arg == "off" else {"language": arg}
            print(f"[репетитор: {arg}]"); continue
        if (mode := detect_mode_command(text)):
            conv.set_mode(mode); print(f"[режим: {mode}]")
        print(f"{conv.persona.name}: ", end="", flush=True)
        t0 = time.monotonic()
        first = None
        for sentence in conv.respond(text):
            print(sentence, end=" ", flush=True)
            if speak:
                speaker.enqueue(tts.synthesize(sentence))
                if first is None:
                    first = time.monotonic() - t0
        print(f"\n   [{_ms(time.monotonic() - t0)} всего" + (f", первый звук {_ms(first)}" if first else "") + "]")


def memory_command(conv: Conversation, text: str) -> None:
    m = conv.memory
    cmd, _, arg = text.partition(" ")
    if cmd == "/tasks":
        tasks = m.open_tasks()
        print("\n".join(f"  [{t['id']}] {t['title']}" + (f" — до {t['due']}" if t['due'] else "") for t in tasks)
              or "  Открытых задач нет.")
    elif cmd == "/task" and arg:
        print(f"  ✓ задача [{m.add_task(arg)}] {arg}")
    elif cmd == "/done" and arg.isdigit():
        print("  ✓ выполнено" if m.complete_task(int(arg)) else "  нет такой открытой задачи")
    elif cmd == "/remember" and arg:
        m.add_fact(arg, "private" if conv.mode == "private" else "work"); print("  ✓ запомнила")
    elif cmd == "/forget" and arg:
        print(f"  забыто фактов: {m.forget(arg)}")
    elif cmd == "/memory":
        print(m.context_block(conv.mode))
    elif cmd == "/mood":
        print(f"  {conv.persona.mood} — {conv.persona.mood_reason}")


def voice_loop(conv: Conversation, bus: EventBus, cfg: dict) -> None:
    from secretary.audio import Microphone, Speaker

    print("Загружаю распознавание речи, детектор и голос…")
    stt = make_stt(cfg["stt"], (HERE / cfg["models_dir"]).resolve())
    vad = make_vad(cfg["vad"])
    tts = make_tts(cfg["tts"], (HERE / cfg["models_dir"]).resolve())
    speaker = Speaker(tts.sample_rate)
    barge_in = cfg["audio"].get("barge_in", False)

    tts_q: queue.Queue[str] = queue.Queue()
    generating = threading.Event()
    timing = {"end_of_speech": 0.0, "first_audio_reported": True}

    def tts_worker() -> None:
        while True:
            sentence = tts_q.get()
            audio = tts.synthesize(sentence)
            if conv.cancelled:
                continue
            speaker.enqueue(audio)
            if not timing["first_audio_reported"]:
                timing["first_audio_reported"] = True
                print(f"   [первый звук через {_ms(time.monotonic() - timing['end_of_speech'])} после твоей фразы]")

    threading.Thread(target=tts_worker, daemon=True).start()

    def handle(audio: np.ndarray) -> None:
        generating.set()
        try:
            t = time.monotonic()
            text = stt.transcribe(audio)
            stt_ms = time.monotonic() - t
            if not text:
                return
            print(f"\nТы: {text}   [распознано за {_ms(stt_ms)}]")
            bus.emit(ev.USER_SAID, text=text, stt_ms=int(stt_ms * 1000))
            if (mode := detect_mode_command(text)):
                conv.set_mode(mode); print(f"[режим: {mode}]")
            print(f"{conv.persona.name}: ", end="", flush=True)
            timing["first_audio_reported"] = False
            for sentence in conv.respond(text):
                print(sentence, end=" ", flush=True)
                tts_q.put(sentence)
            print()
        finally:
            generating.clear()

    def interrupt() -> None:
        conv.cancel()
        speaker.stop()
        while not tts_q.empty():
            tts_q.get_nowait()

    print(f"\n{conv.persona.name} слушает (режим {conv.mode}). Говори. Ctrl+C — выход."
          + ("" if barge_in else " Перебивание выключено: дождись, пока она договорит.") + "\n")
    pre = collections.deque(maxlen=10)  # ~0.3 с до начала речи, чтобы не обрезать первое слово
    buf: list[np.ndarray] = []
    recording = False
    try:
        for chunk in Microphone().chunks():
            busy = speaker.busy or generating.is_set()
            if busy and not barge_in:
                vad.reset(); pre.clear(); recording = False
                continue
            r = vad.process(chunk)
            pre.append(chunk)
            if recording:
                buf.append(chunk)
            if r == "start" and not recording:
                if busy:
                    interrupt()
                recording, buf = True, list(pre)
            elif r == "end" and recording:
                recording = False
                timing["end_of_speech"] = time.monotonic()
                audio = np.concatenate(buf)
                threading.Thread(target=handle, args=(audio,), daemon=True).start()
    except KeyboardInterrupt:
        print("\nПока!")
    finish(conv)


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} мс" if seconds < 1 else f"{seconds:.1f} с"


def main() -> None:
    p = argparse.ArgumentParser(description="Прототип Миры")
    p.add_argument("--text", action="store_true", help="переписка в терминале")
    p.add_argument("--speak", action="store_true", help="в режиме --text отвечать голосом")
    p.add_argument("--mode", default="work", choices=["work", "evening", "private", "weekend"])
    p.add_argument("--tutor", choices=["he", "en"])
    p.add_argument("--voice", choices=["silero", "f5"], help="движок голоса (вместо config.yaml)")
    p.add_argument("--model", help="файл модели в models/ (вместо указанного в config.yaml)")
    args = p.parse_args()
    cfg = load_config()
    if args.voice:
        cfg["tts"]["engine"] = args.voice
    if args.model:
        cfg["llm"]["model"] = args.model
    conv, bus = build(cfg, args.mode, args.tutor)
    if args.text:
        text_loop(conv, cfg, args.speak)
        finish(conv)
    else:
        voice_loop(conv, bus, cfg)


if __name__ == "__main__":
    main()
