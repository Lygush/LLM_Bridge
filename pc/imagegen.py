"""Генерация изображений: sd-server (stable-diffusion.cpp) и распределение видеопамяти.

Видеокарта одна, и языковая модель вместе с моделью изображений в неё не помещаются.
Vram следит, кто сейчас загружен:
  - перед рисованием выгружает llama-server и запускает sd-server с моделями профиля;
  - перед текстовым ответом останавливает sd-server и возвращает llama-server.
Серия картинок подряд не вызывает перезагрузок — переключение только при смене задачи.
Все вызовы — из потока сервера под общей блокировкой генератора.

Профили — data/image_profiles.json (создаётся с шаблонами при первом запуске).
Пути к моделям могут быть шаблонами (*), берётся первый найденный файл.
"""
import paths
import asyncio
import base64
import fnmatch
import json
import os
import random
import time
from collections import deque

from aiohttp import ClientError, ClientSession, ClientTimeout

from config import CONFIG_DIR
from images import image_path
from models import ensure_dirs

PROFILES_PATH = CONFIG_DIR / "image_profiles.json"

# файлы моделей → флаги sd-server
MODEL_FLAGS = {
    "model": "-m", "diffusion_model": "--diffusion-model", "vae": "--vae", "llm": "--llm",
    "llm_vision": "--llm_vision", "clip_l": "--clip_l", "clip_g": "--clip_g", "t5xxl": "--t5xxl",
    "tokenizer": "--tokenizer",
}

# Отрицательный промпт по умолчанию для моделей с CFG (у турбо-моделей CFG=1, он не действует)
NEGATIVE = "blurry, low quality, jpeg artifacts, deformed, bad anatomy, extra fingers, watermark"

# Параметры — по документации stable-diffusion.cpp (docs/krea2.md, qwen_image_2.1.md, moss_image.md).
# rev — версия настроек шаблона: при её росте старые значения по умолчанию в вашем файле
# обновляются (см. UPGRADES), а то, что вы меняли сами, не трогается.
TEMPLATE = [
    {
        # Krea 2 Turbo: 8 шагов без CFG — самая быстрая; фотореализм, фоны
        "id": "krea2-turbo",
        "name": "Krea 2 Turbo",
        "about": "быстрая (8 шагов), фотореализм",
        "roles": ["generate"],
        "rev": 2,
        "files": {
            "diffusion_model": "models/image/*krea*turbo*.gguf",
            "llm": "models/image/*qwen3*vl*4b*q4_k_m*.gguf",
            "vae": "models/image/*wan_2.1_vae*.safetensors",
        },
        "extra_args": ["--diffusion-fa", "--offload-to-cpu"],
        "width": 1024, "height": 1024, "multiple": 16, "steps": 8, "cfg": 1.0, "sampler": "euler",
        "negative": "", "style": "",
    },
    {
        # Qwen-Image 2.1: с mmproj (зрение энкодера) умеет рисовать по образцам — похожие лица
        "id": "qwen-image",
        "name": "Qwen-Image 2.1",
        "about": "рисует по образцу: то же лицо, поза с фото, правка",
        "roles": ["generate", "edit"],
        "rev": 2,
        "files": {
            "diffusion_model": "models/image/*qwen*image*2.1*.gguf",
            "llm": "models/image/*qwen3*vl*8b*q4_k_m*.gguf",
            "vae": "models/image/*qwen_image_2.1_vae*.safetensors",
        },
        "exclude": {"diffusion_model": "*turbo*"},
        "optional_files": {
            "llm_vision": "models/image/*mmproj*qwen3*vl*8b*.gguf",
        },
        "extra_args": ["--diffusion-fa", "--offload-to-cpu"],
        "width": 1024, "height": 1024, "multiple": 32, "steps": 20, "cfg": 6.0, "sampler": "euler",
        "negative": NEGATIVE, "style": "",
    },
    {
        # Qwen-Image 2.1 Turbo: те же умения за 8 шагов без CFG (свой файл модели и расписание сигм)
        "id": "qwen-image-turbo",
        "name": "Qwen-Image 2.1 Turbo",
        "about": "как Qwen-Image, но 8 шагов — в разы быстрее",
        "roles": ["generate", "edit"],
        "rev": 2,
        "files": {
            "diffusion_model": "models/image/*qwen*image*2.1*turbo*.gguf",
            "llm": "models/image/*qwen3*vl*8b*q4_k_m*.gguf",
            "vae": "models/image/*qwen_image_2.1_vae*.safetensors",
        },
        "optional_files": {
            "llm_vision": "models/image/*mmproj*qwen3*vl*8b*.gguf",
        },
        "extra_args": ["--diffusion-fa", "--offload-to-cpu"],
        "width": 1024, "height": 1024, "multiple": 32, "steps": 8, "cfg": 1.0, "sampler": "euler",
        "sigmas": [1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0],
        "negative": "", "style": "",
    },
    {
        # MOSS-Image SFT: 5B DiT; реализм и аниме, сильна в надписях и раскладке; 50 шагов с CFG 3
        "id": "moss-image",
        "name": "MOSS-Image SFT",
        "about": "качественная (50 шагов), надписи на картинке",
        "roles": ["generate", "text"],
        "rev": 2,
        "files": {
            "diffusion_model": "models/image/*moss-image-sft*.gguf",
            "llm": "models/image/*qwen3.5-9b*.gguf",
            "vae": "models/image/MOSS-Image-SFT-FP8/*diffusion_pytorch_model*.safetensors",
            "tokenizer": "models/image/MOSS-Image-SFT-FP8/*tokenizer*.json",
        },
        "extra_args": ["--offload-to-cpu"],
        "width": 1024, "height": 1024, "multiple": 16, "steps": 50, "cfg": 3.0, "sampler": "euler",
        "negative": NEGATIVE, "style": "",
    },
]

# Обновление старых значений по умолчанию: (профиль, ключ, было, стало). Применяется один раз,
# когда rev профиля в файле меньше rev шаблона, и только если значение не меняли руками.
UPGRADES = [
    ("qwen-image", "cfg", 2.5, 6.0),           # документация sd.cpp: --cfg-scale 6.0
    ("qwen-image", "negative", "", NEGATIVE),
    ("moss-image", "negative", "", NEGATIVE),
    ("moss-image", "roles", ["text"], ["generate", "text"]),
]

# Задачи рисования. Для каждой — какая роль нужна и в каком порядке пробовать профили,
# когда в настройках стоит «Авто». Пользователь может закрепить профиль за задачей с телефона.
TASKS = [
    {"id": "portrait", "title": "Портрет персонажа", "hint": "рисуется редко — важнее качество",
     "roles": ["generate"], "prefer": ["moss-image", "qwen-image", "krea2-turbo", "qwen-image-turbo"]},
    {"id": "photo", "title": "Картинки в чате", "hint": "сцены и фото без персонажей с портретом",
     "roles": ["generate"], "prefer": ["moss-image", "krea2-turbo", "qwen-image", "qwen-image-turbo"]},
    {"id": "likeness", "title": "С лицом персонажа", "hint": "селфи, фото по образцу портрета или позы",
     "roles": ["edit"], "prefer": ["qwen-image", "qwen-image-turbo"]},
    {"id": "sprite", "title": "Эмоции для новеллы", "hint": "шесть картинок по образцу портрета",
     "roles": ["edit", "generate"], "prefer": ["qwen-image", "qwen-image-turbo", "moss-image", "krea2-turbo"]},
    {"id": "background", "title": "Фоны новеллы", "hint": "рисуются сами по ходу истории — важнее скорость",
     "roles": ["generate"], "prefer": ["krea2-turbo", "qwen-image-turbo", "moss-image", "qwen-image"]},
    {"id": "text", "title": "Надписи", "hint": "вывески, записки, плакаты с текстом",
     "roles": ["text", "generate"], "prefer": ["moss-image", "qwen-image", "qwen-image-turbo", "krea2-turbo"]},
]
TASK_IDS = [t["id"] for t in TASKS]

# Качество: множители шагов и размера. У турбо-моделей (CFG ≤ 1) число шагов фиксировано.
QUALITY = {"fast": (0.7, 1.0), "normal": (1.0, 1.0), "high": (1.3, 1.25)}


class ImageError(Exception):
    pass


def resolve(path: str, exclude: str = None):
    """Путь или шаблон → существующий файл или None (exclude — шаблон имён, которые не подходят).
    В шаблоне * — любые символы; имя ищется во вложенных папках, без учёта регистра
    (имена файлов на Hugging Face бывают разными: KREA-2-TURBO-Q4_K_M.gguf и т.п.)."""
    for p in paths.variants(path):      # как записано, затем models/ проекта
        f = _resolve_one(p, exclude)
        if f:
            return f
    return None


def _resolve_one(p: str, exclude: str = None):
    if not any(c in p for c in "*?["):
        return p if os.path.exists(p) else None
    base, pattern = os.path.split(p)
    while any(c in base for c in "*?["):       # шаблон в папке — искать от первой обычной
        base, part = os.path.split(base)
        pattern = part + "/" + pattern
    pattern = pattern.split("/")[-1].lower()
    found = []
    for root, _dirs, files in os.walk(base):
        for f in files:
            if fnmatch.fnmatch(f.lower(), pattern) and \
                    not (exclude and fnmatch.fnmatch(f.lower(), exclude.lower())):
                found.append(os.path.join(root, f))
    return sorted(found)[0] if found else None


def pfile(p: dict, key: str, optional: bool = False):
    """Файл модели профиля (с учётом исключений вроде «не turbo»)."""
    path = (p.get("optional_files") if optional else p["files"]).get(key)
    return resolve(path, (p.get("exclude") or {}).get(key)) if path else None


def load_profiles() -> list:
    if not PROFILES_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_PATH.write_text(json.dumps(TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for p in data if isinstance(data, list) else []:
        if isinstance(p, dict) and p.get("id") and isinstance(p.get("files"), dict):
            out.append(p)
    # новые профили из шаблона дописываются в файл (ваши правки старых не трогаются),
    # а у старых появляются новые ключи шаблона (роли, необязательные файлы)
    have = {p["id"] for p in out}
    new = [t for t in TEMPLATE if t["id"] not in have]
    changed = False
    for p in out:
        # в первой версии профиля MOSS путь к токенизатору не учитывал подпапку tokenizer/
        if p["files"].get("tokenizer") == "models/image/MOSS-Image-SFT-FP8/tokenizer.json":
            p["files"]["tokenizer"] = "models/image/MOSS-Image-SFT-FP8/*tokenizer*.json"
            changed = True
        t = next((t for t in TEMPLATE if t["id"] == p["id"]), None)
        for k in ("roles", "optional_files", "exclude", "about", "multiple"):
            if t and k in t and k not in p:
                p[k] = t[k]
                changed = True
        if t and int(p.get("rev", 1)) < int(t.get("rev", 1)):
            for pid, key, old, new in UPGRADES:
                if pid == p["id"] and p.get(key) == old:
                    p[key] = new
            p["rev"] = t["rev"]
            changed = True
    if (new or changed) and isinstance(data, list):
        try:
            PROFILES_PATH.write_text(json.dumps(data + new, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        except OSError:
            pass
        out += new
    return out


def profile_info(p: dict) -> dict:
    """Описание профиля для телефона: без путей, с признаком готовности."""
    missing = [k for k in p["files"] if not pfile(p, k)]
    return {
        "id": p["id"], "name": p.get("name", p["id"]), "roles": roles(p),
        "about": p.get("about", ""), "fast": float(p.get("cfg", 1.0)) <= 1.0,
        "width": int(p.get("width", 1024)), "height": int(p.get("height", 1024)),
        "steps": int(p.get("steps", 20)), "cfg": float(p.get("cfg", 1.0)),
        "ready": not missing, "missing": missing,
    }


def roles(p: dict) -> list:
    """Что умеет профиль: generate — рисовать, edit — рисовать по образцам (нужен файл зрения),
    text — надписи и раскладка."""
    r = list(p.get("roles") or ([p["role"]] if p.get("role") else ["generate"]))
    if "edit" in r and "llm_vision" in (p.get("optional_files") or {}) and \
            not pfile(p, "llm_vision", optional=True):
        r.remove("edit")
    return r


def find_profile(role: str, prefer: str = None):
    """Готовый профиль с нужной ролью (предпочтительно выбранный в чате) или None."""
    ready = [p for p in load_profiles() if profile_info(p)["ready"] and role in roles(p)]
    return next((p for p in ready if p["id"] == prefer), ready[0] if ready else None)


def candidates(task: str, routes: dict = None, need: str = None) -> list:
    """Готовые профили для задачи по порядку: закреплённый пользователем, затем «Авто».
    need — роль, без которой нельзя (edit, когда рисуем по образцу). Первый — основной,
    остальные — запасные: если модель не загрузилась, рисует следующая."""
    t = next((x for x in TASKS if x["id"] == task), TASKS[1])
    ready = [p for p in load_profiles() if profile_info(p)["ready"]]
    out = []
    for want in ([need] if need else t["roles"]):
        able = [p for p in ready if want in roles(p) and p not in out]
        order = {pid: i for i, pid in enumerate(t["prefer"])}
        able.sort(key=lambda p: order.get(p["id"], len(order)))
        out += able
    fixed = (routes or {}).get(task)
    out.sort(key=lambda p: p["id"] != fixed)      # закреплённый — первым (сортировка устойчива)
    return out


def routes_info(routes: dict) -> list:
    """Таблица «задача → модель» для телефона."""
    out = []
    for t in TASKS:
        auto = candidates(t["id"])
        opts = [p for p in auto]
        fixed = (routes or {}).get(t["id"]) or ""
        out.append({"id": t["id"], "title": t["title"], "hint": t["hint"],
                    "choice": fixed if any(p["id"] == fixed for p in opts) else "",
                    "auto": auto[0]["id"] if auto else "",
                    "options": [{"id": p["id"], "name": p.get("name", p["id"]),
                                 "about": p.get("about", "")} for p in opts]})
    return out


def _snap(v: float, m: int) -> int:
    return max(m * 8, int(round(v / m)) * m)


def tuned(profile: dict, params: dict, quality: str = "normal") -> dict:
    """Параметры рисования под конкретную модель: шаги и CFG профиля, качество, размеры кратны
    шагу сетки модели (Qwen-Image — 32, MOSS и Krea — 16)."""
    ksteps, ksize = QUALITY.get(quality, QUALITY["normal"])
    m = int(profile.get("multiple", 16))
    cfg = float(params.get("cfg") or profile.get("cfg", 1.0))
    steps = params.get("steps")
    if not steps:
        steps = int(profile.get("steps", 20))
        if cfg > 1.0 and not profile.get("sigmas"):   # у турбо-моделей шаги фиксированы
            steps = max(8, int(round(steps * ksteps)))
    w = float(params.get("width") or profile.get("width", 1024))
    h = float(params.get("height") or profile.get("height", 1024))
    if not params.get("exact_size"):
        w, h = w * ksize, h * ksize
    return {"steps": int(steps), "cfg": cfg, "width": _snap(w, m), "height": _snap(h, m)}


class Vram:
    def __init__(self, cfg, session: ClientSession, log, request_llama):
        self.cfg = cfg
        self.session = session
        self.log = log
        self.request_llama = request_llama   # request_llama(True/False) — запустить/остановить (поток GUI)
        self.mode = "llm"                    # llm | image
        self.sd = None
        self.sd_profile = None
        self.sd_tail = deque(maxlen=30)
        self._reader = None

    @property
    def sd_url(self) -> str:
        return f"http://127.0.0.1:{self.cfg.sd_port}"

    @property
    def llama_url(self) -> str:
        return f"http://127.0.0.1:{self.cfg.llama_port}"

    async def _health(self, url: str):
        try:
            async with self.session.get(url, timeout=ClientTimeout(total=3)) as r:
                return r.status
        except (ClientError, asyncio.TimeoutError, ConnectionError):
            return None

    def sd_alive(self) -> bool:
        return self.sd is not None and self.sd.returncode is None

    # ------------------------------------------------------------- llama
    async def ensure_llm(self, on_stage=None):
        if self.sd_alive() or self.sd is not None:
            await self.stop_sd()
        code = await self._health(f"{self.llama_url}/health")
        if code == 200:
            self.mode = "llm"
            return
        if on_stage:
            on_stage("loading_llm")
        if code is None:
            self.log("Загрузка языковой модели…")
            self.request_llama(True)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if await self._health(f"{self.llama_url}/health") == 200:
                self.mode = "llm"
                return
        raise ImageError("Языковая модель не загрузилась за 5 минут — см. лог моста")

    async def _free_llm(self, on_stage):
        if await self._health(f"{self.llama_url}/health") is None:
            return
        if on_stage:
            on_stage("unloading_llm")
        self.log("Выгрузка языковой модели из видеопамяти…")
        self.request_llama(False)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            if await self._health(f"{self.llama_url}/health") is None:
                await asyncio.sleep(1.5)   # драйвер освобождает память не мгновенно
                return
        raise ImageError("llama-server не остановился. Если он запущен вручную, а не мостом, "
                         "остановите его, чтобы освободить видеопамять")

    # -------------------------------------------------------------- sd-server
    async def ensure_image(self, profile: dict, on_stage=None):
        if self.sd_alive() and self.sd_profile == profile["id"]:
            return
        if self.sd is not None:
            await self.stop_sd()
        self.mode = "image"          # статус для телефона: «модель выгружена на время рисования»
        await self._free_llm(on_stage)
        await self._start_sd(profile, on_stage)

    async def _start_sd(self, profile: dict, on_stage):
        binary = os.path.expanduser(self.cfg.sd_server_bin)
        if not os.path.exists(binary):
            raise ImageError(f"sd-server не найден: {binary} (sd_server_bin в конфиге)")
        args = []
        for key, path in profile["files"].items():
            flag = MODEL_FLAGS.get(key)
            if not flag:
                continue
            f = pfile(profile, key)
            if not f:
                raise ImageError(f"Профиль «{profile.get('name')}»: не найден файл {key} — {path}")
            args += [flag, f]
        for key in (profile.get("optional_files") or {}):
            f = pfile(profile, key, optional=True)
            if f and MODEL_FLAGS.get(key):
                args += [MODEL_FLAGS[key], f]
        root = ensure_dirs(self.cfg)
        args += [str(a) for a in profile.get("extra_args", [])]
        args += ["--listen-ip", "127.0.0.1", "--listen-port", str(self.cfg.sd_port),
                 "--lora-model-dir", str(root / "lora"),
                 "--hires-upscalers-dir", str(root / "upscale")]
        if on_stage:
            on_stage("loading_image_model")
        self.log("Запуск sd-server: " + " ".join([binary] + args))
        self.sd_tail.clear()
        self.sd = await asyncio.create_subprocess_exec(
            binary, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=paths.lib_env(binary))
        self.sd_profile = profile["id"]
        self._reader = asyncio.create_task(self._read_sd(self.sd))
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if not self.sd_alive():
                tail = "\n".join(list(self.sd_tail)[-5:])
                self.sd = None
                raise ImageError(f"sd-server завершился при загрузке:\n{tail}")
            if await self._sd_ready():
                self.log(f"sd-server готов: {profile.get('name')}")
                return
        await self.stop_sd()
        raise ImageError("sd-server не загрузил модели за 15 минут")

    async def _sd_ready(self) -> bool:
        try:
            async with self.session.get(f"{self.sd_url}/sdcpp/v1/models/status",
                                        timeout=ClientTimeout(total=3)) as r:
                if r.status == 200:
                    st = await r.json(content_type=None)
                    if st.get("state") == "error":
                        raise ImageError(f"sd-server: {st.get('error')}")
                    return st.get("state") in ("ready", None)
                if r.status != 404:
                    return False
            async with self.session.get(f"{self.sd_url}/sdcpp/v1/capabilities",
                                        timeout=ClientTimeout(total=3)) as r:
                return r.status == 200
        except (ClientError, asyncio.TimeoutError, ConnectionError, ValueError):
            return False

    async def _read_sd(self, proc):
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").rstrip()
                if text:
                    self.sd_tail.append(text)
                    if any(w in text.lower() for w in ("error", "loaded", "listening", "failed")):
                        self.log(f"[sd] {text}")
        except (asyncio.CancelledError, ValueError):
            pass

    async def stop_sd(self):
        proc, self.sd = self.sd, None
        self.sd_profile = None
        if proc and proc.returncode is None:
            self.log("Остановка sd-server…")
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        if self._reader:
            self._reader.cancel()
            self._reader = None

    # ------------------------------------------------------------- рисование
    async def generate(self, profile: dict, params: dict, on_progress) -> dict:
        """→ {"b64": png в base64, "seed": ...}. Отмена задачи отменяет и генерацию в sd-server."""
        seed = int(params.get("seed", -1))
        if seed < 0:
            seed = random.randint(0, 2**31 - 1)
        style = str(profile.get("style", "")).strip()
        prompt = str(params["prompt"]).strip()
        t = tuned(profile, params, str(params.get("quality") or "normal"))
        negative = params.get("negative")
        if negative is None:
            negative = profile.get("negative", "")
        sample = {
            "sample_method": str(profile.get("sampler", "euler")),
            "sample_steps": t["steps"],
            "guidance": {"txt_cfg": t["cfg"]},
        }
        if profile.get("scheduler"):
            sample["scheduler"] = str(profile["scheduler"])
        if profile.get("flow_shift"):
            sample["flow_shift"] = float(profile["flow_shift"])
        if profile.get("sigmas") and not params.get("steps"):
            sample["custom_sigmas"] = [float(x) for x in profile["sigmas"]]
        body = {
            "prompt": f"{prompt}, {style}" if style else prompt,
            "negative_prompt": str(negative or "") if t["cfg"] > 1.0 else "",
            "width": t["width"],
            "height": t["height"],
            "seed": seed,
            "batch_count": 1,
            "sample_params": sample,
            "output_format": "png",
        }
        refs = []
        for name in params.get("ref_images") or []:   # образцы: портрет персонажа, фото позы
            path = image_path(name)
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    refs.append(base64.b64encode(f.read()).decode())
        if refs:
            body["ref_images"] = refs[:3]
        async with self.session.post(f"{self.sd_url}/sdcpp/v1/img_gen", json=body,
                                     timeout=ClientTimeout(total=30)) as r:
            text = await r.text()
            if r.status not in (200, 202):
                raise ImageError(f"sd-server {r.status}: {text[:300]}")
            job = json.loads(text)
        jid = job["id"]
        try:
            while True:
                await asyncio.sleep(0.7)
                async with self.session.get(f"{self.sd_url}/sdcpp/v1/jobs/{jid}",
                                            timeout=ClientTimeout(total=10)) as r:
                    j = await r.json(content_type=None)
                st = j.get("status")
                pr = j.get("progress") or {}
                on_progress(pr.get("stage") or st, pr.get("completed"), pr.get("total"))
                if st == "completed":
                    imgs = (j.get("result") or {}).get("images") or []
                    if not imgs or not imgs[0].get("b64_json"):
                        raise ImageError("sd-server вернул пустой результат")
                    return {"b64": imgs[0]["b64_json"], "seed": seed, "width": body["width"],
                            "height": body["height"], "steps": body["sample_params"]["sample_steps"]}
                if st in ("failed", "cancelled"):
                    raise ImageError(str(j.get("error") or "генерация не удалась"))
                if not self.sd_alive():
                    raise ImageError("sd-server завершился во время генерации")
        except asyncio.CancelledError:
            try:
                async with self.session.post(f"{self.sd_url}/sdcpp/v1/jobs/{jid}/cancel",
                                             timeout=ClientTimeout(total=5)):
                    pass
            except (ClientError, asyncio.TimeoutError, ConnectionError):
                pass
            # sd-server не всегда прерывает расчёт сразу: если задача всё ещё идёт,
            # останавливаем его целиком — иначе следующая картинка или ответ ждали бы до конца
            try:
                await asyncio.sleep(1.5)
                async with self.session.get(f"{self.sd_url}/sdcpp/v1/jobs/{jid}",
                                            timeout=ClientTimeout(total=5)) as r:
                    st = (await r.json(content_type=None)).get("status")
                if st not in ("completed", "failed", "cancelled"):
                    self.log("Рисование отменено — останавливаю sd-server")
                    await self.stop_sd()
            except (ClientError, asyncio.TimeoutError, ConnectionError, ValueError):
                await self.stop_sd()
            raise
