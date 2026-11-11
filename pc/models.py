"""Папки моделей и выбор текстовой модели.

models/ в папке проекта (в git не попадает)
    llm/       текстовые модели (.gguf) и их mmproj (зрение)
    image/     модели изображений: диффузия, текстовые энкодеры, VAE (можно по подпапкам)
    lora/      LoRA для изображений (+ catalog.json — описания для автоподбора)
    upscale/   апскейлеры
    whisper/   распознавание речи (на будущее)
"""
from pathlib import Path

import paths

SUBDIRS = ("llm", "llm/helper", "image", "lora", "upscale", "whisper")


def models_dir(cfg) -> Path:
    return Path(paths.expand(cfg.models_dir))


def ensure_dirs(cfg) -> Path:
    root = models_dir(cfg)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def text_models(cfg) -> list:
    """Текстовые модели в models/llm (без mmproj и без вторых частей разбитых файлов)."""
    root = models_dir(cfg) / "llm"
    out = []
    if root.is_dir():
        for p in sorted(root.rglob("*.gguf")):
            n = p.name.lower()
            if "mmproj" in n or "helper" in p.relative_to(root).parts[:-1]:
                continue   # helper/ — фоновые маленькие модели, не для основного чата
            if "-of-" in n and "-00001-of-" not in n:
                continue   # разбитая модель: llama.cpp открывает её по первой части
            out.append(p)
    return out


def guess_mmproj(model: str) -> str:
    """mmproj рядом с моделью с самым длинным общим началом имени (не короче 6 символов)."""
    m = Path(model)
    best, best_len = "", 5
    for p in m.parent.glob("*.gguf"):
        if "mmproj" not in p.name.lower():
            continue
        n = 0
        for a, b in zip(m.name.lower(), p.name.lower()):
            if a != b:
                break
            n += 1
        if n > best_len:
            best, best_len = str(p), n
    return best
