#!/bin/bash
# Запуск llm-bridge. Аргументы передаются в main.py (--minimized, --headless).
# Доступ к wpa_supplicant даёт группа netdev — она применяется после перезагрузки.
DIR="$(cd "$(dirname "$0")" && pwd)"

if id -nG | grep -qw netdev; then
    exec python3 "$DIR/main.py" "$@"
fi

echo "Группа netdev ещё не применилась к текущей сессии."
echo "Перезагрузите компьютер, затем запустите ./run.sh"
exit 1
