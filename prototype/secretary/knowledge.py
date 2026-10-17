"""База знаний: поиск по пакетам .kpack (ADR 0004). Офлайн, многоязычно."""
import json
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, file TEXT, title TEXT, version TEXT, lang TEXT, pages INTEGER);
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, doc_id INTEGER, page INTEGER, lang TEXT,
                                   text TEXT, text_ru TEXT, emb BLOB);
CREATE TABLE IF NOT EXISTS images (id INTEGER PRIMARY KEY, doc_id INTEGER, page INTEGER, file TEXT,
                                   caption TEXT, description TEXT, keywords TEXT, emb BLOB);
"""


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def detect_lang(text: str) -> str:
    counts = {
        "he": len(re.findall(r"[֐-׿]", text)),
        "ru": len(re.findall(r"[А-Яа-яЁё]", text)),
        "zh": len(re.findall(r"[一-鿿]", text)),
        "en": len(re.findall(r"[A-Za-z]", text)),
    }
    lang, n = max(counts.items(), key=lambda kv: kv[1])
    return lang if n else ""


class Embedder:
    """multilingual-e5: запрос и документ с разными префиксами. На телефоне — та же модель в ONNX."""

    def __init__(self, model: str = "intfloat/multilingual-e5-small") -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model)

    def passage(self, text: str) -> np.ndarray:
        return self.model.encode("passage: " + text, normalize_embeddings=True)

    def query(self, text: str) -> np.ndarray:
        return self.model.encode("query: " + text, normalize_embeddings=True)


@dataclass
class Hit:
    kind: str          # text | image
    score: float
    doc: str
    page: int
    text: str
    image: Path | None = None

    def ref(self) -> str:
        return f"«{self.doc}», стр. {self.page}" + (" (рисунок)" if self.kind == "image" else "")


class Pack:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.dir = Path(tempfile.mkdtemp(prefix=f"{path.stem}_"))
        with zipfile.ZipFile(path) as z:
            z.extractall(self.dir)
        self.db = sqlite3.connect(self.dir / "pack.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.meta = {r["key"]: r["value"] for r in self.db.execute("SELECT * FROM meta")}
        docs = {r["id"]: r["title"] for r in self.db.execute("SELECT id, title FROM docs")}
        self.items: list[tuple[str, str, int, str, Path | None]] = []
        vecs = []
        for r in self.db.execute("SELECT * FROM chunks"):
            self.items.append(("text", docs[r["doc_id"]], r["page"], r["text_ru"] or r["text"], None))
            vecs.append(from_blob(r["emb"]))
        for r in self.db.execute("SELECT * FROM images"):
            kw = ", ".join(json.loads(r["keywords"] or "[]"))
            desc = f"{r['caption']}: {r['description']}" + (f" [{kw}]" if kw else "")
            self.items.append(("image", docs[r["doc_id"]], r["page"], desc, self.dir / "images" / r["file"]))
            vecs.append(from_blob(r["emb"]))
        self.matrix = np.vstack(vecs) if vecs else np.zeros((0, 1), dtype=np.float32)


class KnowledgeBase:
    def __init__(self, packs_dir: Path, embedder=None, min_score: float = 0.80) -> None:
        self.packs = [Pack(p) for p in sorted(Path(packs_dir).glob("*.kpack"))] if Path(packs_dir).exists() else []
        self.min_score = min_score  # у e5 «похоже по теме» начинается примерно с 0.8
        self._embedder = embedder

    @property
    def empty(self) -> bool:
        return not any(len(p.items) for p in self.packs)

    def describe(self) -> str:
        if self.empty:
            return "база документов пуста — у тебя НЕТ ни одной инструкции, схемы или файла"
        return "подключены пакеты: " + ", ".join(
            f"{p.meta.get('brand', '')} {p.meta.get('model', '')}".strip() or p.path.stem for p in self.packs)

    def search(self, query: str, k: int = 4) -> list[Hit]:
        if self.empty:
            return []
        if self._embedder is None:
            self._embedder = Embedder(self.packs[0].meta.get("embed_model", "intfloat/multilingual-e5-small"))
        q = self._embedder.query(query)
        hits: list[Hit] = []
        for p in self.packs:
            if not len(p.items):
                continue
            scores = p.matrix @ q
            for i in np.argsort(-scores)[:k]:
                kind, doc, page, text, img = p.items[i]
                hits.append(Hit(kind, float(scores[i]), doc, page, text, img))
        hits = [h for h in sorted(hits, key=lambda h: -h.score) if h.score >= self.min_score]
        return hits[:k]

    @staticmethod
    def prompt_block(hits: list[Hit]) -> str:
        if not hits:
            return ("По этому вопросу в базе ничего не нашлось. Скажи честно, что в твоей базе этого нет, "
                    "и предложи спросить облако. Не выдумывай.")
        lines = ["Найдено в документах (ссылайся ТОЛЬКО на эти фрагменты, номер страницы бери отсюда):"]
        for i, h in enumerate(hits, 1):
            lines.append(f"[{i}] {h.ref()}: {h.text[:700]}")
        lines.append("Если есть рисунок — скажи: «смотри рисунок на экране», он будет показан.")
        return "\n".join(lines)


def check_citations(answer: str, hits: list[Hit]) -> list[str]:
    """Страницы, на которые Мира сослалась, но которых нет в найденных фрагментах (признак выдумки)."""
    allowed = {h.page for h in hits}
    cited = {int(n) for n in re.findall(r"стр(?:\.|аниц[аеуы])\s*(\d+)", answer)}
    return [str(p) for p in sorted(cited - allowed)]
