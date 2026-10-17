#!/bin/bash
# Установка прототипа Миры на Mac (Apple Silicon). Запуск: bash prototype/scripts/setup_mac.sh
set -e
cd "$(dirname "$0")/.."

PY=""
for c in python3.12 python3.11 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 "$HOME/.homebrew/bin/python3.12" "$HOME/.homebrew/bin/python3.11"; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Нужен Python 3.11 или 3.12. Установи: brew install python@3.12 — и запусти скрипт снова."; exit 1
fi
echo "Python: $($PY --version)"

[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
echo "Ставлю библиотеки (несколько минут)…"
CMAKE_ARGS="-DGGML_METAL=on" pip install -q -r requirements.txt
echo "Скачиваю модели (~3 ГБ)…"
python scripts/download_models.py
python -m pip install -q pytest && python -m pytest -q tests
echo
echo "Готово. Первый запуск (переписка):"
echo "  cd \"$(pwd)\" && source .venv/bin/activate && python main.py --text"
