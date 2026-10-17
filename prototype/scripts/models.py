"""Поиск и скачивание моделей с Hugging Face (запускается на Mac, где есть интернет).

  python scripts/models.py search abliterated qwen3 8b      — найти модели GGUF
  python scripts/models.py files <репозиторий>               — список файлов
  python scripts/models.py get <репозиторий> [Q4_K_M]        — скачать файл нужного квантования
  python scripts/models.py list                              — что уже скачано
"""
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

MODELS = Path(__file__).resolve().parents[2] / "models"
api = HfApi()


def search(words: list[str]) -> None:
    query = " ".join(words + ["gguf"])
    found = list(api.list_models(search=" ".join(words), sort="downloads", limit=40))
    found = [m for m in found if "gguf" in m.id.lower()] or found
    print(f"Поиск: {query}\n")
    for m in found[:20]:
        print(f"{(m.downloads or 0):>9}  {m.id}")


def files(repo: str) -> list[str]:
    names = [f for f in api.list_repo_files(repo) if f.endswith(".gguf")]
    for n in names:
        print(n)
    return names


def get(repo: str, quant: str = "Q4_K_M") -> None:
    names = [f for f in api.list_repo_files(repo) if f.endswith(".gguf")]
    pick = [n for n in names if quant.lower() in n.lower() and "mmproj" not in n.lower()]
    if not pick:
        print(f"Нет файла {quant}. Есть:\n  " + "\n  ".join(names)); return
    name = sorted(pick, key=len)[0]
    MODELS.mkdir(exist_ok=True)
    print(f"↓ {repo}/{name}")
    path = hf_hub_download(repo_id=repo, filename=name, local_dir=MODELS)
    print(f"✓ {path}\nЗапуск:  python main.py --text --model {name}")


def ls() -> None:
    for f in sorted(MODELS.rglob("*.gguf")):
        print(f"{f.stat().st_size / 1e9:5.1f} ГБ  {f.relative_to(MODELS)}")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["list"]
    {"search": lambda: search(rest), "files": lambda: files(rest[0]),
     "get": lambda: get(*rest), "list": ls}[cmd]()
