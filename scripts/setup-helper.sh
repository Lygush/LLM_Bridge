#!/bin/bash
# Фоновая модель: маленькая LLM на процессоре для памяти, отношений персонажей и состояния квеста.
# Большая модель на видеокарте тогда занята только ответами, а фон не ждёт и не мешает рисованию.
#
#   ./scripts/setup-helper.sh          Qwen3-4B-Instruct-2507 Q4_K_M (~2,5 ГБ) — по умолчанию
#   ./scripts/setup-helper.sh --small  Qwen3-1.7B Q4_K_M (~1,1 ГБ) — если процессор слабый
#
# Файл ляжет в models/llm/helper/ проекта, путь пропишется в конфиг моста (bg_model).
# После этого перезапустите мост: фоновая модель стартует сама.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/tools/hf-venv"   # утилита загрузки с Hugging Face — тоже внутри проекта
DEST="$ROOT/models/llm/helper"
SIZE=normal
[[ "${1:-}" == "--small" ]] && SIZE=small
mkdir -p "$DEST"

if ! "$VENV/bin/python" -c "" 2>/dev/null; then   # нет или сломалось после переноса папки
    rm -rf "$VENV"
    sudo apt install -y python3-venv >/dev/null
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q -U huggingface_hub

SIZE=$SIZE DEST="$DEST" ROOT="$ROOT" "$VENV/bin/python" - <<'PY'
import json, os, pathlib, sys
from huggingface_hub import hf_hub_download, list_repo_files

dest = os.environ["DEST"]
if os.environ["SIZE"] == "small":
    candidates = [("unsloth/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q4_K_M.gguf"),
                  ("Qwen/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q8_0.gguf")]
else:
    candidates = [("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
                  ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf")]

path = None
for repo, name in candidates:
    try:
        files = list_repo_files(repo)
    except Exception as e:  # noqa: BLE001
        print(f"  {repo}: недоступен ({e.__class__.__name__})")
        continue
    if name not in files:   # имя файла могло поменяться — берём похожий Q4_K_M
        alt = [f for f in files if f.lower().endswith("q4_k_m.gguf")]
        if not alt:
            print(f"  {repo}: нет файла Q4_K_M")
            continue
        name = alt[0]
    print(f"== {repo} / {name}")
    path = hf_hub_download(repo, name, local_dir=dest)
    break

if not path:
    sys.exit("Не удалось скачать фоновую модель")

cfg = pathlib.Path(os.environ["ROOT"]) / "data/config.json"
if cfg.exists():
    c = json.loads(cfg.read_text())
    c["bg_model"] = pathlib.Path(path).resolve().relative_to(os.environ["ROOT"]).as_posix()
    cfg.write_text(json.dumps(c, ensure_ascii=False, indent=2))
    print(f"  конфиг: bg_model = {c['bg_model']}")
print(f"Готово: {path}")
PY
ls -la "$DEST"
