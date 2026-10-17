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
text = p.system_prompt("work")
out = ROOT / "android" / "app" / "src" / "main" / "assets" / "system_prompt.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(text, encoding="utf-8")
print(f"✓ {out.relative_to(ROOT)}: {len(text)} символов")
