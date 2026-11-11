#!/bin/bash
# Установка llm-bridge: зависимости, helper, правило sudo, группа netdev.
set -euo pipefail
cd "$(dirname "$0")"

echo "== Пакеты"
sudo apt install -y python3-pyqt6 python3-aiohttp python3-qrcode dnsmasq-base wpasupplicant

echo "== Helper"
sudo install -m 755 -o root -g root helper/llm-bridge-helper /usr/local/sbin/llm-bridge-helper

echo "== Правило sudo (helper без пароля только для $USER)"
TMP=$(mktemp)
echo "$USER ALL=(root) NOPASSWD: /usr/local/sbin/llm-bridge-helper" > "$TMP"
sudo visudo -cf "$TMP"
sudo install -m 440 -o root -g root "$TMP" /etc/sudoers.d/llm-bridge
rm -f "$TMP"

echo "== Доступ к wpa_supplicant"
if id -nG "$USER" | grep -qw netdev; then
    echo "Пользователь уже в группе netdev"
else
    sudo usermod -aG netdev "$USER"
    echo "Добавлен в группу netdev. Перелогиньтесь или запускайте через ./run.sh (он использует sg)."
fi

chmod +x main.py run.sh
echo "Готово. Запуск: ./run.sh"
