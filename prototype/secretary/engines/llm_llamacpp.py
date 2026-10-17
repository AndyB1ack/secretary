from pathlib import Path
from typing import Iterator


class LlamaCppLLM:
    def __init__(self, model_path: Path, cfg: dict) -> None:
        from llama_cpp import Llama

        if not model_path.exists():
            raise FileNotFoundError(f"нет модели {model_path}. Запусти scripts/download_models.py")
        self.cfg = cfg
        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=cfg.get("context", 8192),
            n_gpu_layers=cfg.get("gpu_layers", -1),
            verbose=False,
        )

    def stream_chat(self, messages: list[dict]) -> Iterator[str]:
        stream = self.llm.create_chat_completion(
            messages=messages,
            stream=True,
            temperature=self.cfg.get("temperature", 0.8),
            top_p=self.cfg.get("top_p", 0.9),
            min_p=self.cfg.get("min_p", 0.05),
            repeat_penalty=self.cfg.get("repeat_penalty", 1.1),
            presence_penalty=self.cfg.get("presence_penalty", 0.3),
            max_tokens=self.cfg.get("max_tokens", 400),
        )
        yield from _strip_think(
            chunk["choices"][0]["delta"].get("content") or "" for chunk in stream
        )


def _strip_think(pieces: Iterator[str]) -> Iterator[str]:
    """Убирает блок <think>…</think>, который Qwen3 иногда выдаёт в начале."""
    buf = ""
    passed = False
    for piece in pieces:
        if passed:
            yield piece
            continue
        buf += piece
        stripped = buf.lstrip()
        if stripped.startswith("<think>"):
            if "</think>" in buf:
                passed = True
                rest = buf.split("</think>", 1)[1].lstrip()
                if rest:
                    yield rest
        elif len(stripped) >= 7 or (stripped and not "<think>".startswith(stripped)):
            passed = True
            yield stripped
    if not passed and buf.strip() and not buf.lstrip().startswith("<think>"):
        yield buf.strip()
