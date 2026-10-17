from secretary.engines.llm_llamacpp import _strip_think
from secretary.sentences import SentenceSplitter


def test_splits_streamed_sentences():
    s = SentenceSplitter()
    out = []
    for piece in ["Привет, Андрей", "! Как прошёл ", "день на объекте? Я тут ", "скучала."]:
        out += s.feed(piece)
    out += s.flush()
    assert out == ["Привет, Андрей!", "Как прошёл день на объекте?", "Я тут скучала."]


def test_short_sentences_are_merged():
    s = SentenceSplitter()
    out = s.feed("Да. Конечно, сейчас найду. ") + s.flush()
    assert out == ["Да. Конечно, сейчас найду."]


def test_strip_think_block():
    assert "".join(_strip_think(iter(["<th", "ink>\n\n</think>\n\n", "При", "вет"]))) == "Привет"
    assert "".join(_strip_think(iter(["При", "вет"]))) == "Привет"
