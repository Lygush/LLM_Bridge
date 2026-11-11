"""Изображения в сообщениях: хранение файлов и подготовка для модели.

Файлы лежат в data/images/<sha256>.jpg|png, имя — хэш содержимого
(одинаковые картинки не дублируются). В сообщении хранится список
{"name", "w", "h"} в meta.images.
"""
import base64
import hashlib
import math
import re
import struct

from config import DATA_DIR
from store import BadRequest

IMG_DIR = DATA_DIR / "images"
NAME_RE = re.compile(r"^[0-9a-f]{24}\.(jpg|png)$")
MAX_BYTES = 12 * 1024 * 1024
MAX_IMAGES = 6
PATCH = 32   # пикселей на токен изображения (оценка для Qwen-VL: патч 16 × слияние 2)


def _png_size(b: bytes):
    if len(b) >= 24 and b[12:16] == b"IHDR":
        return struct.unpack(">II", b[16:24])
    return None


def _jpeg_size(b: bytes):
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", b[i + 2:i + 4])[0]
        # SOF0..SOF15, кроме DHT(C4), JPG(C8), DAC(CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return None


def save_image(data_b64: str) -> dict:
    """base64 (можно с префиксом data:...;base64,) → сохранённый файл и размеры."""
    if "," in data_b64[:100] and data_b64.startswith("data:"):
        data_b64 = data_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (ValueError, TypeError):
        raise BadRequest("картинка: некорректный base64")
    if len(raw) > MAX_BYTES:
        raise BadRequest("картинка слишком большая")
    if raw[:3] == b"\xff\xd8\xff":
        ext, size = "jpg", _jpeg_size(raw)
    elif raw[:8] == b"\x89PNG\r\n\x1a\n":
        ext, size = "png", _png_size(raw)
    else:
        raise BadRequest("поддерживаются только JPEG и PNG")
    if not size or not all(size):
        raise BadRequest("не удалось прочитать размер картинки")
    name = hashlib.sha256(raw).hexdigest()[:24] + "." + ext
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    path = IMG_DIR / name
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)
    return {"name": name, "w": int(size[0]), "h": int(size[1])}


def image_path(name: str):
    if not NAME_RE.match(name or ""):
        return None
    p = IMG_DIR / name
    return p if p.exists() else None


def data_url(name: str):
    p = image_path(name)
    if not p:
        return None
    mime = "image/png" if name.endswith(".png") else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def image_tokens(img: dict) -> int:
    """Оценка числа токенов картинки в контексте модели."""
    w, h = max(1, img.get("w", 1024)), max(1, img.get("h", 1024))
    return min(4096, math.ceil(w / PATCH) * math.ceil(h / PATCH) + 4)
