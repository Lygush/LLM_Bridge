#!/bin/bash
# Подготовка генерации изображений: сборка stable-diffusion.cpp (CUDA) и загрузка моделей.
#
#   ./scripts/setup-images.sh            сборка + Krea 2 Turbo (≈ 10–12 ГБ)
#   ./scripts/setup-images.sh --qwen     то же + Qwen-Image 2.1 (ещё ≈ 14 ГБ) — он же рисует по
#                                      образцам: похожие лица персонажей, поза по вашему фото
#   ./scripts/setup-images.sh --moss     то же + MOSS-Image SFT: текст на картинке, раскладка (≈ 9 ГБ)
#   ./scripts/setup-images.sh --qwen-turbo  Qwen-Image 2.1 Turbo: то же, что Qwen-Image, но 8 шагов
#                                      вместо 20 — картинки с лицом персонажа в разы быстрее
#   ./scripts/setup-images.sh --no-build только модели
#
# Всё остаётся в папке проекта: исходники и сборка — tools/stable-diffusion.cpp,
# модели — models/image; профили моста находят их сами.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SD_DIR="$ROOT/tools/stable-diffusion.cpp"
MODELS="$ROOT/models/image"
mkdir -p "$ROOT/tools" "$MODELS"
VENV="$ROOT/tools/hf-venv"   # утилита загрузки с Hugging Face — тоже внутри проекта
BUILD=1; QWEN=0; MOSS=0; TURBO=0
for a in "$@"; do
    case "$a" in
        --qwen) QWEN=1 ;;
        --moss) MOSS=1 ;;
        --qwen-turbo) TURBO=1 ;;
        --no-build) BUILD=0 ;;
        *) echo "Неизвестный аргумент: $a"; exit 1 ;;
    esac
done

if [[ $BUILD == 1 ]]; then
    echo "== Сборка stable-diffusion.cpp с CUDA"
    if [[ -d "$SD_DIR/.git" ]]; then
        git -C "$SD_DIR" pull --ff-only
        git -C "$SD_DIR" submodule update --init --recursive
    else
        git clone --recursive https://github.com/leejet/stable-diffusion.cpp "$SD_DIR"
    fi
    # папку переносили — старая сборка помнит прежний путь и не пересоберётся
    if [[ -f "$SD_DIR/build/CMakeCache.txt" ]] && ! grep -q "CMAKE_HOME_DIRECTORY:INTERNAL=$SD_DIR\$" "$SD_DIR/build/CMakeCache.txt"; then
        echo "   папка проекта изменилась — собираю заново"
        rm -rf "$SD_DIR/build"
    fi
    cmake -S "$SD_DIR" -B "$SD_DIR/build" -DSD_CUDA=ON -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES=120 -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc
    cmake --build "$SD_DIR/build" --config Release -j"$(nproc)"
    ls -l "$SD_DIR/build/bin/" | grep -E "sd-server|sd-cli" || { echo "sd-server не собрался"; exit 1; }
fi

echo "== Утилита загрузки с Hugging Face"
if ! "$VENV/bin/python" -c "" 2>/dev/null; then   # нет или сломалось после переноса папки
    rm -rf "$VENV"
    sudo apt install -y python3-venv >/dev/null
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q -U huggingface_hub

mkdir -p "$MODELS"
echo "== Загрузка моделей в $MODELS"
QWEN=$QWEN MOSS=$MOSS TURBO=$TURBO MODELS="$MODELS" "$VENV/bin/python" - <<'PY'
import os, fnmatch
from huggingface_hub import HfApi, hf_hub_download

api = HfApi()
dest = os.environ["MODELS"]

def files(repo):
    return {f.path: getattr(f, "size", 0) or 0
            for f in api.list_repo_tree(repo, recursive=True) if hasattr(f, "size")}

def pick(repo, pattern, prefer=None, exclude="mmproj"):
    """Файл репозитория по шаблону; из нескольких — по списку предпочтительных квантизаций."""
    fs = files(repo)
    cand = [p for p in fs if fnmatch.fnmatch(p.lower(), pattern.lower()) and exclude not in p.lower()]
    if not cand:
        print(f"  !! в {repo} нет файла по шаблону {pattern}. Есть:")
        for p in sorted(fs):
            print("     ", p)
        raise SystemExit(1)
    for q in prefer or []:
        for p in cand:
            if q.lower() in p.lower():
                return p, fs[p]
    return cand[0], fs[cand[0]]

def get(repo, pattern, prefer=None):
    path, size = pick(repo, pattern, prefer)
    print(f"  {repo}/{path}  ({size / 2**30:.1f} ГБ)")
    hf_hub_download(repo, path, local_dir=os.path.join(dest, repo.split("/")[-1]))

# Krea 2 Turbo: DiT 12.9B (+ Qwen3-VL 4B как текстовый энкодер, VAE от Wan 2.1)
get("realrebelai/KREA-2_GGUFs", "turbo/*.gguf", ["Q5_K_M", "Q4_K_M", "Q6_K", "Q8_0"])
get("Qwen/Qwen3-VL-4B-Instruct-GGUF", "*.gguf", ["Q4_K_M"])
get("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "split_files/vae/wan_2.1_vae.safetensors")

def qwen_common():
    get("Qwen/Qwen3-VL-8B-Instruct-GGUF", "*.gguf", ["Q4_K_M"])
    path, size = pick("Qwen/Qwen3-VL-8B-Instruct-GGUF", "*mmproj*.gguf", ["F16", "Q8_0"], exclude="\x00")
    hf_hub_download("Qwen/Qwen3-VL-8B-Instruct-GGUF", path,
                    local_dir=os.path.join(dest, "Qwen3-VL-8B-Instruct-GGUF"))
    get("Comfy-Org/Qwen-Image-2.1", "vae/*.safetensors")

if os.environ.get("TURBO") == "1":
    # Qwen-Image 2.1 Turbo: 8 шагов без CFG; энкодер, зрение и VAE — те же, что у Qwen-Image 2.1
    get("unsloth/Qwen-Image-2.1-Turbo-GGUF", "*.gguf", ["Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M"])
    qwen_common()
if os.environ.get("QWEN") == "1":
    get("leejet/Qwen-Image-2.1-GGUF", "*.gguf", ["Q4_K_M", "Q5_K_M", "Q4_0", "Q8_0"])
    get("Qwen/Qwen3-VL-8B-Instruct-GGUF", "*.gguf", ["Q4_K_M"])
    # зрение энкодера: Qwen-Image рисует по образцам (похожие лица, поза по фото)
    path, size = pick("Qwen/Qwen3-VL-8B-Instruct-GGUF", "*mmproj*.gguf", ["F16", "Q8_0"], exclude="\x00")
    print(f"  Qwen/Qwen3-VL-8B-Instruct-GGUF/{path}  ({size / 2**30:.1f} ГБ)")
    hf_hub_download("Qwen/Qwen3-VL-8B-Instruct-GGUF", path,
                    local_dir=os.path.join(dest, "Qwen3-VL-8B-Instruct-GGUF"))
    get("Comfy-Org/Qwen-Image-2.1", "vae/*.safetensors")
if os.environ.get("MOSS") == "1":
    # MOSS-Image (нужен stable-diffusion.cpp master-975 или новее — сборка выше обновляет)
    get("unsloth/MOSS-Image-SFT-GGUF", "*.gguf", ["UD-Q4_K_XL", "Q4_K_M", "UD-Q5_K_XL"])
    get("unsloth/Qwen3.5-9B-GGUF", "*.gguf", ["Q4_K_M", "Q5_K_M", "Q8_0"])
    get("unsloth/MOSS-Image-SFT-FP8", "vae/diffusion_pytorch_model.safetensors")
    get("unsloth/MOSS-Image-SFT-FP8", "tokenizer/tokenizer.json")
print("Готово.")
PY

echo "== Готово. Проверка профилей — кнопка «Профили изображений» в окне моста."
