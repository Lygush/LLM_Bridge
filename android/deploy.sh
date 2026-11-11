#!/bin/bash
# Сборка и установка на телефон по беспроводной отладке одной командой.
#   ./deploy.sh             собрать, установить, запустить
#   ./deploy.sh 41234       то же, указав новый порт беспроводной отладки
#   ./deploy.sh --no-build  только установить уже собранный APK
#   ./deploy.sh --log       после запуска показать лог приложения (Ctrl+C — выход)
#
# Один раз нужно сопрячь телефон: adb pair <IP:порт> (см. README).
# Порт отладки меняется, когда на телефоне заново включается «Беспроводная отладка».
# Скрипт ищет телефон так: уже подключён → порт из аргумента → mDNS → последний
# адрес (.adb-last) → сканирование портов (если установлен nmap).
# IP телефона в группе Wi-Fi Direct берётся из DHCP-аренд моста.
set -euo pipefail
cd "$(dirname "$0")"

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21-openjdk-amd64}"
ADB="${ADB:-$HOME/Android/Sdk/platform-tools/adb}"
command -v "$ADB" >/dev/null 2>&1 || ADB=adb
PKG=dev.llmbridge.client
APK=app/build/outputs/apk/debug/app-debug.apk
LAST=.adb-last
LEASES=/run/llm-bridge/dnsmasq.leases

BUILD=1; LOG=0; PORT=""
for a in "$@"; do
    case "$a" in
        --no-build) BUILD=0 ;;
        --log) LOG=1 ;;
        [0-9]*) PORT="$a" ;;
        *) echo "Неизвестный аргумент: $a"; exit 1 ;;
    esac
done

log() { echo "$@" >&2; }

# телефон: подключённое устройство, кроме эмулятора
find_device() {
    "$ADB" devices | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1; exit}'
}

remember() {  # запомнить адрес вида IP:порт
    [[ "$1" =~ ^[0-9.]+:[0-9]+$ ]] && echo "$1" > "$LAST"
    return 0
}

try_connect() {  # IP:порт → serial или пусто
    local out
    log "  пробую $1"
    out=$(timeout 6 "$ADB" connect "$1" 2>&1 || true)
    if [[ "$out" == *"connected to"* ]]; then
        sleep 0.5
        find_device
    fi
}

phone_ip() {
    # последний клиент DHCP моста, иначе IP из .adb-last
    if [[ -r "$LEASES" ]] && [[ -s "$LEASES" ]]; then
        sort -n "$LEASES" | tail -1 | awk '{print $3}'
    elif [[ -f "$LAST" ]]; then
        cut -d: -f1 "$LAST"
    fi
}

connect_phone() {
    local dev addr ip p
    dev=$(find_device)
    if [[ -n "$dev" ]]; then remember "$dev"; echo "$dev"; return; fi

    ip=$(phone_ip)

    # 1) порт указан явно
    if [[ -n "$PORT" && -n "$ip" ]]; then
        log "Подключение к $ip:$PORT"
        dev=$(try_connect "$ip:$PORT")
        if [[ -n "$dev" ]]; then remember "$ip:$PORT"; echo "$dev"; return; fi
    fi

    # 2) mDNS: телефон объявляет адрес отладки (обычно в домашней сети).
    #    Порт одинаков на всех сетях телефона — сначала пробуем его по Wi-Fi Direct:
    #    домашнюю сеть может перехватывать VPN на ПК.
    for addr in $(timeout 5 "$ADB" mdns services 2>/dev/null | awk '/_adb-tls-connect\._tcp/ {print $NF}'); do
        log "Найден через mDNS: $addr"
        p=${addr##*:}
        if [[ -n "$ip" ]]; then
            dev=$(try_connect "$ip:$p")
            if [[ -n "$dev" ]]; then remember "$ip:$p"; echo "$dev"; return; fi
        fi
        dev=$(try_connect "$addr")
        if [[ -n "$dev" ]]; then remember "$addr"; echo "$dev"; return; fi
    done

    # 3) последний известный адрес
    if [[ -f "$LAST" ]]; then
        addr=$(cat "$LAST")
        log "Последний адрес: $addr"
        dev=$(try_connect "$addr")
        if [[ -n "$dev" ]]; then echo "$dev"; return; fi
    fi

    # 4) поиск порта сканированием (порт отладки — в диапазоне 30000–49999), не дольше 40 с
    if [[ -n "$ip" ]] && command -v nmap >/dev/null 2>&1; then
        if ! ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
            log "Телефон $ip не отвечает — он подключён к группе Wi-Fi Direct?"
            echo ""
            return
        fi
        log "Поиск порта отладки на $ip (до 40 с)…"
        for p in $(nmap -Pn -T4 --host-timeout 40s --open -p 30000-49999 "$ip" 2>/dev/null \
                   | awk -F/ '/^[0-9]+\/tcp/ {print $1}'); do
            dev=$(try_connect "$ip:$p")
            if [[ -n "$dev" ]]; then remember "$ip:$p"; echo "$dev"; return; fi
        done
    fi
    echo ""
}

if [[ $BUILD == 1 ]]; then
    echo "== Сборка"
    ./gradlew -q assembleDebug
fi
[[ -f "$APK" ]] || { echo "APK не найден: $APK"; exit 1; }

echo "== Поиск телефона"
DEV=$(connect_phone)
if [[ -z "$DEV" ]]; then
    echo "Телефон не найден. Проверьте:"
    echo "  - на телефоне включена «Беспроводная отладка» (Для разработчиков);"
    echo "  - телефон подключён к группе Wi-Fi Direct ПК (или к той же сети, что ПК);"
    echo "  - укажите порт со строки «IP-адрес и порт»: ./deploy.sh ПОРТ"
    command -v nmap >/dev/null 2>&1 || echo "  - для автопоиска порта: sudo apt install -y nmap"
    exit 1
fi
echo "Телефон: $DEV"

echo "== Установка"
"$ADB" -s "$DEV" install -r "$APK"

echo "== Запуск"
"$ADB" -s "$DEV" shell am start -n "$PKG/.MainActivity" >/dev/null

if [[ $LOG == 1 ]]; then
    echo "== Лог (Ctrl+C — выход)"
    sleep 1
    PID=$("$ADB" -s "$DEV" shell pidof "$PKG" | tr -d '\r')
    "$ADB" -s "$DEV" logcat --pid="$PID" -v time
fi
echo "Готово."
