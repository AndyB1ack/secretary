import sqlite3
import zipfile

import numpy as np

from secretary.knowledge import SCHEMA, KnowledgeBase, check_citations, detect_lang, to_blob


class FakeEmb:
    vocab = ["клемм", "двер", "тормоз"]

    def _v(self, t):
        v = np.array([t.lower().count(w) for w in self.vocab], dtype=np.float32) + 1e-3
        return v / np.linalg.norm(v)

    passage = query = _v


def make_pack(tmp_path):
    db_path = tmp_path / "pack.db"
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    e = FakeEmb()
    db.execute("INSERT INTO meta VALUES ('brand','KONE'),('model','MonoSpace')")
    db.execute("INSERT INTO docs (id, file, title, lang, pages) VALUES (1,'a.pdf','Монтаж MonoSpace','ru',40)")
    db.execute("INSERT INTO chunks (doc_id, page, lang, text, emb) VALUES (1, 12, 'ru', ?, ?)",
               ("Клеммы X1 и X2 подключаются к контроллеру", to_blob(e.passage("клеммы клемм"))))
    db.execute("INSERT INTO chunks (doc_id, page, lang, text, emb) VALUES (1, 30, 'ru', ?, ?)",
               ("Регулировка тормоза", to_blob(e.passage("тормоз"))))
    db.commit(); db.close()
    with zipfile.ZipFile(tmp_path / "kone.kpack", "w") as z:
        z.write(db_path, "pack.db")
    return KnowledgeBase(tmp_path, FakeEmb(), min_score=0.5)


def test_search_and_cite(tmp_path):
    kb = make_pack(tmp_path)
    assert "KONE MonoSpace" in kb.describe()
    hits = kb.search("какие клеммы у контроллера?")
    assert hits[0].page == 12
    assert "стр. 12" in KnowledgeBase.prompt_block(hits)
    assert check_citations("Смотри стр. 12", hits) == []
    assert check_citations("Это на странице 14", hits) == ["14"]


def test_empty_kb(tmp_path):
    kb = KnowledgeBase(tmp_path / "nope")
    assert kb.empty and "НЕТ" in kb.describe() and kb.search("x") == []


def test_detect_lang():
    assert detect_lang("שלום עולם") == "he" and detect_lang("Привет") == "ru" and detect_lang("Brake") == "en"
