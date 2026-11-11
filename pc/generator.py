"""Генерация ответов как фоновые задачи на ПК.

Задача живёт независимо от соединения с телефоном: телефон может отключиться
и подключиться снова — ответ продолжает генерироваться и сохраняется в базу.
Ход генерации рассылается событиями message.delta со смещениями (offset),
чтобы клиент после переподключения мог склеить текст без пропусков и повторов.
"""
import asyncio
import json
import re
import time

from aiohttp import ClientError, ClientSession

import cards
import quest
import vn
import relations as rel
from imagegen import ImageError, candidates, roles
from images import save_image
from store import SAMPLING_KEYS
from memory import PROMPT_RULES, _clip, effective_settings, last_state

DELTA_INTERVAL = 0.05   # с — как часто отправлять накопленный текст
SAVE_INTERVAL = 1.0     # с — как часто сохранять промежуточный текст в базу


# Инструмент рисования для текстовой модели (вызов функций llama-server, нужен --jinja)
DRAW_TOOL = {"type": "function", "function": {
    "name": "draw_image",
    "description": "Нарисовать изображение и показать его пользователю в чате.",
    "parameters": {"type": "object", "properties": {
        "prompt": {"type": "string",
                   "description": "Detailed self-contained English prompt for the image model: "
                                  "subjects with full appearance, action, setting, lighting, "
                                  "camera, style. 40-120 words."},
        "negative": {"type": "string", "description": "What must not be in the image (English, short)."},
        "orientation": {"type": "string", "enum": ["square", "portrait", "landscape"]},
        "caption": {"type": "string", "description": "Короткая подпись к картинке по-русски."},
        "characters": {"type": "array", "items": {"type": "string"},
                       "description": "Имена персонажей чата, которые есть в кадре."},
        "pose_from_photo": {"type": "boolean",
                            "description": "true — пользователь прислал фото как образец позы "
                                           "или кадра, и его надо повторить."},
        "purpose": {"type": "string", "enum": ["scene", "text"],
                    "description": "text — главное на картинке надпись: вывеска, плакат, "
                                   "записка, обложка с названием."},
    }, "required": ["prompt", "caption"]},
}}

DRAW_HINT = {
    "on_request": (
        "## Рисование\nУ тебя есть инструмент draw_image: он рисует картинку и показывает её "
        "пользователю. Вызывай его, когда пользователь просит нарисовать, показать, сделать "
        "картинку, фото или арт. Сначала коротко ответь текстом, затем вызови инструмент — один раз "
        "за ответ. Не говори, что не умеешь рисовать. Нарисованное ты потом видишь в диалоге. "),
    "auto": (
        "## Рисование\nУ тебя есть инструмент draw_image: он рисует картинку и показывает её "
        "пользователю. Вызывай его, когда пользователь просит нарисовать или показать что-то, а также "
        "сам иллюстрируй ключевые моменты: появление нового персонажа или места, важную или яркую "
        "сцену истории — но не чаще чем раз в 3–4 ответа и не в обычной беседе. Сначала напиши ответ "
        "текстом, затем вызови инструмент — один раз за ответ. Нарисованное ты потом видишь в "
        "диалоге. "),
}

ORIENTATION = {"square": (1024, 1024), "portrait": (832, 1216), "landscape": (1216, 832)}
TOOL_TAG = "<tool_call>"
# дополнение к подсказке о рисовании: образцы и надписи
DRAW_EXTRA = (
    "Если в кадре персонажи чата (в том числе ты сам — например, селфи), перечисли их имена в "
    "characters: тогда они будут нарисованы похожими на свои портреты. Если пользователь прислал "
    "фото и просит повторить позу или кадр («сфоткайся так же»), поставь pose_from_photo. "
    "Если главное на картинке — надпись (вывеска, плакат, записка), поставь purpose=text и "
    "впиши текст надписи в промпт в кавычках. ")


def ref_prompt(prompt: str, names: list, pose: bool) -> str:
    """Промпт для рисования по образцам: кто на каком образце, откуда взять позу."""
    parts = [f"Picture {i + 1} shows {n}: keep exactly the same face, hair and outfit."
             for i, n in enumerate(names)]
    if pose:
        parts.append(f"Picture {len(names) + 1} is the pose and framing reference: copy the pose, "
                     "body position and camera angle, not the person.")
    return " ".join(parts + ["Create a new image:", prompt])


def _text_tool_call(text: str):
    """Запасной разбор, если сервер не распознал вызов и он пришёл текстом:
    <tool_call>{"name":..,"arguments":{..}}</tool_call> или <function=..><parameter=..>..</parameter>."""
    body = text.split(TOOL_TAG, 1)[1].split("</tool_call>", 1)[0].strip()
    try:
        obj = json.loads(body)
        args = obj.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args)
        return {"name": obj.get("name", ""), "args": args}
    except ValueError:
        pass
    m = re.search(r"<function=([\w-]+)>", body)
    if not m:
        return None
    args = {k: v.strip() for k, v in re.findall(r"<parameter=(\w+)>(.*?)</parameter>", body, re.S)}
    return {"name": m.group(1), "args": args}


def _held(text: str) -> int:
    """Сколько текста можно показывать: вызов инструмента текстом пользователю не нужен."""
    i = text.find(TOOL_TAG)
    if i >= 0:
        return i
    for k in range(len(TOOL_TAG) - 1, 0, -1):   # хвост может оказаться началом тега
        if text.endswith(TOOL_TAG[:k]):
            return len(text) - k
    return len(text)


class GenError(Exception):
    pass


def u16len(s: str) -> int:
    """Длина в единицах UTF-16 — так считают String.length в Kotlin/Java и JS.
    Смещения в событиях даются в этих единицах, иначе эмодзи сбивали бы склейку."""
    return len(s.encode("utf-16-le")) // 2


class Job:
    def __init__(self, chat_id: int, msg_id: int, prefix: str = ""):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.continuing = bool(prefix)   # продолжение: текст дописывается к prefix
        self.content = prefix
        self.reasoning = ""
        self.task = None


class Generator:
    def __init__(self, store, llama_url: str, session: ClientSession, emit, log, memory, n_ctx,
                 vram=None):
        self.vram = vram          # переключение видеопамяти LLM ↔ изображения (может отсутствовать)
        self.store = store
        self.llama_url = llama_url
        self.session = session
        self.emit = emit          # emit(dict) — разослать событие клиентам
        self.log = log
        self.memory = memory
        self.n_ctx = n_ctx        # n_ctx() — текущий размер контекста модели
        self.jobs = {}            # msg_id -> Job
        self.lock = asyncio.Lock()  # одна генерация за раз: одна видеокарта
        self.bg_task = None       # фоновое обновление памяти
        self.bg_pending = {}      # chat_id -> force
        self.portraits = set()           # карточки, для которых сейчас рисуется портрет
        self.bg_lock = asyncio.Lock()    # фоновая модель: один запрос за раз
        self.after_tasks = set()
        self.vn_pending = set()          # (chat_id, ключ места): фон в очереди
        self.card_tasks = {}             # карточка → задача рисования портрета или эмоций
        self.bg_tasks = {}               # (chat_id, ключ места) → задача рисования фона
        self.images_ok = lambda: False   # можно ли сейчас рисовать (есть sd-server и готовый профиль)

    # ------------------------------------------------------------ управление
    def start(self, chat_id: int, msg_id: int, prefix: str = "") -> Job:
        # ответ пользователю важнее фоновой памяти: прерываем её, она повторится позже
        self._preempt()
        job = Job(chat_id, msg_id, prefix)
        self.jobs[msg_id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job))
        return job

    def start_image(self, chat_id: int, msg_id: int, profile: dict, params: dict) -> Job:
        return self._start(chat_id, msg_id, lambda job: self._run_image(job, profile, params))

    def start_redraw(self, chat_id: int, msg_id: int, profile: dict, params: dict) -> Job:
        return self._start(chat_id, msg_id, lambda job: self._run_redraw(job, profile, params))

    def _start(self, chat_id, msg_id, run) -> Job:
        self._preempt()
        job = Job(chat_id, msg_id)
        self.jobs[msg_id] = job
        job.task = asyncio.get_running_loop().create_task(run(job))
        return job

    def _stager(self, job: Job):
        last = [0.0]

        def stage(st, done=None, total=None):
            now = time.monotonic()
            if st == "image" and now - last[0] < 0.4 and done:
                return
            last[0] = now
            ev = {"type": "message.stage", "chat_id": job.chat_id, "id": job.msg_id, "stage": st}
            if done is not None and total:
                ev["done"], ev["total"] = int(done), int(total)
            self.emit(ev)
        return stage

    async def _draw(self, stage, profile: dict, params: dict) -> dict:
        """Нарисовать (вызывать под self.lock) → {seed, width, height, steps, images}."""
        if not self.vram:
            raise ImageError("генерация изображений недоступна")
        profiles = [profile] if isinstance(profile, dict) else list(profile or [])
        if not profiles:
            raise ImageError("нет готового профиля изображений")
        params = dict(params, quality=self.store.get_setting("image_quality", "normal"))
        for i, pr in enumerate(profiles):
            try:
                await self.vram.ensure_image(pr, on_stage=stage)
                stage("image", 0, params.get("steps") or pr.get("steps"))
                self.log(f"Рисование ({pr.get('name')}): {params.get('prompt', '')[:80]}")
                res = await self.vram.generate(pr, params, lambda st, d, t: stage("image", d, t))
                img = save_image(res.pop("b64"))
                res["images"] = [img]
                res["profile"] = pr["id"]
                return res
            except ImageError as e:
                if i + 1 == len(profiles):
                    raise
                # модель не загрузилась или упала — рисует следующая подходящая
                self.log(f"«{pr.get('name')}» не справилась ({str(e)[:160]}) — "
                         f"пробую «{profiles[i + 1].get('name')}»")
                await self.vram.stop_sd()

    def routes(self) -> dict:
        r = self.store.get_setting("image_routes", {})
        return r if isinstance(r, dict) else {}

    def profiles_for(self, task: str, need: str = None) -> list:
        return candidates(task, self.routes(), need)

    async def enhance(self, chat_id, text: str) -> dict:
        """Короткий запрос → подробный английский промпт (текстовой моделью)."""
        self._preempt()
        async with self.lock:
            if self.vram:
                await self.vram.ensure_llm()
            return await self.memory.image_prompt(chat_id, text)

    # ------------------------------------------------------------ карточки
    async def _llm(self, messages, max_tokens, schema):
        self._preempt()
        async with self.lock:
            if self.vram:
                await self.vram.ensure_llm()
            return await self.memory.llama.complete(messages, max_tokens=max_tokens, schema=schema)

    async def fill_card(self, kind: str, text: str) -> dict:
        """Описание своими словами → все поля карточки."""
        out = await self._llm([{"role": "system", "content": cards.fill_prompt(kind)},
                               {"role": "user", "content": text.strip()}],
                              2500, cards.fill_schema(kind))
        return cards.parse_fill(kind, out)   # (поля, лорбук)

    async def add_lore(self, world: dict, existing: list, text: str) -> list:
        have = "\n".join(f"- {e['title']}: {e['content'][:200]}" for e in existing) or "(пусто)"
        user = (f"МИР:\n{cards.card_text(world)}\n\nУЖЕ ЕСТЬ В ЛОРБУКЕ:\n{have}\n\n"
                f"ПРОСЬБА:\n{text.strip()}")
        out = await self._llm([{"role": "system", "content": cards.lore_add_prompt()},
                               {"role": "user", "content": user}], 2500, cards.LORE_ADD_SCHEMA)
        return cards.clean_lore(json.loads(out).get("lore"))

    async def rewrite_field(self, card: dict, key: str, wish: str) -> str:
        user = f"КАРТОЧКА:\n{cards.card_text(card)}\n\nПОЛЕ: {key}" + \
            (f"\nПОЖЕЛАНИЕ: {wish.strip()}" if wish.strip() else "")
        out = await self._llm([{"role": "system", "content": cards.rewrite_prompt(card["kind"], key)},
                               {"role": "user", "content": user}], 1500, cards.REWRITE_SCHEMA)
        return str(json.loads(out).get("value", "")).strip()

    def start_portrait(self, card: dict, profile: dict):
        """Портрет карточки — рисуется в фоне, прогресс событиями card.stage."""
        self._preempt()
        cid = card["id"]

        def stage(st, done=None, total=None):
            ev = {"type": "card.stage", "id": cid, "stage": st}
            if done is not None and total:
                ev["done"], ev["total"] = int(done), int(total)
            self.emit(ev)

        async def run():
            self.portraits.add(cid)
            try:
                async with self.lock:
                    stage("starting")
                    params = {"prompt": cards.portrait_prompt(card), "width": 832, "height": 1216}
                    res = await self._draw(stage, profile, params)
                img = dict(res["images"][0], prompt=params["prompt"], seed=res.get("seed"),
                           profile=res.get("profile"))
                self.emit({"type": "card.updated", "card": self.store.set_portrait(cid, img)})
                self.log(f"Портрет «{card['name']}» готов")
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                self.log(f"Портрет «{card['name']}» не нарисован: {e}")
                self.emit({"type": "card.stage", "id": cid, "stage": "error", "error": str(e)})
            finally:
                self.portraits.discard(cid)
                self.emit({"type": "card.stage", "id": cid, "stage": "done"})
                self.emit({"type": "busy", "busy": self.busy})

        self.emit({"type": "card.stage", "id": cid, "stage": "queued"})
        t = asyncio.get_running_loop().create_task(run())
        self.card_tasks[cid] = t
        t.add_done_callback(lambda _t, c=cid: self.card_tasks.pop(c, None) if self.card_tasks.get(c) is _t else None)
        return t

    async def _run_image(self, job: Job, profile: dict, params: dict):
        status, error = "done", None
        profiles = [profile] if isinstance(profile, dict) else list(profile)
        chosen = bool(params.pop("chosen", False))   # профиль выбран руками, а не «Авто»
        meta = {"kind": "image", "source": "user", "prompt": params.get("prompt", ""),
                "profile": profiles[0]["id"] if profiles else ""}
        started = time.monotonic()
        stage = self._stager(job)
        try:
            async with self.lock:
                if params.pop("enhance", False):
                    request = params["prompt"]
                    if self.vram:
                        await self.vram.ensure_llm(on_stage=stage)
                    stage("enhancing")
                    try:
                        better = await self.memory.image_prompt(job.chat_id, request)
                        params["prompt"] = better["prompt"]
                        if better["negative"] and not params.get("negative"):
                            params["negative"] = better["negative"]
                        meta.update(request=request, prompt=better["prompt"])
                        self.log(f"Промпт доработан моделью: {better['prompt'][:100]}")
                    except Exception as e:  # noqa: BLE001 — рисуем по исходному запросу
                        self.log(f"Промпт не доработан ({e}) — рисую как есть")
                if params.get("negative"):
                    meta["negative"] = params["negative"]
                try:   # единый стиль картинок чата (портрет, селфи, иллюстрации — одинаково)
                    style = self.memory.style(self.store.chat_row(job.chat_id))
                except LookupError:
                    style = ""
                if style:
                    params["prompt"] = cards.with_style(params["prompt"], style)
                    meta["prompt"] = params["prompt"]
                # похожесть: упомянутые в запросе персонажи чата — образцами их портретов
                if params.pop("likeness", True):
                    try:
                        cs = json.loads(self.store.chat_row(job.chat_id)["settings"] or "{}")
                    except LookupError:
                        cs = {}
                    refs = self.references(job.chat_id, cs, [], False,
                                           text=meta.get("request") or params["prompt"])
                    edit = self.profiles_for("likeness", "edit") if refs else []
                    if chosen and profiles and "edit" in roles(profiles[0]):
                        edit = profiles     # выбранная руками модель сама умеет по образцу
                    if edit:
                        profiles = edit
                        meta["profile"] = edit[0]["id"]
                        params["ref_images"] = refs["images"]
                        params["prompt"] = ref_prompt(params["prompt"], refs["names"], False)
                        meta["refs"] = refs["names"]
                meta.update(await self._draw(stage, profiles, params))
        except asyncio.CancelledError:
            status = "cancelled"
        except (ImageError, GenError) as e:
            status, error = "error", str(e)
        except (ClientError, asyncio.TimeoutError, ConnectionError) as e:
            status, error = "error", f"sd-server недоступен ({e.__class__.__name__})"
        except Exception as e:  # noqa: BLE001
            status, error = "error", f"Внутренняя ошибка: {e}"
        finally:
            meta["seconds"] = round(time.monotonic() - started, 1)
            self.jobs.pop(job.msg_id, None)
            try:
                self.store.finish(job.msg_id, "", "", status, error=error, meta=meta)
                self.emit({"type": "message.done", "chat_id": job.chat_id,
                           "message": self.store.msg_dict(job.msg_id)})
                self.emit({"type": "chat.updated", "chat": self.store.chat_dict(job.chat_id)})
            except LookupError:
                pass
            if status == "done":
                self.bg_pending.setdefault(job.chat_id, False)   # подписать картинку, когда вернётся LLM
            self.log(f"Картинка {job.msg_id}: {status} за {meta['seconds']} с"
                     + (f" — {error}" if error else ""))
            self.emit({"type": "busy", "busy": self.busy})

    async def _run_redraw(self, job: Job, profile: dict, params: dict):
        """Перерисовать картинку сообщения на месте (текст ответа не меняется)."""
        row = self.store.msg_row(job.msg_id)
        meta = json.loads(row["meta"] or "{}")
        target = meta["drawn"] if meta.get("drawn") else meta
        stage = self._stager(job)
        started = time.monotonic()
        try:
            async with self.lock:
                res = await self._draw(stage, profile, params)
            meta["images"] = res.pop("images")
            target.update(res, profile=profile["id"], prompt=params["prompt"])
            target.pop("seen", None)
            meta.pop("draw_error", None)
            self.bg_pending.setdefault(job.chat_id, False)
            result = "ok"
        except asyncio.CancelledError:
            result = "отменено"
        except Exception as e:  # noqa: BLE001 — старая картинка остаётся
            meta["draw_error"] = str(e) if isinstance(e, (ImageError, GenError)) else \
                f"{e.__class__.__name__}: {e}"
            result = meta["draw_error"]
        finally:
            self.jobs.pop(job.msg_id, None)
            try:
                self.store.finish(job.msg_id, row["content"], row["reasoning"], "done",
                                  usage={"prompt_tokens": row["prompt_tokens"],
                                         "completion_tokens": row["completion_tokens"]},
                                  meta=meta)
                self.emit({"type": "message.done", "chat_id": job.chat_id,
                           "message": self.store.msg_dict(job.msg_id)})
            except LookupError:
                pass
            self.log(f"Перерисовка {job.msg_id}: {result} за {time.monotonic() - started:.1f} с")
            self.emit({"type": "busy", "busy": self.busy})

    def schedule_facts(self, chat_id: int, force: bool = False):
        self.bg_pending[chat_id] = force or self.bg_pending.get(chat_id, False)
        self._kick()

    def _preempt(self):
        """Ответ пользователю важнее фона: фон на большой модели прерывается (повторится позже).
        На фоновой модели он не мешает и продолжается."""
        if self.bg_task and not self.bg_task.done() and not self.memory.bg_llm():
            self.bg_task.cancel()

    def _kick(self):
        if (self.bg_task and not self.bg_task.done()) or not self.bg_pending:
            return
        if self.busy and not self.memory.bg_llm():
            return   # без фоновой модели фон ждёт, пока большая освободится
        chat_id, force = self.bg_pending.popitem()
        self.bg_task = asyncio.get_running_loop().create_task(self._bg(chat_id, force))

    async def _bg(self, chat_id: int, force: bool):
        try:
            await asyncio.sleep(1.5)   # пользователь может сразу написать ещё
            bg = self.memory.bg_llm()
            if bg:
                # факты — на фоновой модели, не мешая ответам и рисованию
                async with self.bg_lock:
                    await self.memory.extract_facts(chat_id, force, llm=bg)
                # подписи картинок нужны зрению большой модели — только когда она свободна
                if self.memory.vision() and not self.busy and not self.lock.locked() and \
                        (not self.vram or self.vram.mode == "llm"):
                    async with self.lock:
                        await self.memory.describe_images(chat_id)
            else:
                async with self.lock:
                    if self.vram and self.vram.mode != "llm":
                        # сейчас в памяти модель изображений — не гоняем её ради фона
                        self.bg_pending.setdefault(chat_id, force)
                        return
                    await self.memory.describe_images(chat_id)
                    await self.memory.extract_facts(chat_id, force)
        except asyncio.CancelledError:
            self.bg_pending.setdefault(chat_id, force)
            return
        except LookupError:
            pass   # чат удалён
        except Exception as e:  # noqa: BLE001
            self.log(f"Память чата {chat_id}: {e}")
        asyncio.get_running_loop().call_soon(self._kick)

    # ---------------------------------------------- после хода: состояние, отношения
    def _after(self, chat_id: int, msg_id: int):
        t = asyncio.get_running_loop().create_task(self._after_turn(chat_id, msg_id))
        self.after_tasks.add(t)
        t.add_done_callback(self.after_tasks.discard)

    # ------------------------------------------------------- новелла: фоны, спрайты
    def _queue_bg(self, chat_id: int, place: str, key: str, context: str, world):
        if (chat_id, key) in self.vn_pending or not self.images_ok():
            return
        self.vn_pending.add((chat_id, key))
        self.emit({"type": "vn.background", "chat_id": chat_id, "key": key, "state": "queued"})
        t = asyncio.get_running_loop().create_task(self._vn_bg(chat_id, place, key, context, world))
        self.after_tasks.add(t)
        t.add_done_callback(self.after_tasks.discard)
        self.bg_tasks[(chat_id, key)] = t
        t.add_done_callback(lambda _t, k=(chat_id, key): self.bg_tasks.pop(k, None))

    async def _vn_bg(self, chat_id, place, key, context, world):
        try:
            chat = self.store.chat_row(chat_id)
            sc = self.memory.scene(chat)
            # о чём история: первое указание пользователя (завязка) и герои — чтобы фон был
            # из этого мира и времени, а не «коридор вообще»
            first = self.store.first_user_text(chat_id)
            cast = "; ".join(f"{c['data'].get('name', '')} — {c['data'].get('short', '')}"
                             for c in sc["chars"])
            msgs = vn.bg_messages(place, world, context, first, cast)
            # промпт пишет большая модель: она только что отвечала и ещё в памяти, а после
            # рисования всё равно будет загружаться заново; маленькая здесь ошибается чаще
            async with self.lock:
                if self.vram:
                    await self.vram.ensure_llm()
                out = await self.memory.llama.complete(msgs, max_tokens=300, schema=vn.BG_SCHEMA)
            prompt = vn.bg_prompt(json.loads(out).get("prompt") or place, world,
                                  self.memory.style(chat))
            profile = self.profiles_for("background")
            if not profile:
                return
            async with self.lock:
                res = await self._draw(lambda *a, **k: None, profile,
                                       {"prompt": prompt, "width": 1216, "height": 832})
            img = dict(res["images"][0], prompt=prompt, place=place)
            self.store.set_vn_background(chat_id, key, img)
            self.emit({"type": "vn.background", "chat_id": chat_id, "key": key, "state": "ready",
                       "image": img})
            self.log(f"Фон «{place}» готов")
        except LookupError:
            pass
        except Exception as e:  # noqa: BLE001
            self.log(f"Фон «{place}» не нарисован: {e}")
            self.emit({"type": "vn.background", "chat_id": chat_id, "key": key, "state": "error"})
        finally:
            self.vn_pending.discard((chat_id, key))
            self.emit({"type": "busy", "busy": self.busy})

    def start_sprites(self, card: dict, profile: list):
        """Набор эмоций персонажа для новеллы — одна загрузка модели изображений на все шесть.
        Сид как у портрета: лицо и одежда получаются похожими."""
        cid = card["id"]
        seed = (card.get("portrait") or {}).get("seed")

        def stage(st, done=None, total=None):
            ev = {"type": "card.stage", "id": cid, "stage": st}
            if done is not None and total:
                ev["done"], ev["total"] = int(done), int(total)
            self.emit(ev)

        async def run():
            self.portraits.add(cid)
            sprites = dict(card.get("sprites") or {})
            try:
                async with self.lock:
                    stage("starting")
                    for i, emo in enumerate(vn.EMOTIONS):
                        stage("sprites", i, len(vn.EMOTIONS))
                        params = {"prompt": vn.sprite_prompt(card, emo), "width": 832, "height": 1216}
                        if seed is not None:
                            params["seed"] = int(seed)
                        if "edit" in roles(profile[0]) and card.get("portrait"):
                            # по образцу портрета — то же лицо, меняется только эмоция
                            params["ref_images"] = [card["portrait"]["name"]]
                            params["prompt"] = ref_prompt(params["prompt"], [card["name"]], False)
                        res = await self._draw(lambda st, d=None, t=None: None if st == "image" else stage(st),
                                               profile, params)
                        sprites[emo] = res["images"][0]
                        self.emit({"type": "card.updated", "card": self.store.set_sprites(cid, sprites)})
                self.log(f"Эмоции «{card['name']}» готовы")
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                self.log(f"Эмоции «{card['name']}» не нарисованы: {e}")
                self.emit({"type": "card.stage", "id": cid, "stage": "error", "error": str(e)})
            finally:
                self.portraits.discard(cid)
                self.emit({"type": "card.stage", "id": cid, "stage": "done"})
                self.emit({"type": "busy", "busy": self.busy})

        self.emit({"type": "card.stage", "id": cid, "stage": "queued"})
        t = asyncio.get_running_loop().create_task(run())
        self.card_tasks[cid] = t
        t.add_done_callback(lambda _t, c=cid: self.card_tasks.pop(c, None) if self.card_tasks.get(c) is _t else None)
        return t

    async def _side_llm(self, fn):
        """Служебный запрос: на фоновой модели, если она есть, иначе на большой (под self.lock)."""
        bg = self.memory.bg_llm()
        if bg:
            async with self.bg_lock:
                return await fn(bg)
        async with self.lock:
            if self.vram:
                await self.vram.ensure_llm()
            return await fn(self.memory.llama)

    async def _after_turn(self, chat_id: int, msg_id: int):
        """После ответа: состояние квеста и варианты действий, отношения персонажей.
        Ответ уже показан — это догружается следом событием message.updated."""
        try:
            chat = self.store.chat_row(chat_id)
            sc = self.memory.scene(chat)
            quest_mode = sc["mode"] in ("quest", "gm")
            rel_mode = (sc["mode"] == "chat" or sc["date_of"]) and sc["chars"]
            story_mode = sc["mode"] == "story"
            if not (quest_mode or rel_mode or story_mode):
                return
            row = self.store.msg_row(msg_id)
            answer = row["content"]
            if not answer.strip():
                return
            parent = self.store.msg_row(row["parent_id"]) if row["parent_id"] else None
            pmeta = json.loads(parent["meta"] or "{}") if parent else {}
            player = parent["content"] if parent and parent["role"] == "user" else ""
            if pmeta.get("kind") == "nudge":
                player = "(собеседник вернулся после паузы и ещё ничего не написал)"
            pid = sc["persona"]["id"] if sc["persona"] else 0
            extra = {}
            # перегенерированный вариант ответа не должен второй раз менять отношения и кошелёк
            # (иначе симпатию и монеты можно «накрутить» перегенерацией)
            first = not parent or len(self.store.children(parent["id"])) <= 1
            if story_mode:   # кадры новеллы; новые места — фоны в очередь рисования
                beats = vn.parse(answer, sc["chars"])
                extra["beats"] = beats
                extra["choices"] = vn.choices(answer)
                have = self.store.vn_backgrounds(chat_id)
                auto_bg = json.loads(chat["settings"] or "{}").get("vn_bg") != "manual"
                for b in beats:
                    if auto_bg and b["type"] == "place" and b["key"] not in have:
                        self._queue_bg(chat_id, b["name"], b["key"], answer, sc["world"])
            if quest_mode:
                hist = self.store.history_rows(chat_id, parent["id"]) if parent else []
                prev = last_state(hist)
                try:
                    out = await self._side_llm(lambda llm: llm.complete(
                        quest.update_messages(prev, player, answer), max_tokens=900,
                        schema=quest.STATE_SCHEMA))
                    state, choices, coins = quest.parse(out)
                    extra.update(state=state, choices=choices if sc["mode"] == "quest" else [])
                    if coins and first:
                        left = self.store.add_coins(pid, coins)
                        extra["coins"] = coins
                        self.emit({"type": "wallet", "persona_id": pid, "coins": left})
                except Exception as e:  # noqa: BLE001 — ход важнее учёта
                    self.log(f"Состояние квеста не обновлено: {e}")
                    if prev:
                        extra["state"] = prev
            if rel_mode and first:
                meta = json.loads(row["meta"] or "{}")
                ids = meta.get("speakers") or [c["id"] for c in sc["chars"]]
                user = self.memory.user_name(sc)
                events = []
                for c in sc["chars"]:
                    if c["id"] not in ids:
                        continue
                    r = dict(rel.new(), **self.store.relation(c["id"], pid))
                    try:
                        out = await self._side_llm(lambda llm, c=c, r=r: llm.complete(
                            rel.update_messages(c, user, r, player, answer), max_tokens=400,
                            schema=rel.UPDATE_SCHEMA))
                        upd = rel.parse(out)
                        r, event = rel.apply(r, upd)
                        given = 0
                        if pmeta.get("kind") == "loan" and pmeta.get("to") == c["id"]:
                            # просили в долг — даёт не больше просьбы (или отказывает)
                            given = max(0, min(int(upd.get("money_given") or 0),
                                               int(pmeta.get("amount") or 0)))
                            if given:
                                r["debt"] = r.get("debt", 0) + given
                                r["debt_at"] = time.time()
                        if given:
                            left = self.store.add_coins(pid, given)
                            extra["coins"] = extra.get("coins", 0) + given
                            self.emit({"type": "wallet", "persona_id": pid, "coins": left})
                    except Exception as e:  # noqa: BLE001
                        self.log(f"Отношения не обновлены ({c['name']}): {e}")
                        continue
                    self.store.save_relation(c["id"], pid, r)
                    self.log(f"Отношения «{c['name']}»: симпатия {r['sympathy']}, доверие {r['trust']}, "
                             f"{rel.status(r)}, настроение «{rel.mood(r)}»" + (f" — {event}" if event else ""))
                    if event:
                        events.append({"character_id": c["id"], "text": event})
                    self.emit({"type": "relation.updated", "chat_id": chat_id,
                               "character_id": c["id"], "persona_id": pid,
                               "relation": rel.public(r), "event": event})
                if events:
                    extra["events"] = events
            if extra:
                self.store.merge_meta(msg_id, extra)
                self.emit({"type": "message.updated", "chat_id": chat_id,
                           "message": self.store.msg_dict(msg_id)})
        except LookupError:
            pass   # удалено, пока считали
        except Exception as e:  # noqa: BLE001
            self.log(f"После хода {msg_id}: {e}")

    async def _tool_draw(self, job: Job, chat_settings: dict, args: dict, meta: dict, flush):
        """Модель вызвала draw_image: текст уже готов, рисуем картинку к этому же сообщению.
        Ошибка рисования не портит ответ — она пишется в meta.draw_error."""
        flush()
        self.store.save_progress(job.msg_id, job.content, job.reasoning)
        w, h = ORIENTATION.get(str(args.get("orientation", "")), ORIENTATION["square"])
        drawn = {"source": "model", "prompt": " ".join(str(args["prompt"]).split()),
                 "negative": str(args.get("negative") or "").strip(),
                 "caption": str(args.get("caption") or "").strip(),
                 "orientation": args.get("orientation") or "square"}
        meta["drawn"] = drawn
        self.emit({"type": "message.stage", "chat_id": job.chat_id, "id": job.msg_id,
                   "stage": "drawing"})
        # модель под задачу: надписи — той, что умеет текст; остальное — «картинки в чате»
        profile = self.profiles_for("text" if args.get("purpose") == "text" else "photo")
        if not profile:
            meta["draw_error"] = "нет готового профиля изображений"
            return
        try:   # единый стиль картинок чата — даже если модель забыла его вписать
            style = self.memory.style(self.store.chat_row(job.chat_id))
        except LookupError:
            style = ""
        if style and args.get("purpose") != "text":
            drawn["prompt"] = cards.with_style(drawn["prompt"], style)
        params = {"prompt": drawn["prompt"], "width": w, "height": h}
        if drawn["negative"]:
            params["negative"] = drawn["negative"]
        # похожесть: портреты персонажей в кадре и (если просили) фото позы — образцами
        pose = args.get("pose_from_photo") in (True, 1, "true", "True", "1", "yes")
        refs = {} if args.get("purpose") == "text" else self.references(
            job.chat_id, chat_settings, args.get("characters") or [], pose, job.msg_id)
        if refs:
            edit = self.profiles_for("likeness", "edit")
            if edit:
                profile = edit
                params["ref_images"] = refs["images"]
                params["prompt"] = ref_prompt(drawn["prompt"], refs["names"], refs["pose"])
                drawn["refs"] = refs["names"] + (["фото позы"] if refs["pose"] else [])
        drawn["profile"] = profile[0]["id"]
        self.log(f"Модель рисует: {drawn['caption'] or drawn['prompt'][:60]}")
        try:
            res = await self._draw(self._stager(job), profile, params)
            meta["images"] = res.pop("images")
            drawn.update(res)
        except (ImageError, GenError) as e:
            meta["draw_error"] = str(e)
        except (ClientError, asyncio.TimeoutError, ConnectionError) as e:
            meta["draw_error"] = f"sd-server недоступен ({e.__class__.__name__})"

    def references(self, chat_id: int, chat_settings: dict, names: list, pose: bool,
                   msg_id: int = None, text: str = "") -> dict:
        """Образцы для похожести: портреты персонажей чата, которые в кадре (по именам из
        вызова инструмента или упомянутые в тексте запроса), и фото позы из сообщения
        пользователя. Выключается настройкой чата likeness=false."""
        if chat_settings.get("likeness") is False:
            return {}
        try:
            sc = self.memory.scene(self.store.chat_row(chat_id))
        except LookupError:
            return {}
        cast = [c for c in sc["chars"] + ([sc["persona"]] if sc["persona"] else []) if c.get("portrait")]
        if isinstance(names, str):   # модель могла прислать строку вместо списка
            names = [x for x in re.split(r"[,;]", names.strip("[] "))]
        want = {str(n).strip(" \"'").lower() for n in names or [] if str(n).strip()}
        low = text.lower()
        picked = [c for c in cast if (c["data"].get("name") or "").strip().lower() in want
                  or (low and (c["data"].get("name") or "~").lower() in low)]
        images = [c["portrait"]["name"] for c in picked][:2]
        photo = None
        if pose and msg_id:
            try:
                row = self.store.msg_row(msg_id)
                parent = self.store.msg_row(row["parent_id"]) if row["parent_id"] else None
                imgs = json.loads(parent["meta"] or "{}").get("images") if parent else None
                photo = imgs[-1]["name"] if imgs else None
            except (LookupError, KeyError, IndexError, TypeError):
                photo = None
        if photo:
            images.append(photo)
        if not images:
            return {}
        return {"images": images, "names": [c["data"].get("name") or "?" for c in picked][:2],
                "pose": bool(photo)}

    def cancel_card(self, card_id: int) -> bool:
        """Карточку удаляют — портрет или эмоции для неё дорисовывать незачем."""
        t = self.card_tasks.get(card_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    def cancel_backgrounds(self, chat_id: int) -> int:
        """Чат удаляют — фоны его мест больше не нужны."""
        n = 0
        for (cid, _key), t in list(self.bg_tasks.items()):
            if cid == chat_id and not t.done():
                t.cancel()
                n += 1
        return n

    def cancel_chat(self, chat_id: int) -> int:
        n = 0
        for job in list(self.jobs.values()):
            if job.chat_id == chat_id and job.task and not job.task.done():
                job.task.cancel()
                n += 1
        return n

    def cancel_msgs(self, ids) -> int:
        n = 0
        for mid in ids:
            job = self.jobs.get(mid)
            if job and job.task and not job.task.done():
                job.task.cancel()
                n += 1
        return n

    async def wait_msgs(self, ids):
        tasks = [self.jobs[m].task for m in ids if m in self.jobs and self.jobs[m].task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self):
        tasks = [j.task for j in self.jobs.values() if j.task and not j.task.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def live(self, msg_id: int):
        """Текущий текст идущей генерации (для GET чата)."""
        return self.jobs.get(msg_id)

    @property
    def busy(self) -> bool:
        return bool(self.portraits or self.vn_pending) or \
            any(j.task and not j.task.done() for j in self.jobs.values())

    # -------------------------------------------------------------- задача
    async def _run(self, job: Job):
        status, error, usage, meta = "done", None, {}, {}
        sent_c, sent_r = len(job.content), 0      # сколько уже разослано (индексы Python)
        off_c, off_r = u16len(job.content), 0      # то же в единицах UTF-16 — для клиента
        last_emit = last_save = 0.0
        started = time.monotonic()

        def flush_delta():
            nonlocal sent_c, sent_r, off_c, off_r, last_emit
            vis = max(sent_c, _held(job.content))
            if vis == sent_c and len(job.reasoning) == sent_r:
                return
            pc, pr = job.content[sent_c:vis], job.reasoning[sent_r:]
            self.emit({
                "type": "message.delta", "chat_id": job.chat_id, "id": job.msg_id,
                "offset": off_c, "content": pc, "r_offset": off_r, "reasoning": pr,
            })
            sent_c, sent_r = vis, len(job.reasoning)
            off_c += u16len(pc)
            off_r += u16len(pr)
            last_emit = time.monotonic()

        try:
            async with self.lock:
                if self.vram:
                    await self.vram.ensure_llm(on_stage=lambda st: self.emit({
                        "type": "message.stage", "chat_id": job.chat_id, "id": job.msg_id, "stage": st}))
                chat = self.store.chat_row(job.chat_id)
                chat_settings = json.loads(chat["settings"] or "{}")
                settings = effective_settings(chat_settings)
                thinking = settings.pop("thinking")
                illustrate = chat_settings.get("illustrate") or "on_request"
                # в llama-server уходят только параметры генерации; настройки чата
                # (режим, персонажи, стиль, иллюстрации…) — нет
                settings = {k: v for k, v in settings.items() if k in SAMPLING_KEYS}
                scene = self.memory.scene(chat)
                tools = illustrate in DRAW_HINT and not job.continuing and self.images_ok()
                hint = DRAW_HINT[illustrate] + DRAW_EXTRA + PROMPT_RULES if tools else ""
                if tools and self.memory.look(chat):
                    hint += "\n" + self.memory.look(chat)
                row = self.store.msg_row(job.msg_id)
                own = json.loads(row["meta"] or "{}")
                parent = self.store.msg_row(row["parent_id"]) if row["parent_id"] else None
                pmeta = json.loads(parent["meta"] or "{}") if parent else {}
                who = self.store.card_or_none(pmeta.get("reply_as"))
                if who:   # пользователь выбрал, кто из персонажей отвечает
                    hint += (f"\n\nСейчас отвечает только {who['data'].get('name')}: остальные "
                             "персонажи молчат, если их прямо не касается.")
                if own.get("wish") and not job.continuing:
                    meta["wish"] = own["wish"]
                    try:
                        prev = self.store.msg_row(own.get("prev_id"))["content"]
                    except (LookupError, TypeError):
                        prev = ""
                    hint += (f"\n\n## Переписать ответ\nПерепиши свой предыдущий вариант ответа "
                             f"на последнее сообщение. Пожелание: {own['wish']}"
                             + (f"\nПредыдущий вариант:\n{_clip(prev, 6000)}" if prev else ""))
                messages, stats = await self.memory.build(
                    job.msg_id, self.n_ctx(), dict(settings, thinking=thinking), job.continuing,
                    on_stage=lambda st: self.emit({"type": "message.stage", "chat_id": job.chat_id,
                                                   "id": job.msg_id, "stage": st}), hint=hint)
                meta["ctx"] = stats
                self.emit({"type": "message.stage", "chat_id": job.chat_id, "id": job.msg_id,
                           "stage": "generating"})
                payload = {"messages": messages, "stream": True,
                           "stream_options": {"include_usage": True},
                           "chat_template_kwargs": {"enable_thinking": thinking}}
                if tools:
                    payload["tools"] = [DRAW_TOOL]
                    payload["tool_choice"] = "auto"
                payload.update(settings)
                self.log(f"Генерация в чате «{chat['title'] or chat['id']}»: "
                         f"{stats['messages']} сообщ. дословно, {stats['dropped']} в хронике"
                         + (", размышления вкл." if thinking else "")
                         + (", может рисовать" if tools else "")
                         + (", продолжение" if job.continuing else ""))
                calls = {}   # index -> {"name", "args"} — вызовы инструментов из потока
                async with self.session.post(f"{self.llama_url}/v1/chat/completions",
                                             json=payload) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise GenError(_llama_error(resp.status, text))
                    finish = None
                    async for raw in resp.content:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        if obj.get("error"):
                            err = obj["error"]
                            raise GenError(err.get("message") if isinstance(err, dict) else str(err))
                        if obj.get("usage"):
                            usage = obj["usage"]
                        if obj.get("timings"):
                            meta["timings"] = obj["timings"]
                        for ch in obj.get("choices") or []:
                            d = ch.get("delta") or {}
                            job.content += d.get("content") or ""
                            job.reasoning += d.get("reasoning_content") or ""
                            for tc in d.get("tool_calls") or []:
                                c = calls.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                                fn = tc.get("function") or {}
                                c["name"] += fn.get("name") or ""
                                c["args"] += fn.get("arguments") or ""
                            if ch.get("finish_reason"):
                                finish = ch["finish_reason"]
                        now = time.monotonic()
                        if now - last_emit >= DELTA_INTERVAL:
                            flush_delta()
                        if now - last_save >= SAVE_INTERVAL:
                            self.store.save_progress(job.msg_id, job.content[:_held(job.content)],
                                                     job.reasoning)
                            last_save = now
                    if finish:
                        meta["finish_reason"] = finish
                        if finish == "length":
                            meta["truncated"] = True   # упёрлись в предел длины — можно «Продолжить»

                # ---- рисование по вызову инструмента (после текста, в той же задаче)
                call = None
                for c in calls.values():
                    try:
                        call = {"name": c["name"], "args": json.loads(c["args"] or "{}")}
                    except ValueError:
                        self.log(f"Вызов инструмента не разобран: {c['args'][:200]}")
                    break
                if TOOL_TAG in job.content:
                    if call is None:
                        call = _text_tool_call(job.content)
                    job.content = job.content[:job.content.index(TOOL_TAG)].rstrip()
                if call and not isinstance(call.get("args"), dict):
                    call = None   # модель прислала не объект с параметрами
                if scene["chars"]:   # кто из персонажей говорил — для аватаров в чате
                    if len(scene["chars"]) == 1 and scene["mode"] == "chat":
                        meta["speakers"] = [scene["chars"][0]["id"]]
                    else:
                        meta["speakers"] = cards.speaker_ids(job.content, scene["chars"])
                if call and tools and call["name"] == "draw_image" and \
                        str(call["args"].get("prompt", "")).strip():
                    await self._tool_draw(job, chat_settings, call["args"], meta, flush_delta)
        except asyncio.CancelledError:
            status = "cancelled"
        except (GenError, ImageError) as e:
            status, error = "error", str(e)
        except (ClientError, asyncio.TimeoutError, ConnectionError) as e:
            status, error = "error", f"Модель недоступна ({e.__class__.__name__})"
        except Exception as e:  # noqa: BLE001 — задача не должна падать молча
            status, error = "error", f"Внутренняя ошибка: {e}"
        finally:
            meta["seconds"] = round(time.monotonic() - started, 2)
            flush_delta()
            self.jobs.pop(job.msg_id, None)
            try:
                self.store.finish(job.msg_id, job.content, job.reasoning, status,
                                  error=error, usage=usage, meta=meta)
                msg = self.store.msg_dict(job.msg_id)
                self.emit({"type": "message.done", "chat_id": job.chat_id, "message": msg})
                self.emit({"type": "chat.updated", "chat": self.store.chat_dict(job.chat_id)})
            except LookupError:
                pass  # сообщение или чат удалены во время генерации
            if status == "done":
                self._after(job.chat_id, job.msg_id)
            if meta.get("images") or (status == "done" and self.memory.needs_facts(job.chat_id)):
                self.bg_pending[job.chat_id] = self.bg_pending.get(job.chat_id, False)
            asyncio.get_running_loop().call_soon(self._kick)
            tok = usage.get("completion_tokens")
            self.log(f"Ответ {job.msg_id}: {status}"
                     + (f", {tok} ток. за {meta['seconds']} с" if tok else "")
                     + (f" — {error}" if error else ""))
            self.emit({"type": "busy", "busy": self.busy})


def _llama_error(status: int, text: str) -> str:
    msg = text
    try:
        obj = json.loads(text)
        err = obj.get("error", obj)
        msg = err.get("message", text) if isinstance(err, dict) else str(err)
    except ValueError:
        pass
    if status == 503:
        return "Модель ещё загружается"
    if "context" in msg.lower() and ("exceed" in msg.lower() or "size" in msg.lower()):
        return "Не хватает контекста: история слишком длинная"
    return f"llama-server {status}: {msg[:300]}"
