#!/usr/bin/env python3
"""Переезд на новую структуру: всё нужное — внутри папки проекта.

    python3 scripts/migrate-layout.py        показать, что будет сделано (ничего не меняет)
    python3 scripts/migrate-layout.py --go   выполнить

Что делает:
  1. убирает из корня проекта старые файлы моста (они теперь в pc/, scripts/, docs/);
  2. переносит настройки сборки из ~/llm-bridge-android в android/, старую папку
     переименовывает в ~/llm-bridge-android.old;
  3. переносит модели (~/models и файлы, указанные в настройках моста) в models/;
  4. переносит llama.cpp и stable-diffusion.cpp в tools/;
  5. переносит личные данные в data/: настройки и токен (~/.config/llm-bridge), чаты, карточки
     и картинки (~/.local/share/llm-bridge);
  6. поправляет пути в data/config.json и image_profiles.json
     (старые версии сохраняются рядом с расширением .bak).

Ничего не перезаписывает: если файл с таким именем на новом месте уже есть, старый остаётся
где был, а скрипт об этом пишет. Запускать при закрытом мосте. Повторный запуск безопасен.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
OLD_CONF = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config"))) / "llm-bridge"
OLD_DATA = Path(os.environ.get("XDG_DATA_HOME", str(HOME / ".local/share"))) / "llm-bridge"
DATA = ROOT / "data"
# настройки читаем там, где они сейчас: уже в проекте или ещё в домашней папке
CONF = DATA if (DATA / "config.json").exists() else OLD_CONF
GO = "--go" in sys.argv
BIG = 100 * 1024 * 1024          # файл модели — от 100 МБ (в llama.cpp лежат мелкие словари .gguf)

moves = []       # (откуда, куда) — для правки путей в настройках
notes = []       # на что обратить внимание в конце
count = {"moved": 0, "removed": 0, "bytes": 0}


def say(text=""):
    print(text)


def size(p: Path) -> int:
    if p.is_symlink() or not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dp, _dn, fn in os.walk(p):
        for f in fn:
            fp = os.path.join(dp, f)
            if not os.path.islink(fp):
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    return total


def human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.1f} {unit}" if unit == "ГБ" else f"{n:.0f} {unit}"
        n /= 1024


def short(p) -> str:
    p = str(p)
    for base, name in ((str(ROOT), "<проект>"), (str(HOME), "~")):
        if p == base or p.startswith(base + "/"):
            return name + p[len(base):]
    return p


def inside(p: Path, parent: Path) -> bool:
    try:
        p.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def same_disk(a: Path, b: Path) -> bool:
    while not b.exists():
        b = b.parent
    return a.stat().st_dev == b.stat().st_dev


def move(src: Path, dst: Path, what: str = ""):
    """Перенести файл или папку; папки сливаются, существующее не перезаписывается."""
    if not src.exists() and not src.is_symlink():
        return
    if dst.exists() or dst.is_symlink():
        if src.is_dir() and dst.is_dir() and not src.is_symlink():
            for child in sorted(src.iterdir()):
                move(child, dst / child.name)
            moves.append((str(src), str(dst)))
            if GO:
                try:
                    src.rmdir()
                except OSError:
                    pass
            return
        notes.append(f"уже есть на новом месте, оставлен как был: {short(src)}")
        return
    n = size(src)
    slow = "" if same_disk(src, dst.parent) else "  ← другой диск: будет копирование"
    say(f"  перенести  {short(src)}  →  {short(dst)}  ({human(n)}){slow}{'  ' + what if what else ''}")
    moves.append((str(src), str(dst)))
    count["moved"] += 1
    count["bytes"] += n
    if GO:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def remove(p: Path):
    if not p.exists() and not p.is_symlink():
        return
    say(f"  убрать     {short(p)}")
    count["removed"] += 1
    if GO:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()


def remap(path: str) -> str:
    """Старый путь из настроек → новый (относительно проекта, если файл теперь внутри него)."""
    if not path:
        return path
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        return path
    for old, new in sorted(moves, key=lambda m: -len(m[0])):
        if p == old or p.startswith(old + "/"):
            p = new + p[len(old):]
            break
    try:
        return Path(p).relative_to(ROOT).as_posix()
    except ValueError:
        return path


def _ancestors() -> set:
    """Этот скрипт и оболочки, из которых он запущен (в их командной строке могут быть те же слова)."""
    out, pid = set(), os.getpid()
    while pid > 1 and pid not in out:
        out.add(pid)
        try:
            pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def running() -> list:
    out = []
    for args in (["-x", "llama-server"], ["-x", "sd-server"], ["-f", "python3 .*(pc|llm-bridge)/main.py"]):
        pat = args[1] if args[0] == "-x" else "мост"
        r = subprocess.run(["pgrep"] + args, capture_output=True, text=True)
        pids = [x for x in r.stdout.split() if int(x) not in _ancestors()]
        if pids:
            out.append(pat)
    return out


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def tool_dir(binary: str, default: Path) -> Path:
    """Папка инструмента по пути к программе из настроек: …/llama.cpp/build/bin/llama-server."""
    p = Path(os.path.expanduser(binary)) if binary else None
    if p and p.is_absolute():
        for parent in p.parents:
            if parent.name == "build":
                return parent.parent
    return default


def main():
    if not (ROOT / "pc" / "main.py").exists():
        sys.exit("Не вижу pc/main.py — сначала распакуйте новый архив поверх проекта.")
    busy = running()
    if busy and GO:
        sys.exit("Мост или модель ещё работают (" + ", ".join(busy) + "). Закройте мост и повторите.")
    say(f"Проект: {ROOT}")
    say("Режим: " + ("ВЫПОЛНЕНИЕ" if GO else "только показ — ничего не меняется"))
    cfg = load_json(CONF / "config.json") or {}

    say("\n1. Старые файлы моста в корне проекта")
    for f in sorted((ROOT / "pc").glob("*.py")):
        remove(ROOT / f.name)
    for name in ("helper", "install.sh", "__pycache__", "ROADMAP.md", "ПРОВЕРКА.md",
                 "tools/organize-models.sh", "tools/setup-helper.sh", "tools/setup-images.sh"):
        if name == "helper" and not (ROOT / "pc" / "helper").exists():
            continue
        remove(ROOT / name)

    say("\n2. Приложение для телефона")
    old_app = HOME / "llm-bridge-android"
    if old_app.is_dir() and not inside(old_app, ROOT):
        for name in ("local.properties", ".adb-last"):
            move(old_app / name, ROOT / "android" / name)
        park = HOME / "llm-bridge-android.old"
        if park.exists():
            notes.append(f"{short(park)} уже существует — {short(old_app)} оставлена как есть")
        else:
            say(f"  переименовать  {short(old_app)}  →  {short(park)}")
            if GO:
                old_app.rename(park)
            notes.append(f"старая папка приложения: {short(park)} — после проверки сборки "
                         f"удалите её: rm -rf {short(park)}")
    else:
        say("  старой папки ~/llm-bridge-android нет — пропускаю")

    say("\n3. Модели → models/")
    llama_dir = tool_dir(cfg.get("llama_bin", ""), HOME / "llama.cpp")
    sd_dir = tool_dir(cfg.get("sd_server_bin", ""), HOME / "stable-diffusion.cpp")
    old_models = Path(os.path.expanduser(cfg.get("models_dir") or str(HOME / "models")))
    if not old_models.is_absolute():
        old_models = ROOT / old_models
    if old_models.is_dir() and not inside(old_models, ROOT):
        move(old_models, ROOT / "models")
    # файлы из настроек, лежащие где-то ещё (например, рядом с llama.cpp)
    for key, sub in (("model", "llm"), ("mmproj", "llm"), ("bg_model", "llm/helper")):
        v = cfg.get(key) or ""
        p = Path(os.path.expanduser(v))
        if v and p.is_absolute() and p.is_file() and not inside(p, ROOT / "models") \
                and not inside(p, old_models):
            move(p, ROOT / "models" / sub / p.name, f"({key} из настроек)")
    # большие .gguf внутри папок инструментов — это модели, а не часть llama.cpp
    for d in (llama_dir, sd_dir):
        if d.is_dir() and not inside(ROOT / "models", d):
            for f in sorted(d.rglob("*")):
                if f.is_file() and not f.is_symlink() and f.suffix in (".gguf", ".safetensors") \
                        and f.stat().st_size >= BIG and str(f) not in [m[0] for m in moves]:
                    sub = "llm" if f.suffix == ".gguf" and d == llama_dir else "image"
                    move(f, ROOT / "models" / sub / f.name, "(лежал в папке инструмента)")

    say("\n4. Инструменты → tools/")
    for d, name in ((llama_dir, "llama.cpp"), (sd_dir, "stable-diffusion.cpp")):
        dst = ROOT / "tools" / name
        if d.is_dir() and not inside(d, ROOT):
            if inside(ROOT, d):
                notes.append(f"{short(d)} содержит сам проект — не переношу")
                continue
            move(d, dst)
        elif dst.is_dir():
            say(f"  {name}: уже на месте")
        else:
            say(f"  {name}: не найден ({short(d)}) — соберите: ./scripts/setup-"
                + ("llama.sh" if name == "llama.cpp" else "images.sh"))

    say("\n5. Личные данные → data/")
    conf = CONF
    for old, what in ((OLD_CONF, "настройки, токен"), (OLD_DATA, "чаты, карточки, картинки")):
        if old.is_dir() and not inside(old, ROOT):
            for child in sorted(old.iterdir()):
                move(child, DATA / child.name, f"({what})" if child.suffix in (".json", ".db") else "")
            if GO:
                try:
                    old.rmdir()
                except OSError:
                    notes.append(f"в {short(old)} что-то осталось — посмотрите сами")
    if GO and (DATA / "config.json").exists():
        conf = DATA
    if not any(m[1].startswith(str(DATA)) for m in moves):
        say("  уже в проекте или ещё не создавались")

    say("\n6. Пути в настройках моста")
    if cfg:
        new = dict(cfg)
        for key in ("models_dir", "llama_bin", "model", "mmproj", "bg_model", "sd_server_bin"):
            if cfg.get(key):
                new[key] = remap(cfg[key])
                if new[key] != cfg[key]:
                    say(f"  {key}: {short(cfg[key])}  →  {new[key]}")
        if new != cfg and GO:
            shutil.copy2(conf / "config.json", conf / "config.json.bak")
            (conf / "config.json").write_text(json.dumps(new, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
            os.chmod(conf / "config.json", 0o600)
    else:
        say("  config.json не найден — мост создаст новый с путями внутри проекта")
    prof_path = conf / "image_profiles.json"
    raw = prof_path.read_text(encoding="utf-8") if prof_path.exists() else ""
    if raw:
        fixed = raw.replace("~/models/", "models/").replace(str(HOME / "models") + "/", "models/")
        if fixed != raw:
            say("  image_profiles.json: «~/models/…» → «models/…»")
            if GO:
                shutil.copy2(prof_path, str(prof_path) + ".bak")
                prof_path.write_text(fixed, encoding="utf-8")

    say("\nИтог: перенести — %d (%s), убрать — %d." % (count["moved"], human(count["bytes"]),
                                                     count["removed"]))
    for n in notes:
        say("  ! " + n)
    if busy and not GO:
        say("  ! сейчас работают: " + ", ".join(busy) + " — перед переносом закройте мост")
    if not GO:
        say("\nЕсли всё верно, выполните:  python3 scripts/migrate-layout.py --go")
    else:
        say("\nГотово. Запуск моста:  ./run.sh     Сборка приложения:  ./deploy.sh")


if __name__ == "__main__":
    main()
