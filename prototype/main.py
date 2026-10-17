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
from secretary.knowledge import KnowledgeBase
from secretary.memory import Memory, consolidate
from secretary.mood import event_for_today, mood_for_today
from secretary.modes import ModeSwitcher, detect_practice
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
    persona.day_event = event_for_today(memory, persona.data.get("day_events", []))
    print(f"Настроение Миры сегодня: {persona.mood}")
    bus = EventBus()
    kb = KnowledgeBase(HERE / cfg.get("packs_dir", "../packs"))
    print(f"Документы: {kb.describe()}")
    if not kb.empty:
        kb.search("прогрев")  # грузим поисковую модель сразу, а не на первом вопросе
    return Conversation(persona, llm, bus, mode, cfg.get("history_turns", 20), memory, kb), bus


def start_auto_sync(conv: Conversation, every_hours: float = 6) -> None:
    """Сама подтягивает прогресс из Ivrit Trainer: при запуске и каждые N часов, если есть сеть."""
    import os
    url, tok = os.environ.get("IVRIT_URL"), os.environ.get("IVRIT_TOKEN")
    if not (url and tok and conv.practice):
        return
    db = conv.memory.db
    db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")

    def loop() -> None:
        while True:
            row = db.execute("SELECT value FROM kv WHERE key='ivrit_sync'").fetchone()
            last = float(row[0]) if row else 0.0
            if time.time() - last >= every_hours * 3600:
                try:
                    n = conv.practice.sync_from_app(url, tok)
                    db.execute("INSERT OR REPLACE INTO kv VALUES ('ivrit_sync', ?)", (str(time.time()),))
                    db.commit()
                    print(f"\n   [иврит: синхронизировано {n} слов из приложения]")
                except Exception:  # нет сети — попробуем позже
                    pass
            time.sleep(600)

    threading.Thread(target=loop, daemon=True).start()


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
        enable_emotions(conv, tts)
    switcher = ModeSwitcher()
    print(f"\n{conv.persona.name} на связи (режим {conv.mode}). Команды: /mode <режим>, /tutor he|en|off, "
          "/tasks, /done N, /remember, /forget, /memory, /quit\n"
          "Иврит: /talk, /scene [тема или id], /scenes, /lesson ID, /quiz, /word слово, /sync\n")
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
        if text in ("/tasks", "/memory", "/mood", "/talk", "/quiz", "/sync", "/scenes") or \
                text.split()[0] in ("/done", "/remember", "/forget", "/task", "/scene", "/lesson", "/word"):
            memory_command(conv, text); continue
        if text.startswith("/tutor"):
            arg = text.split()[-1]
            conv.persona.tutor = None if arg == "off" else {"language": arg}
            print(f"[репетитор: {arg}]"); continue
        mode, say, handled = switcher.handle(text, conv.mode)
        if mode:
            conv.set_mode(mode); print(f"[режим: {mode}]")
        if say:
            print(f"{conv.persona.name}: {say}")
            if speak:
                speaker.enqueue(tts.synthesize(say))
        if handled:
            continue
        print(f"{conv.persona.name}: ", end="", flush=True)
        t0 = time.monotonic()
        first = None
        for sentence in conv.respond(text):
            print(sentence, end=" ", flush=True)
            if speak:
                speaker.enqueue(tts.synthesize(sentence, conv.emotion))
                if first is None:
                    first = time.monotonic() - t0
        for h in conv.last_hits:
            if h.image:
                print(f"   🖼  {h.ref()}: {h.image}")
        if getattr(conv, "unknown_he", None):
            print(f"   ⚠ нет в словаре курса: {', '.join(conv.unknown_he)} — проверь (/word)")
        if getattr(conv, "bad_citations", None):
            print(f"   ⚠ ссылка на страницы {', '.join(conv.bad_citations)}, которых нет в найденном — проверь!")
        print(f"\n   [{_ms(time.monotonic() - t0)} всего" + (f", первый звук {_ms(first)}" if first else "") + "]")


def memory_command(conv: Conversation, text: str) -> None:
    m = conv.memory
    cmd, _, arg = text.partition(" ")
    pr = conv.practice
    if cmd == "/scene":
        conv.persona.tutor = {"language": "he"}
        print(f"  [сценка: {pr.set_scene(arg)}] — начинай или скажи «начинай»"); return
    if cmd == "/lesson":
        title = pr.set_lesson(arg)
        conv.persona.tutor = {"language": "he"}
        print(f"  [урок: {title}]" if title else "  нет такого урока (пример: /lesson L01)"); return
    if cmd == "/talk":
        pr.mode = "talk"; conv.persona.tutor = {"language": "he"}; print("  [разговор на иврите]"); return
    if cmd == "/quiz":
        pr.mode = "quiz"; conv.persona.tutor = {"language": "he"}; print("  [опрос по пройденному]"); return
    if cmd == "/word" and arg:
        hits = pr.lookup(arg)
        print("\n".join(f"  {t['nikud']} ({t['tr']}) — {t['ru']}  [{t['src']}]" for t in hits) or "  в курсе нет"); return
    if cmd == "/sync":
        import os
        url, tok = os.environ.get("IVRIT_URL"), os.environ.get("IVRIT_TOKEN")
        if not (url and tok):
            print("  задай IVRIT_URL (…/api/mira/progress) и IVRIT_TOKEN"); return
        print(f"  ✓ подтянуто слов из приложения: {pr.sync_from_app(url, tok)}"); return
    if cmd == "/scenes":
        for s in conv.tutor.course.get("scenarios", []):
            print(f"  {s.get('id')}: {s.get('title_ru')}")
        return
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


HEBREW = __import__("re").compile(r"[\u0590-\u05FF]+")
VOICE_HE_RULE = ("Голосовой режим: твой голос читает только русские буквы. Каждую фразу на иврите пиши так: "
                 "сначала иврит с огласовками, затем в скобках транслитерация РУССКИМИ буквами (не латиницей!), "
                 "например: שָׁלוֹם (шалом). Вслух прозвучит транслитерация, иврит Андрей увидит на экране.")
LATIN = __import__("re").compile(r"[A-Za-z]")


def enable_emotions(conv: Conversation, tts) -> None:
    """Голос умеет эмоции — просим Миру ставить метки тона."""
    if getattr(tts, "emotional", False):
        from secretary.emotion import PROMPT
        if PROMPT not in conv.persona.extra:
            conv.persona.extra.append(PROMPT)


def speakable(text: str) -> str:
    """Оставляет то, что русский голос может прочитать: без еврейских букв и латиницы."""
    t = HEBREW.sub("", text)
    t = __import__("re").sub(r"\([^()]*[A-Za-z][^()]*\)", "", t)  # скобки с латиницей целиком
    t = LATIN.sub("", t).replace("(", "").replace(")", "")
    t = __import__("re").sub(r"\s+", " ", t).strip(" ()—-,.!?:;")
    return t if __import__("re").search(r"[А-Яа-яЁё0-9]", t) else ""


def set_practice(conv: Conversation, practice: str, stt=None) -> None:
    if practice == "off":
        conv.persona.tutor = None
        if stt:
            stt.language = "ru"
        print("[практика иврита выключена]")
        return
    conv.persona.tutor = {"language": "he"}
    if practice == "scene":
        conv.practice.set_scene("")
    else:
        conv.practice.mode = practice
    if stt:
        stt.language = "auto"  # понимает и русский, и иврит
        if VOICE_HE_RULE not in conv.persona.extra:
            conv.persona.extra.append(VOICE_HE_RULE)
    print(f"[практика иврита: {practice}]")


def voice_loop(conv: Conversation, bus: EventBus, cfg: dict) -> None:
    from secretary.audio import Microphone, Speaker

    print("Загружаю распознавание речи, детектор и голос…")
    stt = make_stt(cfg["stt"], (HERE / cfg["models_dir"]).resolve())
    vad = make_vad(cfg["vad"])
    tts = make_tts(cfg["tts"], (HERE / cfg["models_dir"]).resolve())
    speaker = Speaker(tts.sample_rate)
    enable_emotions(conv, tts)
    barge_in = cfg["audio"].get("barge_in", False)

    tts_q: queue.Queue = queue.Queue()
    generating = threading.Event()
    timing = {"end_of_speech": 0.0, "first_audio_reported": True}

    def tts_worker() -> None:
        while True:
            item = tts_q.get()
            sentence, feel = item if isinstance(item, tuple) else (item, None)
            sentence = speakable(sentence)
            if not sentence:
                continue
            try:
                audio = tts.synthesize(sentence, feel)
            except Exception as exc:  # голос не смог прочитать фразу — пропускаем её, но не падаем
                print(f"   [голос пропустил фразу: {exc.__class__.__name__}]")
                continue
            if conv.cancelled:
                continue
            speaker.enqueue(audio)
            if not timing["first_audio_reported"]:
                timing["first_audio_reported"] = True
                print(f"   [первый звук через {_ms(time.monotonic() - timing['end_of_speech'])} после твоей фразы]")

    threading.Thread(target=tts_worker, daemon=True).start()
    switcher = ModeSwitcher()
    if conv.persona.tutor:
        set_practice(conv, conv.practice.mode, stt)

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
            practice = detect_practice(text)
            if practice:
                set_practice(conv, practice, stt)
                text = "Начинаем!" if practice != "off" else "Всё, хватит иврита на сегодня."
            mode, say, handled = switcher.handle(text, conv.mode)
            if mode:
                conv.set_mode(mode); print(f"[режим: {mode}]")
            if say:
                print(f"{conv.persona.name}: {say}")
                tts_q.put(say)
            if handled:
                return
            print(f"{conv.persona.name}: ", end="", flush=True)
            timing["first_audio_reported"] = False
            for sentence in conv.respond(text):
                print(sentence, end=" ", flush=True)
                tts_q.put((sentence, conv.emotion))
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
    p.add_argument("--practice", choices=["talk", "scene", "quiz"], default="talk", help="режим практики иврита")
    p.add_argument("--voice", choices=["silero", "f5", "qwen"], help="движок голоса (вместо config.yaml)")
    p.add_argument("--model", help="файл модели в models/ (вместо указанного в config.yaml)")
    args = p.parse_args()
    cfg = load_config()
    if args.voice:
        cfg["tts"]["engine"] = args.voice
    if args.model:
        cfg["llm"]["model"] = args.model
    conv, bus = build(cfg, args.mode, args.tutor)
    if conv.practice:
        conv.practice.mode = args.practice
    start_auto_sync(conv)
    if args.text:
        text_loop(conv, cfg, args.speak)
        finish(conv)
    else:
        voice_loop(conv, bus, cfg)


if __name__ == "__main__":
    main()
    # Выходим сразу: иначе Metal (llama.cpp) падает с GGML_ASSERT при очистке — безвредно, но пугает.
    import os
    import sys
    sys.stdout.flush()
    os._exit(0)
