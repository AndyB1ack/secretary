"""Собирает системный промпт Миры для телефона из persona/mira.yaml (один источник правды).

  python tools/export_prompt.py  → android/app/src/main/assets/system_prompt.txt
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype"))
from secretary.persona import Persona  # noqa: E402

p = Persona.load(ROOT / "persona" / "mira.yaml")
p.docs_status = "на телефоне база документов пока не подключена — у тебя НЕТ инструкций и схем"
text = p.system_prompt("work", compact=True)  # на телефоне чтение промпта дорогое — короткая версия
out = ROOT / "android" / "app" / "src" / "main" / "assets" / "system_prompt.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(text, encoding="utf-8")
print(f"✓ {out.relative_to(ROOT)}: {len(text)} символов")
import json  # noqa: E402
topics = [{"keywords": t["keywords"], "story": t["story"].strip()} for t in (p.life.get("topics") or {}).values()]
(out.parent / "life.json").write_text(json.dumps(topics, ensure_ascii=False), encoding="utf-8")
print(f"✓ история жизни: {len(topics)} тем")
pitch = p.data["modes"]["work"].get("voice_pitch", 1.0)  # пока на телефоне только рабочий режим
(out.parent / "voice_pitch.txt").write_text(str(pitch), encoding="utf-8")
print(f"✓ высота голоса: {pitch}")
