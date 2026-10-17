"""F5-TTS: нейросетевой голос по образцу (10–20 секунд записи). Русская модель Misha24-10/F5-TTS_RUSSIAN."""
import time
from pathlib import Path

import numpy as np

REPO = "Misha24-10/F5-TTS_RUSSIAN"


def fetch_checkpoint(models_dir: Path) -> tuple[Path, Path]:
    """Скачивает веса и словарь русской F5 (один раз, ~1.3 ГБ)."""
    from huggingface_hub import hf_hub_download, list_repo_files

    files = list_repo_files(REPO)
    ckpts = [f for f in files if f.endswith((".safetensors", ".pt")) and "v1" in f.lower()] or \
            [f for f in files if f.endswith((".safetensors", ".pt"))]
    vocabs = [f for f in files if f.endswith("vocab.txt")]
    if not ckpts or not vocabs:
        raise RuntimeError(f"не нашёл веса/словарь в {REPO}: {files}")
    ckpt = sorted(ckpts, key=lambda f: ("inference" not in f, f))[-1] if len(ckpts) > 1 else ckpts[0]
    vocab = next((v for v in vocabs if Path(v).parent == Path(ckpt).parent), vocabs[0])
    target = models_dir / "f5_ru"
    print(f"F5: {ckpt}, {vocab}")
    c = hf_hub_download(REPO, ckpt, local_dir=target)
    v = hf_hub_download(REPO, vocab, local_dir=target)
    return Path(c), Path(v)


class F5TTS:
    def __init__(self, cfg: dict, models_dir: Path) -> None:
        import torch
        from f5_tts.api import F5TTS as _F5

        ckpt, vocab = fetch_checkpoint(models_dir)
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = _F5(model=cfg.get("arch", "F5TTS_v1_Base"), ckpt_file=str(ckpt),
                         vocab_file=str(vocab), device=device)
        self.ref_audio = str(cfg["ref_audio"])
        self.ref_text = Path(cfg["ref_text"]).read_text(encoding="utf-8").strip()
        self.speed = cfg.get("speed", 1.0)
        self.nfe = cfg.get("nfe_step", 16)  # меньше — быстрее, больше — чище (по умолчанию в F5 32)
        self.sample_rate = 24000

    def synthesize(self, text: str) -> np.ndarray:
        wav, sr, _ = self.model.infer(ref_file=self.ref_audio, ref_text=self.ref_text, gen_text=text,
                                      speed=self.speed, nfe_step=self.nfe, remove_silence=False,
                                      show_info=lambda *a, **k: None, progress=None)
        self.sample_rate = sr
        return np.asarray(wav, dtype=np.float32)
