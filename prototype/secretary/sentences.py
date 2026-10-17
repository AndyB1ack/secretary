"""Нарезка потока токенов на предложения, чтобы озвучивать ответ, пока он дописывается."""
import re

_END = re.compile(r"([.!?…]+[»\")]?)(\s+)")
_MIN_CHARS = 12  # слишком короткие куски («Да.») склеиваем со следующим


class SentenceSplitter:
    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[str]:
        self._buf += chunk
        out: list[str] = []
        start = 0
        for m in _END.finditer(self._buf):
            end = m.end(1)
            candidate = self._buf[start:end].strip()
            if len(candidate) >= _MIN_CHARS:
                out.append(candidate)
                start = m.end()
        self._buf = self._buf[start:]
        return out

    def flush(self) -> list[str]:
        rest = self._buf.strip()
        self._buf = ""
        return [rest] if rest else []
