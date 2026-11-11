"""HTTP/WebSocket-мост для телефона.

Сервер aiohttp работает в отдельном потоке со своим event loop. Он запускается
вместе с приложением на 127.0.0.1, а при включении канала Wi-Fi Direct
дополнительно слушает адрес группы — так генерация не прерывается при
переподключениях канала.

Все запросы, кроме /api/ping, — с заголовком Authorization: Bearer <token>.

REST (api 2):
  GET    /api/ping                         {"app","api","name"} — без токена
  GET    /api/status                       состояние модели, контекст, занятость
  GET    /api/chats                        список чатов
  POST   /api/chats                        {title?, system_prompt?, settings?}
  GET    /api/chats/{id}                   {"chat", "messages"} — активная ветка
  PATCH  /api/chats/{id}                   {title?, system_prompt?, settings?}
  DELETE /api/chats/{id}
  POST   /api/chats/{id}/messages          {content, replace_id?, images?: [base64]} — отправить
  GET    /api/images/{name}                файл картинки из сообщения
  GET    /api/image/profiles               профили генерации изображений
  POST   /api/chats/{id}/images            {prompt, profile?, negative?, width?, height?, steps?,
                                            cfg?, seed?, enhance?} — нарисовать (ответом станет
                                            картинка; enhance — модель доработает запрос)
  GET    /api/cards?kind=                 карточки персонажей/персон + описание полей
  POST   /api/cards                        {kind, data} — создать вручную
  POST   /api/cards/generate               {kind, text} — модель заполнит поля по описанию
  PATCH/DELETE /api/cards/{id}             изменить поля {data} / удалить
  POST   /api/cards/{id}/rewrite           {field, wish?, data?} → {value} — переписать поле
  POST   /api/cards/{id}/portrait          нарисовать портрет (события card.stage/card.updated)
  POST   /api/cards/{id}/chat              {persona_id?} — новый чат с персонажем
  GET/POST /api/cards/{id}/lore            лорбук мира / добавить запись {title, keys, content, always}
  POST   /api/cards/{id}/lore/generate     {text} — модель добавит записи по просьбе
  PATCH/DELETE /api/lore/{id}              изменить / удалить запись
  POST   /api/scenes                       {mode, character_ids, persona_id?, world_id?, setup?}
  PATCH  /api/messages/{id}/state          {state, choices?} — правка состояния квеста
  GET/DELETE /api/chats/{id}/relations     отношения персонажей с персоной (+ монеты) / сброс
  POST   /api/chats/{id}/nudge             {min_hours?, force?} — персонаж может написать первым
  POST   /api/chats/{id}/gift              {text, to?, note?} — подарок за монеты
  GET    /api/wallet?persona_id=           монеты
  POST   /api/chats/{id}/money             {action: borrow|repay, amount, to?} — занять / вернуть
  POST   /api/chats/{id}/date              {setup?, to?} — свидание: история из чата с персонажем
  POST   /api/chats/{id}/date/finish       итог вечера — в отношения; → {chat_id исходного}
  GET    /api/chats/{id}/recap             «в предыдущих сериях»
  GET    /api/chats/{id}/choices           карта выборов истории
  GET    /api/chats/{id}/gallery           все картинки чата, фоны, портреты, эмоции
  POST   /api/chats/{id}/vn/background     {name} — нарисовать фон места по кнопке
  GET    /api/proposals                    предложения изменить карточки
  POST   /api/proposals/{id}               {accept} — принять или отклонить
  POST   /api/cards/{id}/sprites           нарисовать эмоции персонажа для новеллы
  GET    /api/chats/{id}/vn                фоны мест истории {ключ: картинка}
  POST   /api/image/enhance                {text, chat_id?} → {prompt, negative} — промпт моделью
  POST   /api/messages/{id}/redraw         {prompt?, seed?, …} — перерисовать картинку на месте
  POST   /api/chats/{id}/cancel            остановить генерацию в чате
  PATCH  /api/messages/{id}                {content?, pinned?} — правка на месте, закрепление
  DELETE /api/messages/{id}                удалить с продолжениями
  POST   /api/messages/{id}/regenerate     новый вариант ответа
  POST   /api/messages/{id}/select         переключиться на вариант/ветку
  POST   /api/messages/{id}/continue       продолжить оборванный ответ
  GET    /api/chats/{id}/memory            {"facts", "chronicle", "ctx"} — память чата
  POST   /api/chats/{id}/facts             {text, pinned?} — добавить факт
  PATCH  /api/facts/{id}                   {text?, pinned?}
  DELETE /api/facts/{id}
  PUT    /api/chats/{id}/chronicle         {text} — правка хроники текущей ветки
  POST   /api/chats/{id}/memory/refresh    обновить факты из диалога сейчас
  GET    /api/settings, PUT /api/settings  {default_system_prompt, default_settings}
  GET    /api/ws                           WebSocket событий
Совместимость:
  GET /v1/models, POST /v1/chat/completions — прокси к llama-server

События WebSocket (сервер → клиент), JSON:
  hello {api, status, chats}        сразу после подключения
  status {status}                   изменилось состояние модели
  busy {busy}
  chat.updated {chat}, chat.deleted {id}
  chat.changed {chat_id}            структура ветки изменилась — перечитать чат
  message.added {chat_id, message}
  message.delta {chat_id, id, offset, content, r_offset, reasoning}
  message.done {chat_id, message}
  message.updated {chat_id, message}
  message.stage {chat_id, id, stage}  summarizing — сжатие истории перед ответом, generating
  memory.updated {chat_id}            факты или хроника изменились
"""
import asyncio
import hmac
import json
import os
import re
import threading

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web
from PyQt6.QtCore import QObject, pyqtSignal

from config import DATA_DIR
from generator import Generator
import cards
import quest
import vn
import random
import time
import relations as rel
from imagegen import (QUALITY, TASK_IDS, ImageError, Vram, load_profiles, profile_info,
                      routes_info)
from images import MAX_IMAGES, image_path, save_image
from memory import _transcript as memory_transcript
from memory import (DEFAULTS_PLAIN, DEFAULTS_THINKING, MAX_TOKENS_PLAIN, MAX_TOKENS_THINKING,
                    Llama, Memory)
from store import BadRequest, NotFound, Store

API_VERSION = 2
PUBLIC_PATHS = {"/api/ping"}
MAX_BODY = 32 * 1024 * 1024       # на будущее: картинки в base64
WS_QUEUE = 2000                   # событий в очереди медленного клиента до отключения


def _json_error(status: int, msg: str):
    return web.json_response({"error": msg}, status=status)


def api(handler):
    """Единая обработка ошибок хранилища и тела запроса."""
    async def wrapped(self, request):
        try:
            return await handler(self, request)
        except NotFound as e:
            return _json_error(404, str(e))
        except BadRequest as e:
            return _json_error(400, str(e))
        except (ValueError, TypeError, KeyError) as e:
            return _json_error(400, f"некорректный запрос: {e}")
    return wrapped


async def _body(request) -> dict:
    if not request.can_read_body:
        return {}
    data = await request.json()
    if not isinstance(data, dict):
        raise BadRequest("ожидался JSON-объект")
    return data


DATE_SUMMARY = ("Подведи итог вечера (свидания) одним-двумя предложениями от третьего лица: где "
                "были, что важного произошло, чем закончилось. Без оценок.")
RECAP_PROMPT = ("Кратко перескажи, что было в истории до этого момента — 3–5 предложений, как "
                "«в предыдущих сериях»: главные события, где сейчас герои, на чём остановились.")
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}},
                  "required": ["summary"]}

NUDGE_HOURS = 3   # через сколько часов тишины персонаж может написать первым

GIFT_PROMPT = (
    "Оцени подарок в игровых монетах и назови его коротко. Ориентиры: мелочь 1–10, цветы или "
    "сладости 5–20, книга или безделушка 10–40, одежда 30–150, украшение 50–500, редкая или "
    "волшебная вещь 200–2000.")
GIFT_DEFAULT_PRICE = 15
GIFT_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "maxLength": 60}, "price": {"type": "integer", "minimum": 1, "maximum": 5000}},
    "required": ["name", "price"]}


def _draw_params(b: dict, prompt: str) -> dict:
    params = {"prompt": prompt}
    for k, conv in (("negative", str), ("width", int), ("height", int), ("steps", int),
                    ("cfg", float), ("seed", int)):
        if b.get(k) not in (None, ""):
            try:
                params[k] = conv(b[k])
            except (TypeError, ValueError):
                raise BadRequest(f"{k}: некорректное значение")
    for k in ("width", "height"):
        if k in params:
            params[k] = max(256, min(2048, params[k] // 64 * 64))
            params["exact_size"] = True   # размер задан руками — качество его не масштабирует
    if "steps" in params:
        params["steps"] = max(1, min(100, params["steps"]))
    return params


def _id(request, key="id") -> int:
    try:
        return int(request.match_info[key])
    except ValueError:
        raise NotFound("некорректный id")


class WsClient:
    def __init__(self, ws: web.WebSocketResponse, peer: str):
        self.ws = ws
        self.peer = peer
        self.queue = asyncio.Queue(maxsize=WS_QUEUE)
        self.sender = None

    def put(self, event: dict) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    async def run_sender(self):
        try:
            while True:
                ev = await self.queue.get()
                await self.ws.send_str(json.dumps(ev, ensure_ascii=False))
        except (ConnectionError, RuntimeError, asyncio.CancelledError):
            pass


class BridgeServer(QObject):
    log = pyqtSignal(str)
    listening = pyqtSignal(str)          # текущие адреса, "" — не слушает
    failed = pyqtSignal(str)
    stopped = pyqtSignal()
    request_seen = pyqtSignal(str, str)  # ip, path
    clients_changed = pyqtSignal(int)    # число подключённых WebSocket
    llama_control = pyqtSignal(bool)     # запустить/остановить llama-server (выполняет GUI-поток)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._thread = None
        self._loop = None
        self._stop_event = None
        self._runner = None
        self._sites = {}                 # host -> TCPSite
        self.session = None
        self.store = None
        self.gen = None
        self.clients = set()
        self._nudge_rolled = {}          # chat_id -> head_id: шанс «написать первым» уже брошен
        self._status = {"llama": "down", "model": os.path.basename(cfg.model),
                        "vision": False, "n_ctx": cfg.ctx, "busy": False}

    # ============================================================ управление
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,),
                                        name="bridge-http", daemon=True)
        self._thread.start()
        ready.wait(5)

    def stop(self, wait: bool = True):
        loop, ev = self._loop, self._stop_event
        if loop and ev:
            loop.call_soon_threadsafe(ev.set)
        if wait and self._thread:
            self._thread.join(timeout=10)

    def bind(self, host: str):
        """Начать слушать ещё один адрес (из GUI-потока)."""
        self._call(self._bind(host))

    def unbind(self, host: str):
        self._call(self._unbind(host))

    def _call(self, coro):
        if self._loop:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            coro.close()

    # ============================================================== поток
    def _run(self, ready: threading.Event):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._main(ready))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"HTTP-сервер: {e}")
        finally:
            ready.set()
            loop.close()
            self._loop = None
            self._stop_event = None
            self.listening.emit("")
            self.stopped.emit()

    async def _main(self, ready: threading.Event):
        self._stop_event = asyncio.Event()
        self.store = Store(DATA_DIR / "chats.db")
        n = self.store.recover()
        if n:
            self.log.emit(f"Отмечено прерванных генераций: {n}")
        self.session = ClientSession(timeout=ClientTimeout(total=None, sock_connect=5))
        self.memory = Memory(self.store, Llama(self.session, self._llama), self.emit, self.log.emit)
        self.memory.bg = Llama(self.session, f"http://127.0.0.1:{self.cfg.bg_port}")
        self.memory.bg_ok = lambda: self._status.get("bg") == "ready"
        self.vram = Vram(self.cfg, self.session, self.log.emit, self.llama_control.emit)
        self.gen = Generator(self.store, self._llama, self.session, self.emit, self.log.emit,
                             self.memory, lambda: int(self._status.get("n_ctx") or self.cfg.ctx),
                             vram=self.vram)
        self.memory.vision = lambda: bool(self._status.get("vision"))
        self.gen.images_ok = lambda: bool(self._status.get("images"))

        @web.middleware
        async def auth(request, handler):
            self.request_seen.emit(request.remote or "?", request.path)
            if request.path not in PUBLIC_PATHS:
                header = request.headers.get("Authorization", "")
                token = header[7:].strip() if header.startswith("Bearer ") else ""
                if not token or not hmac.compare_digest(token.encode(), self.cfg.token.encode()):
                    return _json_error(401, "unauthorized")
            return await handler(request)

        app = web.Application(client_max_size=MAX_BODY, middlewares=[auth])
        r = app.router
        r.add_get("/api/ping", self.h_ping)
        r.add_get("/api/status", self.h_status)
        r.add_get("/api/ws", self.h_ws)
        r.add_get("/api/settings", self.h_settings_get)
        r.add_put("/api/settings", self.h_settings_put)
        r.add_get("/api/chats", self.h_chats)
        r.add_post("/api/chats", self.h_chat_create)
        r.add_get("/api/chats/{id}", self.h_chat_get)
        r.add_patch("/api/chats/{id}", self.h_chat_patch)
        r.add_delete("/api/chats/{id}", self.h_chat_delete)
        r.add_post("/api/chats/{id}/messages", self.h_send)
        r.add_post("/api/chats/{id}/cancel", self.h_cancel)
        r.add_get("/api/images/{name}", self.h_image)
        r.add_get("/api/image/profiles", self.h_image_profiles)
        r.add_put("/api/image/routes", self.h_image_routes_put)
        r.add_post("/api/chats/{id}/images", self.h_draw)
        r.add_post("/api/image/enhance", self.h_enhance)
        r.add_get("/api/cards", self.h_cards)
        r.add_post("/api/cards", self.h_card_create)
        r.add_post("/api/cards/generate", self.h_card_generate)
        r.add_get("/api/cards/{id}", self.h_card_get)
        r.add_patch("/api/cards/{id}", self.h_card_patch)
        r.add_delete("/api/cards/{id}", self.h_card_delete)
        r.add_post("/api/cards/{id}/rewrite", self.h_card_rewrite)
        r.add_post("/api/cards/{id}/portrait", self.h_card_portrait)
        r.add_post("/api/cards/{id}/chat", self.h_card_chat)
        r.add_post("/api/cards/{id}/sprites", self.h_card_sprites)
        r.add_get("/api/chats/{id}/vn", self.h_vn)
        r.add_get("/api/cards/{id}/lore", self.h_lore)
        r.add_post("/api/cards/{id}/lore", self.h_lore_add)
        r.add_post("/api/cards/{id}/lore/generate", self.h_lore_generate)
        r.add_patch("/api/lore/{id}", self.h_lore_patch)
        r.add_delete("/api/lore/{id}", self.h_lore_delete)
        r.add_post("/api/scenes", self.h_scene)
        r.add_get("/api/chats/{id}/relations", self.h_relations)
        r.add_delete("/api/chats/{id}/relations", self.h_relations_reset)
        r.add_post("/api/chats/{id}/nudge", self.h_nudge)
        r.add_post("/api/chats/{id}/gift", self.h_gift)
        r.add_get("/api/wallet", self.h_wallet)
        r.add_post("/api/chats/{id}/money", self.h_money)
        r.add_post("/api/chats/{id}/date", self.h_date)
        r.add_post("/api/chats/{id}/date/finish", self.h_date_finish)
        r.add_get("/api/chats/{id}/recap", self.h_recap)
        r.add_get("/api/chats/{id}/choices", self.h_choices)
        r.add_get("/api/chats/{id}/gallery", self.h_gallery)
        r.add_post("/api/chats/{id}/vn/background", self.h_vn_bg)
        r.add_get("/api/proposals", self.h_proposals)
        r.add_post("/api/proposals/{id}", self.h_proposal)
        r.add_patch("/api/messages/{id}/state", self.h_state)
        r.add_post("/api/messages/{id}/redraw", self.h_redraw)
        r.add_patch("/api/messages/{id}", self.h_msg_patch)
        r.add_delete("/api/messages/{id}", self.h_msg_delete)
        r.add_post("/api/messages/{id}/regenerate", self.h_regenerate)
        r.add_post("/api/messages/{id}/select", self.h_select)
        r.add_post("/api/messages/{id}/continue", self.h_continue)
        r.add_get("/api/chats/{id}/memory", self.h_memory)
        r.add_post("/api/chats/{id}/facts", self.h_fact_add)
        r.add_patch("/api/facts/{id}", self.h_fact_patch)
        r.add_delete("/api/facts/{id}", self.h_fact_delete)
        r.add_put("/api/chats/{id}/chronicle", self.h_chronicle)
        r.add_post("/api/chats/{id}/memory/refresh", self.h_memory_refresh)
        r.add_get("/v1/models", self.h_models)
        r.add_post("/v1/chat/completions", self.h_proxy_chat)

        self._runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await self._runner.setup()
        monitor = asyncio.create_task(self._monitor())
        try:
            await self._bind("127.0.0.1")
            ready.set()
            await self._stop_event.wait()
        finally:
            monitor.cancel()
            await self.gen.shutdown()
            await self.vram.stop_sd()
            for c in list(self.clients):
                await c.ws.close()
            await self._runner.cleanup()
            self._sites.clear()
            await self.session.close()
            self.store.close()

    async def _bind(self, host: str):
        if host in self._sites or not self._runner:
            return
        site = web.TCPSite(self._runner, host, self.cfg.bridge_port)
        try:
            await site.start()
        except OSError as e:
            self.failed.emit(f"Не удалось открыть {host}:{self.cfg.bridge_port}: {e.strerror or e}")
            return
        self._sites[host] = site
        self._announce()

    async def _unbind(self, host: str):
        site = self._sites.pop(host, None)
        if site:
            await site.stop()
            self._announce()

    def _announce(self):
        self.listening.emit(", ".join(f"{h}:{self.cfg.bridge_port}" for h in self._sites))

    # ============================================================== события
    def emit(self, event: dict):
        if event.get("type") == "busy":
            self._status["busy"] = event["busy"]
        for c in list(self.clients):
            if not c.put(event):
                self.log.emit(f"{c.peer}: клиент не успевает читать события — отключение")
                asyncio.ensure_future(c.ws.close())

    async def _monitor(self):
        """Следит за llama-server и рассылает изменения состояния."""
        props_loaded = False
        while True:
            st = dict(self._status)
            try:
                async with self.session.get(f"{self._llama}/health",
                                            timeout=ClientTimeout(total=3)) as r:
                    st["llama"] = "ready" if r.status == 200 else \
                        "loading" if r.status == 503 else "error"
            except (ClientError, asyncio.TimeoutError, ConnectionError):
                st["llama"] = "down"
                props_loaded = False
            if st["llama"] == "ready" and not props_loaded:
                try:
                    async with self.session.get(f"{self._llama}/props",
                                                timeout=ClientTimeout(total=3)) as r:
                        p = await r.json(content_type=None)
                    dgs = p.get("default_generation_settings") or {}
                    st["n_ctx"] = int(dgs.get("n_ctx") or p.get("n_ctx") or self.cfg.ctx)
                    mod = p.get("modalities") or {}
                    st["vision"] = bool(mod.get("vision", False))
                    mp = p.get("model_path")
                    if mp:
                        st["model"] = os.path.basename(mp)
                    props_loaded = True
                except (ClientError, asyncio.TimeoutError, ConnectionError, ValueError):
                    pass
            if st["llama"] == "down" and self.vram.mode == "image":
                st["llama"] = "swapped"   # видеопамять занята рисованием; текст вернёт модель
            st["images"] = any(profile_info(p)["ready"] for p in load_profiles()) and \
                os.path.exists(os.path.expanduser(self.cfg.sd_server_bin))
            try:   # фоновая модель (маленькая, на процессоре)
                async with self.session.get(f"http://127.0.0.1:{self.cfg.bg_port}/health",
                                            timeout=ClientTimeout(total=2)) as r:
                    st["bg"] = "ready" if r.status == 200 else "loading"
            except (ClientError, asyncio.TimeoutError, ConnectionError):
                st["bg"] = "down"
            st["busy"] = self.gen.busy
            if st != self._status:
                self._status = st
                self.emit({"type": "status", "status": st})
            await asyncio.sleep(2)

    # ============================================================ обработчики
    @property
    def _llama(self) -> str:
        return f"http://127.0.0.1:{self.cfg.llama_port}"

    async def h_ping(self, request):
        return web.json_response({"app": "llm-bridge", "api": API_VERSION,
                                  "name": self.cfg.p2p_device_name})

    async def h_status(self, request):
        return web.json_response(self._status)

    async def h_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=1 << 20)
        await ws.prepare(request)
        client = WsClient(ws, request.remote or "?")
        client.sender = asyncio.create_task(client.run_sender())
        client.put({"type": "hello", "api": API_VERSION, "status": self._status,
                    "chats": self.store.list_chats()})
        self.clients.add(client)
        self.clients_changed.emit(len(self.clients))
        self.log.emit(f"{client.peer}: подключён")
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT and msg.data == "ping":
                    client.put({"type": "pong"})
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(client)
            client.sender.cancel()
            self.clients_changed.emit(len(self.clients))
            # 1000/1001 — приложение закрыло само; 1006 или None — связь пропала молча
            # (телефон уснул или потерял Wi-Fi: не ответил на проверку за 15 с)
            code, exc = ws.close_code, ws.exception()
            why = "закрыто приложением" if code in (1000, 1001) else \
                "телефон перестал отвечать (сон или потеря Wi-Fi)"
            self.log.emit(f"{client.peer}: отключён — {why}, код {code}"
                          + (f", {exc.__class__.__name__}" if exc else ""))
        return ws

    # ---------------------------------------------------------- настройки
    @api
    async def h_settings_get(self, request):
        return web.json_response({
            "default_system_prompt": self.store.get_setting("default_system_prompt", ""),
            "default_settings": self.store.get_setting("default_settings", {}),
            # что подставляется, если параметр не задан
            "recommended": {
                "plain": dict(DEFAULTS_PLAIN, max_tokens=MAX_TOKENS_PLAIN),
                "thinking": dict(DEFAULTS_THINKING, max_tokens=MAX_TOKENS_THINKING),
            },
        })

    @api
    async def h_settings_put(self, request):
        from store import clean_settings
        b = await _body(request)
        if "default_system_prompt" in b:
            self.store.set_setting("default_system_prompt", str(b["default_system_prompt"]).strip())
        if "default_settings" in b:
            self.store.set_setting("default_settings", clean_settings(b["default_settings"]))
        return await self.h_settings_get(request)

    # --------------------------------------------------------------- чаты
    def _with_live(self, msgs: list) -> list:
        """Подставляет в генерируемые сообщения текст из памяти (он свежее базы)."""
        for m in msgs:
            job = self.gen.live(m["id"])
            if job:
                m["content"], m["reasoning"], m["status"] = job.content, job.reasoning, "generating"
        return msgs

    @api
    async def h_chats(self, request):
        return web.json_response({"chats": self.store.list_chats()})

    @api
    async def h_chat_create(self, request):
        b = await _body(request)
        chat = self.store.create_chat(str(b.get("title", "")), b.get("system_prompt"),
                                      b.get("settings"))
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat})

    @api
    async def h_chat_get(self, request):
        cid = _id(request)
        return web.json_response({"chat": self.store.chat_dict(cid),
                                  "messages": self._with_live(self.store.messages(cid))})

    @api
    async def h_chat_patch(self, request):
        b = await _body(request)
        cid = _id(request)
        chat = self.store.update_chat(cid, b.get("title"), b.get("system_prompt"),
                                      b.get("settings"))
        if isinstance(b.get("set"), dict):   # точечно: {"set": {"chat_style": "roleplay"}}
            for k, v in b["set"].items():
                self.store.set_chat_setting(cid, k, v)
            chat = self.store.chat_dict(cid)
        if b.get("make_default"):
            if "system_prompt" in b:
                self.store.set_setting("default_system_prompt", chat["system_prompt"])
            if "settings" in b:
                self.store.set_setting("default_settings", chat["settings"])
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat})

    @api
    async def h_chat_delete(self, request):
        cid = _id(request)
        self.store.chat_dict(cid)
        running = [j.msg_id for j in list(self.gen.jobs.values()) if j.chat_id == cid]
        if self.gen.cancel_msgs(running):
            await self.gen.wait_msgs(running)  # задача сохранит итог до удаления чата
        if self.gen.cancel_backgrounds(cid):
            self.log.emit("Чат удалён — рисование его фонов остановлено")
        self.store.delete_chat(cid)
        self.emit({"type": "chat.deleted", "id": cid})
        return web.json_response({"ok": True})

    @api
    async def h_send(self, request):
        cid = _id(request)
        b = await _body(request)
        content = str(b.get("content", ""))
        replace_id = b.get("replace_id")
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        raw_images = b.get("images") or []
        if not isinstance(raw_images, list) or len(raw_images) > MAX_IMAGES:
            raise BadRequest(f"картинок не больше {MAX_IMAGES}")
        if raw_images and not self._status.get("vision"):
            raise BadRequest("модель на ПК запущена без поддержки картинок (mmproj)")
        images = [save_image(str(x)) for x in raw_images] or None
        uid = self.store.add_user_message(cid, content,
                                          int(replace_id) if replace_id is not None else None,
                                          images=images)
        extra = {}
        if b.get("reply_as"):            # кто из персонажей сцены отвечает
            extra["reply_as"] = int(b["reply_as"])
        if b.get("directive"):           # служебная команда истории («продолжи», «поворот»)
            extra["kind"] = "directive"
        if b.get("choice"):              # выбран вариант развилки
            extra["kind"] = "choice"
        if extra:
            self.store.merge_meta(uid, extra)
        aid = self.store.add_assistant(cid, uid)
        self.gen.start(cid, aid)
        self.emit({"type": "busy", "busy": True})
        user, asst = self.store.msg_dict(uid), self.store.msg_dict(aid)
        chat = self.store.chat_dict(cid)
        for m in (user, asst):
            self.emit({"type": "message.added", "chat_id": cid, "message": m})
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat, "messages": [user, asst]})

    async def h_image(self, request):
        p = image_path(request.match_info["name"])
        if not p:
            return _json_error(404, "нет такой картинки")
        return web.FileResponse(p, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @api
    async def h_image_profiles(self, request):
        return web.json_response(self._image_info())

    def _image_info(self) -> dict:
        return {
            "profiles": [profile_info(p) for p in load_profiles()],
            "sd_server": os.path.exists(os.path.expanduser(self.cfg.sd_server_bin)),
            # какая модель рисует какую задачу ("" — «Авто») и общее качество
            "routes": routes_info(self.gen.routes()),
            "quality": self.store.get_setting("image_quality", "normal"),
        }

    @api
    async def h_image_routes_put(self, request):
        """Закрепить модели за задачами: {"routes": {"portrait": "moss-image", "photo": ""},
        "quality": "fast|normal|high"}. Пустая строка — «Авто»."""
        b = await _body(request)
        if isinstance(b.get("routes"), dict):
            ids = {p["id"] for p in load_profiles()}
            cur = self.gen.routes()
            for task, pid in b["routes"].items():
                if task not in TASK_IDS:
                    raise BadRequest(f"нет такой задачи: {task}")
                if pid and pid not in ids:
                    raise BadRequest(f"нет такого профиля: {pid}")
                if pid:
                    cur[task] = pid
                else:
                    cur.pop(task, None)
            self.store.set_setting("image_routes", cur)
        if "quality" in b:
            if b["quality"] not in QUALITY:
                raise BadRequest("quality: fast | normal | high")
            self.store.set_setting("image_quality", b["quality"])
        info = self._image_info()
        self.emit({"type": "image.routes", "routes": info["routes"], "quality": info["quality"]})
        return web.json_response(info)

    @api
    async def h_draw(self, request):
        cid = _id(request)
        b = await _body(request)
        prompt = str(b.get("prompt", "")).strip()
        if not prompt:
            raise BadRequest("пустой запрос")
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        chat = self.store.chat_dict(cid)
        profiles = {p["id"]: p for p in load_profiles()}
        pid = b.get("profile") or ""
        if pid and pid not in profiles:
            raise BadRequest("нет такого профиля изображений")
        # профиль не указан — «Авто»: модель под задачу из таблицы маршрутов
        profile = [profiles[pid]] if pid else self.gen.profiles_for("photo")
        if not profile:
            raise BadRequest("нет готового профиля изображений — скачайте модели (scripts/setup-images.sh)")
        params = _draw_params(b, prompt)
        if pid:
            params["chosen"] = True
        if b.get("likeness") is False:
            params["likeness"] = False   # не подставлять портреты персонажей образцами
        if b.get("enhance"):
            params["enhance"] = True   # текстовая модель доработает запрос перед рисованием
        uid = self.store.add_user_message(cid, prompt)
        self.store.merge_meta(uid, {"kind": "image_request"})
        aid = self.store.add_assistant(cid, uid)
        self.store.merge_meta(aid, {"kind": "image", "source": "user", "prompt": prompt,
                                    "profile": profile[0]["id"]})
        self.gen.start_image(cid, aid, profile, params)
        self.emit({"type": "busy", "busy": True})
        user, asst = self.store.msg_dict(uid), self.store.msg_dict(aid)
        chat = self.store.chat_dict(cid)
        for m in (user, asst):
            self.emit({"type": "message.added", "chat_id": cid, "message": m})
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat, "messages": [user, asst]})

    # ------------------------------------------------------------ карточки
    @staticmethod
    def _kind(v) -> str:
        if v not in cards.KINDS:
            raise BadRequest("kind: character | persona")
        return v

    @api
    async def h_cards(self, request):
        kind = request.query.get("kind")
        return web.json_response({"cards": self.store.cards(self._kind(kind) if kind else None),
                                  "fields": cards.fields_info(),
                                  "drawing": sorted(self.gen.portraits)})

    @api
    async def h_card_get(self, request):
        return web.json_response({"card": self.store.card(_id(request))})

    @api
    async def h_card_create(self, request):
        b = await _body(request)
        kind = self._kind(b.get("kind"))
        card = self.store.save_card(kind, cards.clean_data(kind, b.get("data") or {}))
        self.emit({"type": "card.updated", "card": card})
        return web.json_response({"card": card})

    @api
    async def h_card_generate(self, request):
        """Описание своими словами → модель заполняет все поля → новая карточка."""
        b = await _body(request)
        kind = self._kind(b.get("kind"))
        text = str(b.get("text", "")).strip()
        if not text:
            raise BadRequest("пустое описание")
        try:
            data, lore = await self.gen.fill_card(kind, text)
        except (ImageError, ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError,
                ValueError, KeyError) as e:
            raise BadRequest(f"модель не смогла заполнить карточку: {e}")
        card = self.store.save_card(kind, data)
        for e in lore:
            self.store.add_lore(card["id"], e["title"], e["keys"], e["content"])
        self.log.emit(f"Карточка создана моделью: {card['name']}")
        self.emit({"type": "card.updated", "card": card})
        return web.json_response({"card": card})

    @api
    async def h_card_patch(self, request):
        cid = _id(request)
        old = self.store.card(cid)
        b = await _body(request)
        data = dict(old["data"], **(b.get("data") or {}))
        card = self.store.save_card(old["kind"], cards.clean_data(old["kind"], data), cid)
        self.emit({"type": "card.updated", "card": card})
        return web.json_response({"card": card})

    @api
    async def h_card_delete(self, request):
        cid = _id(request)
        if self.gen.cancel_card(cid):
            self.log.emit("Карточка удалена — рисование для неё остановлено")
        self.store.delete_card(cid)
        self.emit({"type": "card.deleted", "id": cid})
        self.emit({"type": "busy", "busy": self.gen.busy})
        return web.json_response({"ok": True})

    @api
    async def h_card_rewrite(self, request):
        """Переписать одно поле моделью (без сохранения — телефон покажет и даст поправить)."""
        card = self.store.card(_id(request))
        b = await _body(request)
        key = str(b.get("field", ""))
        if key not in [f[0] for f in cards.FIELDS[card["kind"]]]:
            raise BadRequest("неизвестное поле")
        if isinstance(b.get("data"), dict):   # несохранённые правки из редактора
            card["data"] = cards.clean_data(card["kind"], dict(card["data"], **b["data"]))
        try:
            value = await self.gen.rewrite_field(card, key, str(b.get("wish") or ""))
        except (ImageError, ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError,
                ValueError, KeyError) as e:
            raise BadRequest(f"модель не смогла переписать поле: {e}")
        return web.json_response({"field": key, "value": value})

    @api
    async def h_card_portrait(self, request):
        card = self.store.card(_id(request))
        if card["id"] in self.gen.portraits:
            raise BadRequest("портрет уже рисуется")
        b = await _body(request)
        profiles = {p["id"]: p for p in load_profiles()}
        profile = [profiles[b["profile"]]] if b.get("profile") in profiles else \
            self.gen.profiles_for("portrait")
        if not profile or not profile_info(profile[0])["ready"]:
            raise BadRequest("нет готового профиля изображений")
        self.gen.start_portrait(card, profile)
        self.emit({"type": "busy", "busy": True})
        return web.json_response({"ok": True})

    @api
    async def h_card_sprites(self, request):
        """Набор эмоций персонажа для новеллы (шесть картинок)."""
        card = self.store.card(_id(request))
        if card["kind"] != "character":
            raise BadRequest("эмоции рисуются только персонажам")
        if card["id"] in self.gen.portraits:
            raise BadRequest("уже рисуется")
        # по образцу портрета (то же лицо), если есть портрет и модель, умеющая так рисовать
        profile = (self.gen.profiles_for("sprite", "edit") if card.get("portrait") else []) or \
            self.gen.profiles_for("portrait")
        if not profile:
            raise BadRequest("нет готового профиля изображений")
        self.gen.start_sprites(card, profile)
        self.emit({"type": "busy", "busy": True})
        return web.json_response({"ok": True})

    @api
    async def h_vn(self, request):
        """Для экрана новеллы: фоны мест этой истории и какие ещё рисуются."""
        cid = _id(request)
        self.store.chat_dict(cid)
        return web.json_response({
            "backgrounds": self.store.vn_backgrounds(cid),
            "pending": [k for c, k in self.gen.vn_pending if c == cid]})

    @api
    async def h_card_chat(self, request):
        """Новый чат с персонажем: роль из карточки, первое сообщение — приветствие персонажа."""
        card = self.store.card(_id(request))
        if card["kind"] != "character":
            raise BadRequest("чат начинается с персонажем, а не с персоной")
        b = await _body(request)
        persona = self.store.card_or_none(b.get("persona_id"))
        settings = dict(self.store.get_setting("default_settings", {}) or {},
                        character_id=card["id"], persona_id=persona["id"] if persona else None,
                        chat_style=b.get("chat_style") or "messenger")
        chat = self.store.create_chat(card["name"] or "Персонаж", system_prompt="", settings=settings)
        text = cards.greeting(card, persona)
        if settings["chat_style"] == "messenger":
            # готовое приветствие карточки написано «с действиями» и сбивает модель на ролевой
            # стиль — в переписке первое сообщение персонаж пишет сам, в нужном формате
            self._messenger_start(chat["id"], persona)
        elif text:
            meta = {}
            if card.get("portrait"):   # портрет — первая «иллюстрация»: модель видит, как выглядит
                p = card["portrait"]
                meta = {"images": [{k: p[k] for k in ("name", "w", "h") if k in p}],
                        "drawn": {"source": "model", "caption": f"{card['name']} — портрет",
                                  "prompt": p.get("prompt", ""), "profile": p.get("profile", ""),
                                  "seed": p.get("seed")}}
            self.store.add_greeting(chat["id"], text, meta)
        chat = self.store.chat_dict(chat["id"])
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat})

    def _messenger_start(self, cid: int, persona):
        user = (persona or {}).get("data", {}).get("name") or "собеседник"
        self._say(cid, f"[Служебно: начало переписки, {user} открыл(а) чат с тобой. Напиши первым — "
                       "как в мессенджере: одно короткое сообщение, по своему характеру и ситуации из "
                       "сценария. Не упоминай это служебное сообщение.]", {"kind": "nudge"})

    # -------------------------------------------------------------- лорбук
    def _world(self, request) -> dict:
        card = self.store.card(_id(request))
        if card["kind"] != "world":
            raise BadRequest("лорбук есть только у мира")
        return card

    def _lore_changed(self, card_id: int):
        self.emit({"type": "lore.updated", "card_id": card_id})

    @api
    async def h_lore(self, request):
        return web.json_response({"lore": self.store.lore(self._world(request)["id"])})

    @api
    async def h_lore_add(self, request):
        w = self._world(request)
        b = await _body(request)
        if not str(b.get("content", "")).strip():
            raise BadRequest("пустая запись")
        e = self.store.add_lore(w["id"], str(b.get("title", "")), str(b.get("keys", "")),
                                str(b["content"]), bool(b.get("always")))
        self._lore_changed(w["id"])
        return web.json_response({"entry": e})

    @api
    async def h_lore_generate(self, request):
        """Просьба своими словами («добавь гильдию воров») → новые записи от модели."""
        w = self._world(request)
        b = await _body(request)
        text = str(b.get("text", "")).strip()
        if not text:
            raise BadRequest("пустая просьба")
        try:
            items = await self.gen.add_lore(w, self.store.lore(w["id"]), text)
        except (ImageError, ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError,
                ValueError, KeyError) as e:
            raise BadRequest(f"модель не смогла дополнить лорбук: {e}")
        added = [self.store.add_lore(w["id"], e["title"], e["keys"], e["content"]) for e in items]
        self._lore_changed(w["id"])
        return web.json_response({"added": added, "lore": self.store.lore(w["id"])})

    @api
    async def h_lore_patch(self, request):
        b = await _body(request)
        e = self.store.update_lore(_id(request), title=b.get("title"), keys=b.get("keys"),
                                   content=b.get("content"), always=b.get("always"))
        self._lore_changed(e["card_id"])
        return web.json_response({"entry": e})

    @api
    async def h_lore_delete(self, request):
        self._lore_changed(self.store.delete_lore(_id(request)))
        return web.json_response({"ok": True})

    # --------------------------------------------------------------- сцены
    @api
    async def h_scene(self, request):
        """Новый чат-сцена: режим (chat/quest/story), персонажи, персона, мир, завязка.
        Завязка уходит первым сообщением, и модель сразу пишет начало."""
        b = await _body(request)
        mode = b.get("mode") or "chat"
        if mode not in cards.MODES:
            raise BadRequest("mode: chat | quest | story")
        ids = [int(x) for x in (b.get("character_ids") or [])][:8]
        chars = [self.store.card(i) for i in ids]
        if any(c["kind"] != "character" for c in chars):
            raise BadRequest("character_ids — только персонажи")
        persona = self.store.card_or_none(b.get("persona_id"))
        world = self.store.card_or_none(b.get("world_id"))
        setup = str(b.get("setup") or "").strip()
        if mode == "chat" and not chars:
            raise BadRequest("для чата нужен хотя бы один персонаж")
        names = ", ".join(c["name"] for c in chars)
        title = str(b.get("title") or "").strip()
        if not title:
            if mode == "chat":
                title = names
            else:
                what = world["name"] if world else names
                title = {"quest": "Квест", "gm": "Я ведущий", "story": "История"}[mode] + \
                    (f": {what}" if what else "")
        settings = dict(self.store.get_setting("default_settings", {}) or {},
                        character_ids=ids, persona_id=persona["id"] if persona else None,
                        world_id=world["id"] if world else None, mode=mode,
                        chat_style=b.get("chat_style") or ("messenger" if mode == "chat" else None))
        chat = self.store.create_chat(title[:60], system_prompt="", settings=settings)
        cid = chat["id"]
        if mode == "chat" and not setup and settings.get("chat_style") == "messenger":
            self._messenger_start(cid, persona)
        elif mode == "chat" and len(chars) == 1 and not setup:
            text = cards.greeting(chars[0], persona)
            if text:
                self.store.add_greeting(cid, text)
        if mode != "chat" or setup:
            start = setup or "Начни."
            if mode == "quest":
                start = "[Начало игры] " + start + ("" if setup else "")
            elif mode == "story":
                start = "[Завязка истории] " + start
            elif mode == "gm":
                start = "[Ведущий начинает игру] " + start
            uid = self.store.add_user_message(cid, start)
            self.store.merge_meta(uid, {"kind": "directive"})
            aid = self.store.add_assistant(cid, uid)
            self.gen.start(cid, aid)
            self.emit({"type": "busy", "busy": True})
        chat = self.store.chat_dict(cid)
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat})

    # -------------------------------------------- отношения, инициатива, подарки
    def _chat_scene(self, cid: int) -> dict:
        return self.memory.scene(self.store.chat_row(cid))

    @api
    async def h_relations(self, request):
        """Отношения персонажей этого чата с персоной + кошелёк."""
        sc = self._chat_scene(_id(request))
        pid = sc["persona"]["id"] if sc["persona"] else 0
        return web.json_response({
            "relations": [{"character_id": c["id"], "name": c["name"],
                           "relation": rel.public(dict(rel.new(), **self.store.relation(c["id"], pid)))}
                          for c in sc["chars"]] if sc["mode"] == "chat" else [],
            "persona_id": pid, "coins": self.store.wallet(pid)})

    @api
    async def h_relations_reset(self, request):
        cid = _id(request)
        sc = self._chat_scene(cid)
        pid = sc["persona"]["id"] if sc["persona"] else 0
        for c in sc["chars"]:
            self.store.reset_relation(c["id"], pid)
        return await self.h_relations(request)

    @api
    async def h_nudge(self, request):
        """Телефон открыл чат: персонаж может написать первым, если давно не общались.
        Не каждый раз — шанс зависит от симпатии; один бросок на одну паузу."""
        cid = _id(request)
        b = await _body(request)
        chat = self.store.chat_row(cid)
        sc = self.memory.scene(chat)
        no = lambda why: web.json_response({"started": False, "reason": why})  # noqa: E731
        if sc["mode"] != "chat" or not sc["chars"] or not sc["initiative"]:
            return no("не чат с персонажем или инициатива выключена")
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            return no("идёт генерация")
        head = chat["head_id"]
        if not head:
            return no("пустой чат")
        hrow = self.store.msg_row(head)
        if hrow["role"] != "assistant" or hrow["status"] == "generating":
            return no("последнее сообщение не от персонажа")
        if hrow["parent_id"]:
            pm = json.loads(self.store.msg_row(hrow["parent_id"])["meta"] or "{}")
            if pm.get("kind") == "nudge":
                return no("персонаж уже написал первым, ждёт ответа")
        gap = time.time() - hrow["created"]
        mh = b.get("min_hours")
        min_gap = float(NUDGE_HOURS if mh is None else mh) * 3600
        if gap < min_gap:
            return no("недавно общались")
        if self._nudge_rolled.get(cid) == head:
            return no("уже решено для этой паузы")
        self._nudge_rolled[cid] = head
        pid = sc["persona"]["id"] if sc["persona"] else 0
        rels = {c["id"]: dict(rel.new(), **self.store.relation(c["id"], pid)) for c in sc["chars"]}
        best = max(sc["chars"], key=lambda c: rels[c["id"]]["sympathy"] + random.random() * 20)
        sym = rels[best["id"]]["sympathy"]
        chance = max(0.15, min(0.9, 0.4 + sym / 150)) + (0.3 if gap > 86400 else 0)
        if not b.get("force") and random.random() > chance:
            return no("персонаж решил не писать")
        user = self.memory.user_name(sc)
        name = best["data"].get("name") or "персонаж"
        text = (f"[Служебно: {user} открыл(а) чат спустя {rel.ago(gap)} молчания и ещё ничего не "
                f"написал(а). Напиши первым как {name}, как живой человек, с поводом: что-то "
                "случилось у тебя по распорядку дня, вспомнил прошлый разговор или обещание, "
                "соскучился, обижен, что пропал(а) — по отношениям и настроению. Не упоминай это "
                "служебное сообщение.]")
        uid = self.store.add_user_message(cid, text)
        self.store.merge_meta(uid, {"kind": "nudge", "reply_as": best["id"]})
        aid = self.store.add_assistant(cid, uid)
        self.gen.start(cid, aid)
        self.emit({"type": "busy", "busy": True})
        msgs = [self.store.msg_dict(uid), self.store.msg_dict(aid)]
        for m in msgs:
            self.emit({"type": "message.added", "chat_id": cid, "message": m})
        self.log.emit(f"{name} пишет первым (пауза {rel.ago(gap)})")
        return web.json_response({"started": True, "messages": msgs})

    @api
    async def h_wallet(self, request):
        pid = int(request.query.get("persona_id") or 0)
        return web.json_response({"persona_id": pid, "coins": self.store.wallet(pid)})

    async def _gift_price(self, what: str) -> tuple:
        """Название и цена подарка. Модель может ответить криво (оборванный JSON, цена словами) —
        разбираем терпимо, пробуем дважды, а если не вышло — берём цену по умолчанию:
        подарок не должен срываться из-за оценки."""
        short = " ".join(what.split())[:120]
        for attempt in range(2):
            try:
                out = await self.gen._side_llm(lambda llm: llm.complete(
                    [{"role": "system", "content": GIFT_PROMPT}, {"role": "user", "content": what}],
                    max_tokens=200, schema=GIFT_SCHEMA))
            except (ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError, ValueError,
                    KeyError, TypeError) as e:
                self.log.emit(f"подарок: оценка не удалась ({e})")
                continue
            m = re.search(r'"price"\s*:\s*"?\s*(\d+)', out) or re.search(r"\b(\d{1,4})\b", out)
            n = re.search(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)', out)
            if m:
                name = " ".join((n.group(1).replace('\\"', '"') if n else "").split())[:120]
                return name or short, max(1, min(5000, int(m.group(1))))
            self.log.emit(f"подарок: непонятный ответ оценки: {out[:120]!r}")
        return short, GIFT_DEFAULT_PRICE

    @api
    async def h_gift(self, request):
        """Подарок персонажу за монеты: цену оценивает модель, реакция — по вкусам персонажа."""
        cid = _id(request)
        b = await _body(request)
        what = str(b.get("text") or "").strip()
        if not what:
            raise BadRequest("что дарим?")
        sc = self._chat_scene(cid)
        if not sc["chars"]:
            raise BadRequest("в этом чате некому дарить")
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        to = next((c for c in sc["chars"] if c["id"] == b.get("to")), sc["chars"][0])
        pid = sc["persona"]["id"] if sc["persona"] else 0
        name, price = await self._gift_price(what)
        coins = self.store.wallet(pid)
        if price > coins:
            raise BadRequest(f"Не хватает монет: «{name}» стоит {price}, у вас {coins}")
        left = self.store.add_coins(pid, -price)
        note = str(b.get("note") or "").strip()
        content = f"*Дарит: {name}*" + (f" ({to['name']})" if len(sc["chars"]) > 1 else "") + \
            (f"\n{note}" if note else "")
        uid = self.store.add_user_message(cid, content)
        self.store.merge_meta(uid, {"kind": "gift", "gift": name, "price": price,
                                    "reply_as": to["id"]})
        aid = self.store.add_assistant(cid, uid)
        self.gen.start(cid, aid)
        self.emit({"type": "busy", "busy": True})
        self.emit({"type": "wallet", "persona_id": pid, "coins": left})
        user, asst = self.store.msg_dict(uid), self.store.msg_dict(aid)
        for m in (user, asst):
            self.emit({"type": "message.added", "chat_id": cid, "message": m})
        return web.json_response({"messages": [user, asst], "price": price, "coins": left})

    def _say(self, cid: int, content: str, meta: dict) -> list:
        """Сообщение пользователя со служебной пометкой + ответ модели."""
        uid = self.store.add_user_message(cid, content)
        self.store.merge_meta(uid, meta)
        aid = self.store.add_assistant(cid, uid)
        self.gen.start(cid, aid)
        self.emit({"type": "busy", "busy": True})
        msgs = [self.store.msg_dict(uid), self.store.msg_dict(aid)]
        for m in msgs:
            self.emit({"type": "message.added", "chat_id": cid, "message": m})
        return msgs

    @api
    async def h_money(self, request):
        """Занять у персонажа (решает он сам — по отношениям) или вернуть долг."""
        cid = _id(request)
        b = await _body(request)
        sc = self._chat_scene(cid)
        if not sc["chars"]:
            raise BadRequest("в этом чате не у кого занимать")
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        to = next((c for c in sc["chars"] if c["id"] == b.get("to")), sc["chars"][0])
        pid = sc["persona"]["id"] if sc["persona"] else 0
        try:
            amount = int(b.get("amount") or 0)
        except (TypeError, ValueError):
            raise BadRequest("сумма — число")
        note = str(b.get("note") or "").strip()
        if b.get("action") == "borrow":
            if not 1 <= amount <= 1000:
                raise BadRequest("занять можно от 1 до 1000 монет")
            text = f"*Просит в долг {amount} монет*" + (f" ({to['name']})" if len(sc["chars"]) > 1 else "") + \
                (f"\n{note}" if note else "")
            msgs = self._say(cid, text, {"kind": "loan", "amount": amount, "to": to["id"],
                                         "reply_as": to["id"]})
            return web.json_response({"messages": msgs, "coins": self.store.wallet(pid)})
        if b.get("action") == "repay":
            r = dict(rel.new(), **self.store.relation(to["id"], pid))
            debt = int(r.get("debt", 0))
            if debt <= 0:
                raise BadRequest(f"Долга нет ({to['name']})")
            amount = min(amount or debt, debt)
            if amount > self.store.wallet(pid):
                raise BadRequest(f"Не хватает монет: нужно {amount}, у вас {self.store.wallet(pid)}")
            left = self.store.add_coins(pid, -amount)
            r["debt"] = debt - amount
            self.store.save_relation(to["id"], pid, r)
            self.emit({"type": "wallet", "persona_id": pid, "coins": left})
            text = f"*Возвращает долг: {amount} монет*" + (f" ({to['name']})" if len(sc["chars"]) > 1 else "") + \
                (f"\n{note}" if note else "")
            msgs = self._say(cid, text, {"kind": "repay", "amount": amount, "to": to["id"],
                                         "reply_as": to["id"]})
            return web.json_response({"messages": msgs, "coins": left, "debt": r["debt"]})
        raise BadRequest("action: borrow | repay")

    @api
    async def h_date(self, request):
        """Свидание или вечер с персонажем — отдельная короткая история (новелла) из чата.
        Отношения меняются по ходу, итог записывается в отношения пары."""
        cid = _id(request)
        b = await _body(request)
        sc = self._chat_scene(cid)
        if not sc["chars"]:
            raise BadRequest("в этом чате нет персонажа")
        to = next((c for c in sc["chars"] if c["id"] == b.get("to")), sc["chars"][0])
        if cards.is_minor(to) or cards.is_minor(sc["persona"]):
            raise BadRequest("Свидание недоступно: по карточке персонаж несовершеннолетний")
        setup = str(b.get("setup") or "").strip() or "вечер вдвоём — куда пойти, решим по ходу"
        settings = dict(self.store.get_setting("default_settings", {}) or {},
                        character_ids=[to["id"]],
                        persona_id=sc["persona"]["id"] if sc["persona"] else None,
                        world_id=sc["world"]["id"] if sc["world"] else None,
                        mode="story", date_of=cid)
        chat = self.store.create_chat(f"Вечер: {to['name']}", system_prompt="", settings=settings)
        self._say(chat["id"], f"[Свидание] {setup}", {"kind": "directive"})
        chat = self.store.chat_dict(chat["id"])
        self.emit({"type": "chat.updated", "chat": chat})
        return web.json_response({"chat": chat})

    @api
    async def h_date_finish(self, request):
        """Завершить вечер: короткий итог — в отношения пары, возврат в исходный чат."""
        cid = _id(request)
        chat = self.store.chat_row(cid)
        sc = self.memory.scene(chat)
        if not sc["date_of"] or not sc["chars"]:
            raise BadRequest("это не свидание")
        rows = self.store.history_rows(cid, chat["head_id"])[-30:]
        to = sc["chars"][0]
        pid = sc["persona"]["id"] if sc["persona"] else 0
        summary = ""
        if rows:
            try:
                out = await self.gen._side_llm(lambda llm: llm.complete(
                    [{"role": "system", "content": DATE_SUMMARY},
                     {"role": "user", "content": memory_transcript(rows, 600)}],
                    max_tokens=200, schema=SUMMARY_SCHEMA))
                summary = " ".join(str(json.loads(out).get("summary") or "").split())[:300]
            except (ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError,
                    ValueError) as e:
                self.log.emit(f"Итог вечера не составлен: {e}")
        if summary:
            r = dict(rel.new(), **self.store.relation(to["id"], pid))
            r["events"] = (r.get("events", []) + [{"text": f"Вечер вместе: {summary}",
                                                   "at": time.time()}])[-rel.MAX_EVENTS:]
            self.store.save_relation(to["id"], pid, r)
            self.emit({"type": "relation.updated", "chat_id": sc["date_of"],
                       "character_id": to["id"], "persona_id": pid,
                       "relation": rel.public(r), "event": ""})
        return web.json_response({"chat_id": sc["date_of"], "summary": summary})

    @api
    async def h_recap(self, request):
        """«В предыдущих сериях»: краткий пересказ, если история давно не продолжалась."""
        cid = _id(request)
        chat = self.store.chat_row(cid)
        head = chat["head_id"]
        if not head:
            return web.json_response({"recap": ""})
        key = f"recap:{cid}"
        cached = self.store.get_setting(key, {}) or {}
        if cached.get("head") == head:
            return web.json_response({"recap": cached.get("text", "")})
        rows = self.store.history_rows(cid, head)[-16:]
        try:
            out = await self.gen._side_llm(lambda llm: llm.complete(
                [{"role": "system", "content": RECAP_PROMPT},
                 {"role": "user", "content": memory_transcript(rows, 700)}],
                max_tokens=300, schema=SUMMARY_SCHEMA))
            text = " ".join(str(json.loads(out).get("summary") or "").split())
        except (ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError, ValueError) as e:
            raise BadRequest(f"пересказ не получился: {e}")
        self.store.set_setting(key, {"head": head, "text": text})
        return web.json_response({"recap": text})

    @api
    async def h_choices(self, request):
        """Карта выборов истории: развилки на текущем пути, что выбрано и что уже пробовали
        в других ветках."""
        cid = _id(request)
        chat = self.store.chat_row(cid)
        out = []
        for r in self.store.history_rows(cid, chat["head_id"]) if chat["head_id"] else []:
            if r["role"] != "assistant":
                continue
            options = json.loads(r["meta"] or "{}").get("choices") or []
            if not options:
                continue
            kids = [k for k in self.store.children(r["id"]) if k["role"] == "user"]
            tried = [k["content"].strip() for k in kids]
            path_ids = {x["id"] for x in self.store.history_rows(cid, chat["head_id"])}
            taken = next((k["content"].strip() for k in kids if k["id"] in path_ids), None)
            out.append({"msg_id": r["id"], "options": options, "taken": taken,
                        "tried": [t for t in tried if t != taken]})
        return web.json_response({"forks": out})

    @api
    async def h_gallery(self, request):
        """Все картинки чата: нарисованные и присланные, фоны новеллы, портреты и эмоции героев."""
        cid = _id(request)
        sc = self._chat_scene(cid)
        items = [{"name": i["name"], "caption": i.get("caption", ""), "kind": "image"}
                 for i in self.store.chat_images(cid)]
        items += [{"name": v["name"], "caption": v.get("place", k), "kind": "background"}
                  for k, v in self.store.vn_backgrounds(cid).items()]
        for c in sc["chars"]:
            if c.get("portrait"):
                items.append({"name": c["portrait"]["name"], "caption": c["name"], "kind": "portrait"})
            for emo, img in (c.get("sprites") or {}).items():
                items.append({"name": img["name"], "caption": f"{c['name']}: {vn.EMOTION_RU.get(emo, emo)}",
                              "kind": "sprite"})
        seen, uniq = set(), []
        for it in items:
            if it["name"] not in seen:
                seen.add(it["name"])
                uniq.append(it)
        return web.json_response({"items": uniq})

    @api
    async def h_vn_bg(self, request):
        """Нарисовать фон места по кнопке (когда автоматические фоны выключены или не удались)."""
        cid = _id(request)
        b = await _body(request)
        name = str(b.get("name") or "").strip()
        if not name:
            raise BadRequest("какое место?")
        chat = self.store.chat_row(cid)
        sc = self.memory.scene(chat)
        rows = self.store.history_rows(cid, chat["head_id"])[-2:] if chat["head_id"] else []
        if not self.gen.images_ok():
            raise BadRequest("рисование не настроено на ПК")
        self.gen._queue_bg(cid, name, vn.place_key(name), "\n".join(r["content"] for r in rows),
                           sc["world"])
        return web.json_response({"ok": True})

    @api
    async def h_proposals(self, request):
        """Предложения модели изменить карточки («персонаж меняется»)."""
        return web.json_response({"proposals": self.store.get_setting("proposals", []) or []})

    @api
    async def h_proposal(self, request):
        pid = _id(request)
        b = await _body(request)
        items = self.store.get_setting("proposals", []) or []
        prop = next((p for p in items if p["id"] == pid), None)
        if not prop:
            raise NotFound("предложение уже разобрано")
        self.store.set_setting("proposals", [p for p in items if p["id"] != pid])
        card = None
        if b.get("accept"):
            old = self.store.card(prop["card_id"])
            data = dict(old["data"], **{prop["field"]: prop["value"]})
            card = self.store.save_card(old["kind"], cards.clean_data(old["kind"], data), old["id"])
            self.emit({"type": "card.updated", "card": card})
            self.log.emit(f"Карточка «{card['name']}» обновлена: {prop['reason']}")
        self.emit({"type": "card.proposal.closed", "id": pid})
        return web.json_response({"ok": True, "card": card})

    @api
    async def h_state(self, request):
        """Ручная правка состояния квеста (в сообщении ведущего, где оно записано)."""
        mid = _id(request)
        msg = self.store.msg_dict(mid)
        b = await _body(request)
        extra = {"state": quest.clean(b.get("state"))}
        if "choices" in b:
            extra["choices"] = quest.clean_choices(b.get("choices"))
        self.store.merge_meta(mid, extra)
        msg = self.store.msg_dict(mid)
        self.emit({"type": "message.updated", "chat_id": msg["chat_id"], "message": msg})
        return web.json_response({"message": msg})

    @api
    async def h_enhance(self, request):
        """Короткий запрос → подробный английский промпт по контексту чата."""
        b = await _body(request)
        text = str(b.get("text", "")).strip()
        if not text:
            raise BadRequest("пустой запрос")
        cid = b.get("chat_id")
        cid = int(cid) if cid not in (None, "") else None
        if cid is not None:
            self.store.chat_dict(cid)   # 404, если чата нет
        try:
            res = await self.gen.enhance(cid, text)
        except (ImageError, ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError,
                ValueError, KeyError) as e:
            raise BadRequest(f"модель не смогла составить промпт: {e}")
        return web.json_response(res)

    @api
    async def h_redraw(self, request):
        """Перерисовать картинку сообщения на месте: тот же или изменённый промпт, новый seed."""
        mid = _id(request)
        msg = self.store.msg_dict(mid)
        cid = msg["chat_id"]
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        m = msg["meta"]
        src = m.get("drawn") or (m if m.get("kind") == "image" else None)
        if not src:
            raise BadRequest("в сообщении нет картинки")
        b = await _body(request)
        prompt = str(b.get("prompt") or src.get("prompt") or "").strip()
        if not prompt:
            raise BadRequest("пустой запрос")
        b.setdefault("negative", src.get("negative") or "")
        for k in ("width", "height", "steps"):
            if src.get(k) and not b.get(k):
                b[k] = src[k]
        params = _draw_params(b, prompt)
        profiles = {p["id"]: p for p in load_profiles()}
        profile = profiles.get(b.get("profile") or src.get("profile")) or \
            next(iter(profiles.values()), None)
        if not profile:
            raise BadRequest("нет профиля изображений")
        self.store.set_status(mid, "generating")
        self.gen.start_redraw(cid, mid, profile, params)
        msg = self.store.msg_dict(mid)
        self.emit({"type": "message.updated", "chat_id": cid, "message": msg})
        self.emit({"type": "busy", "busy": True})
        return web.json_response({"message": msg})

    @api
    async def h_cancel(self, request):
        n = self.gen.cancel_chat(_id(request))
        return web.json_response({"cancelled": n})

    # ----------------------------------------------------------- сообщения
    @api
    async def h_msg_patch(self, request):
        b = await _body(request)
        if "content" not in b and "pinned" not in b:
            raise BadRequest("нужно поле content или pinned")
        mid = _id(request)
        msg = None
        if "content" in b:
            msg = self.store.edit_message(mid, str(b["content"]))
        if "pinned" in b:
            msg = self.store.set_pinned(mid, bool(b["pinned"]))
        self.emit({"type": "message.updated", "chat_id": msg["chat_id"], "message": msg})
        return web.json_response({"message": msg})

    @api
    async def h_msg_delete(self, request):
        mid = _id(request)
        doomed = self.store.subtree(mid)
        if self.gen.cancel_msgs(doomed):
            await self.gen.wait_msgs(doomed)
        cid = self.store.delete_message(mid)
        self.emit({"type": "chat.changed", "chat_id": cid})
        self.emit({"type": "chat.updated", "chat": self.store.chat_dict(cid)})
        return web.json_response({"chat": self.store.chat_dict(cid),
                                  "messages": self._with_live(self.store.messages(cid))})

    @api
    async def h_regenerate(self, request):
        mid = _id(request)
        old = self.store.msg_dict(mid)
        cid = old["chat_id"]
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        b = await _body(request)
        aid = self.store.regenerate(mid)
        wish = str(b.get("wish") or "").strip()
        if wish and old["meta"].get("kind") != "image":   # переписать с пожеланием
            self.store.merge_meta(aid, {"wish": wish[:500], "prev_id": mid})
        if old["meta"].get("kind") == "image":
            profiles = {p["id"]: p for p in load_profiles()}
            profile = profiles.get(old["meta"].get("profile")) or next(iter(profiles.values()), None)
            if not profile:
                raise BadRequest("нет профиля изображений")
            om = old["meta"]
            prompt = om.get("prompt", "")
            self.store.merge_meta(aid, {"kind": "image", "source": "user", "prompt": prompt,
                                        "profile": profile["id"]})
            params = {"prompt": prompt}
            for k in ("negative", "width", "height", "steps"):
                if om.get(k):
                    params[k] = om[k]
            self.gen.start_image(cid, aid, profile, params)
        else:
            self.gen.start(cid, aid)
        self.emit({"type": "busy", "busy": True})
        self.emit({"type": "chat.changed", "chat_id": cid})
        return web.json_response({"chat": self.store.chat_dict(cid),
                                  "messages": self._with_live(self.store.messages(cid))})

    @api
    async def h_select(self, request):
        cid = self.store.select_variant(_id(request))
        self.emit({"type": "chat.changed", "chat_id": cid})
        return web.json_response({"chat": self.store.chat_dict(cid),
                                  "messages": self._with_live(self.store.messages(cid))})

    @api
    async def h_continue(self, request):
        mid = _id(request)
        old = self.store.msg_dict(mid)
        cid = old["chat_id"]
        if any(j.chat_id == cid for j in self.gen.jobs.values()):
            raise BadRequest("в этом чате уже идёт генерация")
        msg = self.store.reopen(mid)
        self.gen.start(cid, mid, prefix=msg["content"])
        self.emit({"type": "busy", "busy": True})
        self.emit({"type": "chat.changed", "chat_id": cid})
        return web.json_response({"chat": self.store.chat_dict(cid),
                                  "messages": self._with_live(self.store.messages(cid))})

    # ---------------------------------------------------------------- память
    def _memory_dict(self, cid: int) -> dict:
        chat = self.store.chat_dict(cid)
        path = self.store.path(cid)
        ctx = None
        for m in reversed(self.store.messages(cid)):
            if m["role"] == "assistant" and m["meta"].get("ctx"):
                ctx = m["meta"]["ctx"]
                break
        return {"chat_id": cid, "facts": self.store.facts(cid),
                "chronicle": self.store.chronicle_for(cid, path), "ctx": ctx,
                "settings": chat["settings"]}

    def _memory_changed(self, cid: int):
        self.emit({"type": "memory.updated", "chat_id": cid})

    @api
    async def h_memory(self, request):
        return web.json_response(self._memory_dict(_id(request)))

    @api
    async def h_fact_add(self, request):
        cid = _id(request)
        b = await _body(request)
        self.store.add_fact(cid, str(b.get("text", "")), pinned=bool(b.get("pinned", False)))
        self._memory_changed(cid)
        return web.json_response(self._memory_dict(cid))

    @api
    async def h_fact_patch(self, request):
        b = await _body(request)
        f = self.store.update_fact(_id(request), text=b.get("text"), pinned=b.get("pinned"))
        self._memory_changed(f["chat_id"])
        return web.json_response(self._memory_dict(f["chat_id"]))

    @api
    async def h_fact_delete(self, request):
        cid = self.store.delete_fact(_id(request))
        self._memory_changed(cid)
        return web.json_response(self._memory_dict(cid))

    @api
    async def h_chronicle(self, request):
        cid = _id(request)
        b = await _body(request)
        self.store.edit_chronicle(cid, str(b.get("text", "")))
        self._memory_changed(cid)
        return web.json_response(self._memory_dict(cid))

    @api
    async def h_memory_refresh(self, request):
        cid = _id(request)
        self.store.chat_dict(cid)
        self.gen.schedule_facts(cid, force=True)
        return web.json_response({"scheduled": True})

    # -------------------------------------------------------- совместимость
    async def h_models(self, request):
        try:
            async with self.session.get(f"{self._llama}/v1/models",
                                        timeout=ClientTimeout(total=10)) as r:
                return web.Response(body=await r.read(), status=r.status,
                                    content_type="application/json")
        except (ClientError, asyncio.TimeoutError) as e:
            return self._llama_down(e)

    async def h_proxy_chat(self, request):
        body = await request.read()
        try:
            stream = bool(json.loads(body).get("stream"))
        except ValueError:
            return _json_error(400, "invalid json")
        try:
            async with self.session.post(f"{self._llama}/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"}) as up:
                if not stream or up.status != 200:
                    return web.Response(body=await up.read(), status=up.status,
                                        content_type=up.content_type or "application/json")
                resp = web.StreamResponse(status=200, headers={
                    "Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
                await resp.prepare(request)
                try:
                    async for chunk in up.content.iter_any():
                        await resp.write(chunk)
                    await resp.write_eof()
                except (ConnectionResetError, ConnectionError):
                    pass
                return resp
        except (ClientError, asyncio.TimeoutError) as e:
            return self._llama_down(e)

    def _llama_down(self, e):
        self.log.emit(f"llama-server недоступен: {e}")
        return _json_error(503, "model unavailable")
