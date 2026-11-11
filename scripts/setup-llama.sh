#!/bin/bash
# llama.cpp (llama-server) с CUDA: исходники и сборка — в tools/llama.cpp проекта.
#
#   ./scripts/setup-llama.sh          клонировать или обновить и собрать
#   ./scripts/setup-llama.sh --clean  собрать с нуля (после смены драйвера или CUDA)
#
# Запускать при закрытом мосте. Текстовую модель скрипт не скачивает: положите .gguf
# в models/llm/ и выберите её в окне моста.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/tools/llama.cpp"
mkdir -p "$ROOT/tools"
[[ "${1:-}" == "--clean" ]] && rm -rf "$DIR/build"

if [[ -d "$DIR/.git" ]]; then
    git -C "$DIR" pull --ff-only
else
    git clone https://github.com/ggml-org/llama.cpp "$DIR"
fi
# папку переносили — старая сборка помнит прежний путь и не пересоберётся
if [[ -f "$DIR/build/CMakeCache.txt" ]] && ! grep -q "CMAKE_HOME_DIRECTORY:INTERNAL=$DIR\$" "$DIR/build/CMakeCache.txt"; then
    echo "Папка проекта изменилась — собираю заново"
    rm -rf "$DIR/build"
fi
CUDA=()
[[ -x /usr/local/cuda/bin/nvcc ]] && CUDA=(-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc)
cmake -S "$DIR" -B "$DIR/build" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release "${CUDA[@]}"
cmake --build "$DIR/build" --config Release -j"$(nproc)" --target llama-server
ls -l "$DIR/build/bin/llama-server"
echo "Готово. Мост найдёт llama-server сам."
