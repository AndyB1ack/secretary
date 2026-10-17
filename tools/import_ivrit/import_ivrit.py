"""Импорт учебных материалов из Ivrit Trainer (AndyB1ack/ivrit-trainer, database/seed) для слоя репетитора Миры.

  python tools/import_ivrit/import_ivrit.py ~/путь/к/ivrit-trainer

Результат: persona/tutor/he_course.json.gz — слова, уроки, примеры, сценарии, глаголы.
"""
import glob
import gzip
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "persona" / "tutor" / "he_course.json.gz"


def term(t, track: str, topic: str, source: str) -> dict | None:
    if not isinstance(t, dict):
        return None
    he = t.get("he") or t.get("hebrew_plain")
    ru = t.get("ru") or t.get("translation_ru")
    if not he or not ru:
        return None
    return {"he": he, "nikud": t.get("nikud") or t.get("hebrew_nikud") or he,
            "tr": t.get("tr") or t.get("translit_ru") or "", "ru": ru, "pos": t.get("pos") or "",
            "gender": t.get("gender") or "", "track": track, "topic": topic, "src": source}


def main(root: str) -> None:
    seed = Path(root).expanduser() / "database" / "seed"
    terms, lessons, examples, scenarios, verbs = [], [], [], [], []
    for f in sorted(glob.glob(str(seed / "lessons" / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        track = (d.get("tracks") or ["CORE"])[0]
        lessons.append({"id": d["id"], "track": track, "title": d.get("title_ru", ""),
                        "goal": d.get("goal_ru", ""), "grammar": d.get("grammar_md", "")})
        for w in d.get("words", []):
            if (t := term(w, track, d.get("title_ru", ""), f"урок {d['id']}")):
                terms.append(t)
        for e in d.get("examples", []):
            examples.append({"lesson": d["id"], "he": e.get("he"), "nikud": e.get("nikud"),
                             "tr": e.get("tr"), "ru": e.get("ru"), "track": e.get("track", track)})
    for f in sorted(glob.glob(str(seed / "mda" / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        for w in d.get("terms", []):
            if (t := term(w, "MDA", d.get("topic_ru", ""), f"МАДА {Path(f).stem}")):
                terms.append(t)
    for name in ("terms.json", "terms_game.json"):
        p = seed / name
        if p.exists():
            for w in json.load(open(p, encoding="utf-8")):
                tr = w.get("track") or ["CORE"]
                if (t := term(w, tr[0] if isinstance(tr, list) else tr, w.get("topic", ""), name)):
                    terms.append(t)
    for f in sorted(glob.glob(str(seed / "conjugations" / "*.json"))):
        for v in json.load(open(f, encoding="utf-8")):
            verbs.append({k: v.get(k) for k in ("id", "infinitive", "ru", "root", "binyan", "notes")} |
                         {"forms": {k: v[k] for k in v if k not in ("id", "infinitive", "ru", "root", "binyan",
                                                                     "notes", "tracks", "verification")}})
    for f in glob.glob(str(seed / "**" / "*scenario*.json"), recursive=True):
        scenarios += json.load(open(f, encoding="utf-8"))
    seen, uniq = set(), []
    for t in terms:  # без дублей по слову и переводу
        key = (t["he"], t["ru"])
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    data = {"source": "AndyB1ack/ivrit-trainer", "terms": uniq, "lessons": lessons, "examples": examples,
            "scenarios": scenarios, "verbs": verbs}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    print(f"✓ {OUT.name}: слов {len(uniq)}, уроков {len(lessons)}, примеров {len(examples)}, "
          f"сценариев {len(scenarios)}, глаголов {len(verbs)} ({OUT.stat().st_size / 1e6:.1f} МБ)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "~/Projects/ivrit-trainer")
