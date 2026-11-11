"""Где что лежит. Проект самодостаточен: модели и инструменты — внутри его папки.

    llm-bridge/
        pc/        мост для ПК (этот код)
        android/   приложение для телефона
        scripts/   установка и загрузка моделей
        tools/     внешние инструменты: llama.cpp, stable-diffusion.cpp (в git не попадают)
        models/    модели: llm/, image/, lora/, upscale/, whisper/ (в git не попадают)
Пути в настройках хранятся относительно корня проекта, поэтому папку можно переносить.
        data/      личное: настройки, токен, чаты, карточки, картинки (в git не попадает)

Вне проекта остаются только системные вещи: helper в /usr/local/sbin и запись автозапуска.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()

LLAMA_BIN = "tools/llama.cpp/build/bin/llama-server"
SD_BIN = "tools/stable-diffusion.cpp/build/bin/sd-server"
MODELS = "models"


def expand(path: str) -> str:
    """Путь из настроек → абсолютный: «~» — домашняя папка, относительный — от корня проекта."""
    p = Path(os.path.expanduser(str(path)))
    return str(p if p.is_absolute() else ROOT / p)


def shorten(path: str) -> str:
    """Абсолютный путь → как хранить в настройках: внутри проекта — относительный."""
    if not path:
        return path
    try:
        return Path(expand(path)).relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def variants(path: str) -> list:
    """Где искать файл из старых настроек: как записано, затем в папке проекта.
    «~/models/…» и «models/…» — это models/ проекта (раньше модели лежали в домашней папке)."""
    s = str(path)
    out = [expand(s)]
    for old in ("~/models/", str(HOME / "models") + "/"):
        if s.startswith(old):
            out.append(str(ROOT / MODELS / s[len(old):]))
    if not os.path.isabs(os.path.expanduser(s)):
        out.append(str(HOME / s))
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


def lib_env(binary: str) -> dict:
    """Окружение для запуска инструмента: его библиотеки (libllama.so и т.п.) лежат рядом
    с программой, а путь к ним, вшитый при сборке, после переноса папки уже неверен."""
    env = dict(os.environ)
    here = os.path.dirname(os.path.abspath(binary))
    env["LD_LIBRARY_PATH"] = here + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env
