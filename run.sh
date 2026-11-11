#!/bin/bash
# Запуск моста на ПК. Аргументы — как у pc/run.sh: --minimized, --headless.
exec "$(cd "$(dirname "$0")" && pwd)/pc/run.sh" "$@"
