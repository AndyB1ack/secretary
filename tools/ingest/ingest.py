"""Сборка пакета знаний (.kpack) из PDF-документов по одной модели лифта (ADR 0004).

  python tools/ingest/ingest.py --name kone-monospace --brand KONE --model "MonoSpace 500" \
      docs/*.pdf [--describe-images] [--translate] [--out packs/]

Что делает:
  1. Достаёт текст по страницам и картинки (встроенные изображения и страницы-схемы целиком).
  2. Режет текст на куски с указанием документа и страницы.
  3. --translate: тексты на иврите и китайском переводит на русский через Claude (оригинал сохраняется).
  4. --describe-images: каждую картинку описывает Claude — по подписи/тексту страницы и по самому изображению,
     с ключевыми словами на русском, английском и иврите. Без флага — описание из подписи и текста страницы.
  5. Считает эмбеддинги (multilingual-e5-small) для текста и описаний картинок.
  6. Пишет пакет: pack.db (SQLite) + images/*.webp, упакованные в <name>.kpack (zip).

Ключ Claude API берётся из переменной окружения ANTHROPIC_API_KEY (нужен только для флагов 3–4).
"""
import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "prototype"))

from secretary.knowledge import SCHEMA, Embedder, detect_lang, to_blob  # noqa: E402

CHUNK_CHARS = 900
OVERLAP = 150
MIN_IMAGE_PX = 160            # меньше — иконки и мусор
SCHEMATIC_TEXT_RATIO = 0.002  # страница, где мало текста и много графики, рендерится целиком как схема
CLAUDE_MODEL = os.environ.get("INGEST_CLAUDE_MODEL", "claude-sonnet-5-5")

DESCRIBE_PROMPT = """Ты помогаешь монтажнику лифтов. Перед тобой изображение из документа «{doc}», страница {page}.
Текст страницы рядом с изображением (контекст):
---
{context}
---
Опиши, что изображено, так, чтобы по описанию можно было найти этот рисунок поиском и понять его без картинки:
что за узел/схема/чертёж, ключевые детали, обозначения, клеммы, размеры, порядок действий, предупреждения.
Опирайся сначала на контекст документа, потом на само изображение. Не выдумывай того, чего не видно.
Ответь ТОЛЬКО JSON:
{{"caption": "короткое название по-русски",
 "description": "3–8 предложений по-русски",
 "keywords_ru": ["..."], "keywords_en": ["..."], "keywords_he": ["..."]}}"""

TRANSLATE_PROMPT = """Переведи технический текст из инструкции по лифтам на русский. Сохрани номера, обозначения,
коды ошибок и названия клемм как есть. Ответь только переводом.

{text}"""


def chunk_text(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):  # режем по границе предложения или строки
            cut = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if cut > start + CHUNK_CHARS // 2:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return [p for p in parts if p]


def find_caption(page_text: str) -> str:
    m = re.search(r"((?:Fig(?:ure)?|Рис(?:унок)?|Abb|איור)\.?\s*[\d.]+[^\n]{0,80})", page_text, re.I)
    return m.group(1).strip() if m else ""


class Claude:
    def __init__(self) -> None:
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("Нужен ключ: export ANTHROPIC_API_KEY=... (см. tools/ingest/README.md)")
        self.client = anthropic.Anthropic()

    def ask(self, prompt: str, image_png: bytes | None = None, max_tokens: int = 1200) -> str:
        import base64

        content: list[dict] = []
        if image_png:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                          "data": base64.b64encode(image_png).decode()}})
        content.append({"type": "text", "text": prompt})
        msg = self.client.messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens,
                                          messages=[{"role": "user", "content": content}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def extract(pdf_path: Path, img_dir: Path):
    """Отдаёт (page_no, text, [(image_file, png_bytes)]) по страницам."""
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        images = []
        area = page.rect.width * page.rect.height
        drawings = len(page.get_drawings())
        is_schematic = drawings > 200 and len(text) / max(area, 1) < SCHEMATIC_TEXT_RATIO
        sources = []
        if is_schematic:  # векторная схема — рендерим страницу целиком
            pix = page.get_pixmap(dpi=150)
            sources.append(pix.tobytes("png"))
        else:
            for xref, *_ in page.get_images(full=True):
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width < MIN_IMAGE_PX or pix.height < MIN_IMAGE_PX:
                        continue
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    sources.append(pix.tobytes("png"))
                except Exception:  # noqa: BLE001 — битые картинки пропускаем
                    continue
        for png in sources:
            h = hashlib.sha1(png).hexdigest()[:12]
            name = f"{pdf_path.stem[:40]}_p{i}_{h}.webp"
            img = Image.open(io.BytesIO(png)).convert("RGB")
            img.thumbnail((1600, 1600))
            img.save(img_dir / name, "WEBP", quality=80)
            images.append((name, png))
        yield i, text, images


def build(args) -> Path:
    claude = Claude() if (args.describe_images or args.translate) else None
    embedder = Embedder(args.embed_model)
    work = Path(tempfile.mkdtemp(prefix="kpack_"))
    img_dir = work / "images"
    img_dir.mkdir()
    db = sqlite3.connect(work / "pack.db")
    db.executescript(SCHEMA)
    meta = {"name": args.name, "brand": args.brand, "model": args.model, "built": date.today().isoformat(),
            "embed_model": args.embed_model, "format": 1}
    db.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])

    seen_images: set[str] = set()
    for pdf in args.pdfs:
        pdf = Path(pdf)
        print(f"\n📄 {pdf.name}")
        cur = db.execute("INSERT INTO docs (file, title, version, lang) VALUES (?,?,?,?)",
                         (pdf.name, args.title or pdf.stem, args.version, ""))
        doc_id = cur.lastrowid
        langs = []
        for page_no, text, images in extract(pdf, img_dir):
            lang = detect_lang(text)
            langs.append(lang)
            for chunk in chunk_text(text):
                translated = None
                if args.translate and lang in ("he", "zh"):
                    translated = claude.ask(TRANSLATE_PROMPT.format(text=chunk)).strip()
                search_text = translated or chunk
                db.execute("INSERT INTO chunks (doc_id, page, lang, text, text_ru, emb) VALUES (?,?,?,?,?,?)",
                           (doc_id, page_no, lang, chunk, translated, to_blob(embedder.passage(search_text))))
            caption = find_caption(text)
            for name, png in images:
                key = name.rsplit("_", 1)[-1]
                if key in seen_images:  # одинаковые картинки (логотипы и т.п.) — один раз
                    (img_dir / name).unlink(missing_ok=True)
                    continue
                seen_images.add(key)
                info = {"caption": caption, "description": text[:400].strip(), "keywords_ru": [],
                        "keywords_en": [], "keywords_he": []}
                if args.describe_images:
                    raw = claude.ask(DESCRIBE_PROMPT.format(doc=pdf.name, page=page_no, context=text[:2500]), png)
                    m = re.search(r"\{.*\}", raw, re.S)
                    if m:
                        try:
                            info.update(json.loads(m.group(0)))
                        except json.JSONDecodeError:
                            pass
                keywords = info["keywords_ru"] + info["keywords_en"] + info["keywords_he"]
                search_text = f"{info['caption']}. {info['description']} {' '.join(keywords)}"
                db.execute("""INSERT INTO images (doc_id, page, file, caption, description, keywords, emb)
                              VALUES (?,?,?,?,?,?,?)""",
                           (doc_id, page_no, name, info["caption"], info["description"],
                            json.dumps(keywords, ensure_ascii=False), to_blob(embedder.passage(search_text))))
            print(f"  стр. {page_no}: {lang}, картинок {len(images)}", end="\r")
        main_lang = max(set(langs), key=langs.count) if langs else ""
        db.execute("UPDATE docs SET lang=?, pages=? WHERE id=?", (main_lang, len(langs), doc_id))
        print(f"  ✓ страниц: {len(langs)}, язык: {main_lang}            ")
    db.commit()
    stats = db.execute("SELECT (SELECT count(*) FROM chunks), (SELECT count(*) FROM images)").fetchone()
    db.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pack = out / f"{args.name}.kpack"
    with zipfile.ZipFile(pack, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(work / "pack.db", "pack.db")
        for f in img_dir.iterdir():
            z.write(f, f"images/{f.name}")
    print(f"\n✓ {pack}  ({pack.stat().st_size / 1e6:.1f} МБ): кусков текста {stats[0]}, картинок {stats[1]}")
    return pack


def main() -> None:
    p = argparse.ArgumentParser(description="Сборка пакета знаний .kpack")
    p.add_argument("pdfs", nargs="+")
    p.add_argument("--name", required=True, help="имя пакета, например kone-monospace")
    p.add_argument("--brand", default="")
    p.add_argument("--model", default="", help="модель лифта")
    p.add_argument("--title", default="", help="название документа (по умолчанию имя файла)")
    p.add_argument("--version", default="", help="версия/дата документа")
    p.add_argument("--describe-images", action="store_true", help="описать картинки через Claude")
    p.add_argument("--translate", action="store_true", help="перевести иврит и китайский через Claude")
    p.add_argument("--embed-model", default="intfloat/multilingual-e5-small")
    p.add_argument("--out", default=str(HERE.parents[1] / "packs"))
    build(p.parse_args())


if __name__ == "__main__":
    main()
