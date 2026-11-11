#!/bin/bash
# Сборка приложения и установка на телефон. Аргументы — как у android/deploy.sh:
# порт беспроводной отладки, --no-build, --log.
exec "$(cd "$(dirname "$0")" && pwd)/android/deploy.sh" "$@"
