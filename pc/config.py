"""Настройки приложения: data/config.json в папке проекта (в git не попадает)"""
import json
import os
import re
import secrets
import string
from dataclasses import asdict, dataclass, field
from pathlib import Path

import paths

# всё личное — в data/ проекта: настройки, чаты, карточки, картинки (LLM_BRIDGE_DATA — другая папка)
DATA_DIR = Path(os.environ.get("LLM_BRIDGE_DATA") or paths.ROOT / "data")
CONFIG_DIR = DATA_DIR
CONFIG_PATH = CONFIG_DIR / "config.json"

HOME = Path.home()

# без похожих символов (l/1/I, 0/O) — пароль иногда приходится вводить руками
_PSK_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "lI1O0o")


@dataclass
class Config:
    # --- llama-server ---
    # пути — относительно корня проекта (см. paths.py); абсолютные и «~» тоже понимаются
    models_dir: str = paths.MODELS   # llm/, image/, lora/, upscale/, whisper/ — см. models.py
    llama_bin: str = paths.LLAMA_BIN
    model: str = "models/llm/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ3_XS.gguf"
    mmproj: str = "models/llm/Qwen3.6-27B-mmproj-hybrid-Q8_0-F16.gguf"  # пусто = без картинок
    ngl: int = 99
    ctx: int = 16384
    llama_port: int = 8080
    llama_extra_args: list = field(default_factory=list)  # например ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]

    # --- фоновая модель: маленькая, на процессоре — память, отношения, состояние квеста ---
    bg_model: str = "models/llm/helper/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"  # пусто = выкл
    bg_port: int = 8081
    bg_ngl: int = 0        # 0 — целиком на процессоре: видеокарта остаётся большой модели и рисованию
    bg_ctx: int = 8192
    bg_threads: int = 0    # 0 — llama-server выберет сам
    bg_autostart: bool = True   # запускать вместе с мостом, если файл модели есть

    # --- Wi-Fi Direct ---
    wifi_iface: str = "wlp5s0"
    p2p_device_name: str = "LLM-PC"
    p2p_freq: int = 2  # 2 = любой канал 2,4 ГГц, 5 = любой 5 ГГц, или точная частота в МГц (2462, 5180 ...)
    p2p_ssid: str = ""  # постоянные имя сети и пароль группы: генерируются один раз
    p2p_psk: str = ""
    p2p_ip: str = "192.168.49.1"
    dhcp_start: str = "192.168.49.10"
    dhcp_end: str = "192.168.49.50"
    remove_group_on_stop: bool = True

    # --- API для телефона ---
    bridge_port: int = 8765
    token: str = ""

    # --- изображения (stable-diffusion.cpp) ---
    sd_server_bin: str = paths.SD_BIN
    sd_port: int = 7861

    # --- запуск ---
    autostart_model: bool = False
    autostart_link: bool = False
    close_to_tray: bool = True
    helper: str = "/usr/local/sbin/llm-bridge-helper"

    @classmethod
    def load(cls) -> "Config":
        data = {}
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        known = set(cls.__dataclass_fields__)
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        for k in PATH_KEYS:   # в памяти пути абсолютные; в файле — относительно проекта
            if getattr(cfg, k):
                setattr(cfg, k, _locate(k, getattr(cfg, k)))
        if not cfg.token:
            cfg.token = new_token()
        if not cfg.p2p_ssid.startswith("DIRECT-") or len(cfg.p2p_ssid.encode()) > 32:
            cfg.p2p_ssid = new_ssid(cfg.p2p_device_name)
        if not (8 <= len(cfg.p2p_psk) <= 63):
            cfg.p2p_psk = new_psk()
        cfg.save()  # дописывает новые поля в старый конфиг
        return cfg

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        data = asdict(self)
        for k in PATH_KEYS:
            data[k] = paths.shorten(data[k])
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)  # в конфиге токен и пароль сети
        tmp.replace(CONFIG_PATH)


PATH_KEYS = ("models_dir", "llama_bin", "model", "mmproj", "bg_model", "sd_server_bin")
_TOOLS = {"llama_bin": paths.LLAMA_BIN, "sd_server_bin": paths.SD_BIN, "models_dir": paths.MODELS}


def _locate(key: str, value: str) -> str:
    """Путь из настроек → существующий файл. Если по записанному пути ничего нет (проект
    перенесли, модели переложили в папку проекта) — ищем на новом месте: инструменты в tools/,
    модель с тем же именем в models/llm."""
    for p in paths.variants(value):
        if os.path.exists(p):
            return p
    if key in _TOOLS:
        p = paths.expand(_TOOLS[key])
        if os.path.exists(p) or key == "models_dir":
            return p
    else:
        name = os.path.basename(value)
        for p in sorted((paths.ROOT / paths.MODELS / "llm").rglob(name)) if name else []:
            return str(p)
    return paths.expand(value)


def new_token() -> str:
    return secrets.token_urlsafe(24)


def new_psk(n: int = 12) -> str:
    return "".join(secrets.choice(_PSK_ALPHABET) for _ in range(n))


def new_ssid(device_name: str) -> str:
    """DIRECT-xy-<имя>: такой формат требует Android для подключения по имени сети."""
    xy = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(2))
    name = re.sub(r"[^A-Za-z0-9_-]", "", device_name) or "PC"
    return f"DIRECT-{xy}-{name}"[:32]
