"""Скачивает модели для прототипа в папку models/ (в git она не попадает).

Запуск:  python scripts/download_models.py
Если имя файла в репозитории Hugging Face поменялось, скрипт покажет список доступных файлов.
"""
from pathlib import Path

from huggingface_hub import hf_hub_download, list_repo_files

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"

DOWNLOADS = [
    # (репозиторий, файл, зачем)
    ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", "языковая модель, рабочий режим"),
    ("ggerganov/whisper.cpp", "ggml-small.bin", "распознавание речи"),
]


def main() -> None:
    MODELS.mkdir(exist_ok=True)
    for repo, filename, why in DOWNLOADS:
        target = MODELS / filename
        if target.exists():
            print(f"✓ {filename} уже есть")
            continue
        print(f"↓ {filename} ({why}) из {repo} ...")
        try:
            hf_hub_download(repo_id=repo, filename=filename, local_dir=MODELS)
            print(f"✓ {filename}")
        except Exception as exc:  # noqa: BLE001
            print(f"✗ не удалось скачать {filename}: {exc}")
            try:
                files = [f for f in list_repo_files(repo) if f.endswith((".gguf", ".bin"))]
                print("  Доступные файлы:", ", ".join(files[:30]))
            except Exception:  # noqa: BLE001
                pass
    print("\nSilero TTS и Silero VAD скачаются сами при первом запуске и закэшируются.")


if __name__ == "__main__":
    main()
