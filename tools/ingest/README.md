# Сборка базы знаний

Из PDF-инструкций по одной модели лифта собирается пакет `packs/<имя>.kpack`. Мира подхватывает все пакеты из `packs/` при запуске.

## Установка (один раз, в окружении прототипа)

```bash
cd ~/Projects/secretary/prototype && source .venv/bin/activate
pip install pymupdf pillow anthropic sentence-transformers
```

## Сборка

```bash
cd ~/Projects/secretary
# только текст, бесплатно и офлайн:
python tools/ingest/ingest.py --name kone-monospace --brand KONE --model "MonoSpace 500" путь/к/*.pdf
# с описанием картинок и переводом иврита/китайского через Claude (платно, разово):
python tools/ingest/ingest.py --name kone-monospace --brand KONE --model "MonoSpace 500" --describe-images --translate путь/к/*.pdf
```

## Ключ Claude API (только для `--describe-images` и `--translate`)

Ключ создаётся в Claude Console (console.anthropic.com → API Keys). В чат его не присылать. Сохранить на Mac:

```bash
echo 'export ANTHROPIC_API_KEY="сюда-ключ"' >> ~/.zshrc && source ~/.zshrc
```

## Что внутри пакета

`pack.db` (SQLite: документы, куски текста со страницами, описания картинок, эмбеддинги multilingual-e5-small) и `images/*.webp`. Ответы Миры ссылаются на документ и страницу; если она сошлётся на страницу, которой нет в найденном, прототип покажет предупреждение.
