from pathlib import Path
from typing import Iterator


class LlamaCppLLM:
    def __init__(self, model_path: Path, cfg: dict) -> None:
        from llama_cpp import Llama

        if not model_path.exists():
            raise FileNotFoundError(f"нет модели {model_path}. Запусти scripts/download_models.py")
        self.cfg = cfg
        # Модели Qwen (ChatML) умеют «думать вслух». Для голоса это лишнее:
        # собираем промпт сами и сразу закрываем блок размышлений.
        self.is_qwen = "qwen" in model_path.name.lower()
        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=cfg.get("context", 8192),
            n_gpu_layers=cfg.get("gpu_layers", -1),
            verbose=False,
        )

    def _sampling(self, temperature: float | None = None) -> dict:
        c = self.cfg
        return dict(
            temperature=c.get("temperature", 0.8) if temperature is None else temperature,
            top_p=c.get("top_p", 0.9),
            min_p=c.get("min_p", 0.05),
            repeat_penalty=c.get("repeat_penalty", 1.1),
            presence_penalty=c.get("presence_penalty", 0.3),
            max_tokens=c.get("max_tokens", 400),
        )

    def stream_chat(self, messages: list[dict], temperature: float | None = None) -> Iterator[str]:
        if self.is_qwen:
            prompt = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
            prompt += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
            stream = self.llm.create_completion(prompt=prompt, stream=True,
                                                stop=["<|im_end|>", "<|im_start|>"], **self._sampling(temperature))
            pieces = (chunk["choices"][0]["text"] for chunk in stream)
        else:
            stream = self.llm.create_chat_completion(messages=messages, stream=True, **self._sampling(temperature))
            pieces = (chunk["choices"][0]["delta"].get("content") or "" for chunk in stream)
        yield from _strip_think(pieces)


_THINK_STARTS = ("<think>", "thinking process", "thinking:")
_PROBE = 24  # сколько символов ждём, чтобы понять, начала ли модель «думать вслух»


def _strip_think(pieces: Iterator[str]) -> Iterator[str]:
    """Убирает размышления модели: блок <think>…</think> или текст «Thinking Process: … </think>»."""
    buf = ""
    mode = "probe"  # probe → think (пропускаем до </think>) → pass
    for piece in pieces:
        if mode == "pass":
            yield piece
            continue
        buf += piece
        if mode == "probe":
            head = buf.lstrip().lower()
            if any(head.startswith(s) for s in _THINK_STARTS):
                mode = "think"
            elif len(head) >= _PROBE or (head and not any(s.startswith(head[:len(s)]) for s in _THINK_STARTS)):
                mode = "pass"
                yield buf.lstrip()
                buf = ""
                continue
        if mode == "think" and "</think>" in buf:
            mode = "pass"
            rest = buf.split("</think>", 1)[1].lstrip()
            buf = ""
            if rest:
                yield rest
    if mode == "probe" and buf.strip():
        yield buf.strip()
