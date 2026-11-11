"""Память чата и сборка контекста.

Контекст для ответа собирается слоями (по убыванию важности):
  1. системный промпт чата;
  2. память — долговременные факты (модель извлекает их в фоне, человек правит и закрепляет);
  3. хроника — краткое содержание старой части ветки, которая не помещается дословно;
  4. закреплённые сообщения, выпавшие из окна;
  5. последние сообщения дословно — сколько поместится в остаток.

Если из окна выпадают сообщения, ещё не попавшие в хронику, хроника дописывается
перед ответом (с запасом, чтобы не пересчитывать её на каждом шаге).
Хроника привязана к ветке: она годится, только если её граница лежит на текущем пути.
"""
import asyncio
import json
import time

from aiohttp import ClientError, ClientSession, ClientTimeout

import quest
import relations as rel
from cards import DATE_TEXT, MESSENGER_NOTE, art_style, look_block, scene_block
from images import data_url, image_tokens

MSG_OVERHEAD = 8          # токены разметки шаблона на одно сообщение
SAFETY = 64               # запас на неточность подсчёта
HISTORY_AFTER_SUMMARY = 0.6   # после сжатия история занимает не больше этой доли бюджета
MAX_FACTS = 80
FACTS_EVERY = 4           # извлекать факты после каждых N новых сообщений
SUMMARY_TOKENS = 1000
SEE_LAST_IMAGES = 2
LORE_SCAN = 6             # по скольким последним сообщениям ищутся ключи лорбука
LORE_CHARS = 6000         # предел текста лорбука в системном промпте       # сколько последних нарисованных картинок модель видит пикселями

# Рекомендуемые параметры для Qwen3 — подставляются, если в чате значение не задано.
# presence_penalty защищает квантованные модели от зацикливания (в том числе в размышлениях).
DEFAULTS_PLAIN = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0,
                  "presence_penalty": 1.0}
DEFAULTS_THINKING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                     "presence_penalty": 1.0}
# предел длины ответа по умолчанию (с размышлениями — вместе с ними)
MAX_TOKENS_PLAIN = 1536
MAX_TOKENS_THINKING = 4096


def effective_settings(settings: dict) -> dict:
    """Параметры запроса к llama-server: заданные в чате + рекомендуемые + предел длины."""
    thinking = bool(settings.get("thinking", False))
    out = dict(DEFAULTS_THINKING if thinking else DEFAULTS_PLAIN)
    out.update({k: v for k, v in settings.items() if k != "thinking" and v is not None})
    if not out.get("max_tokens"):
        out["max_tokens"] = MAX_TOKENS_THINKING if thinking else MAX_TOKENS_PLAIN
    out["thinking"] = thinking
    return out

ROLE_NAMES = {"user": "Пользователь", "assistant": "Ассистент"}

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "add": {"type": "array", "items": {"type": "string"}},
        "update": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["id", "text"]}},
        "remove": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["add", "update", "remove"],
}

FACTS_PROMPT = (
    "Ты ведёшь долговременную память длинного диалога. Из НОВЫХ СООБЩЕНИЙ выдели важное, "
    "что пригодится позже: имена и роли, отношения, внешность и характер персонажей, устройство "
    "мира, места, предметы, обещания, договорённости, решения, цели, предпочтения пользователя.\n"
    "Правила:\n"
    "- каждый факт — одна короткая самодостаточная фраза;\n"
    "- не повторяй то, что уже есть в ПАМЯТИ;\n"
    "- если новое уточняет или меняет факт из памяти — верни его в update с тем же id;\n"
    "- в remove — id фактов, которые стали неверны;\n"
    "- мелочи и сиюминутные реплики не нужны; если важного нет — пустые списки;\n"
    "- пиши на языке диалога.\n"
    "Ответ — только JSON."
)

SUMMARY_PROMPT = (
    "Ты пишешь хронику длинного диалога, чтобы его можно было продолжить, не видя исходных "
    "сообщений. Объедини ПРЕДЫДУЩУЮ ХРОНИКУ и НОВЫЕ СООБЩЕНИЯ в одну обновлённую хронику:\n"
    "- события по порядку, кто что сделал и сказал по существу;\n"
    "- имена, отношения, договорённости, важные детали и текущее положение дел;\n"
    "- сжато, без оценок и без пересказа мелочей; на языке диалога.\n"
    "Выведи только текст хроники целиком."
)


# какие поля карточки модель может предложить изменить
CHANGE_FIELDS = ("appearance", "appearance_tags", "personality", "background", "likes", "ties",
                 "scenario")
CHANGE_PROMPT = (
    "Проверь, случилось ли с персонажем в последних сообщениях что-то, что меняет его надолго: "
    "внешность (шрам, стрижка, новая одежда), обстоятельства (работа, жильё), взгляды, отношения "
    "с другими людьми. Если да — предложи правку карточки: name — имя персонажа, field — поле, "
    "value — новое значение поля ЦЕЛИКОМ (прежний текст с внесённым изменением; appearance_tags — "
    "по-английски), reason — одной фразой, что случилось. Мелочи, настроение и разовые события "
    "не считаются. Чаще всего изменений нет — тогда верни пустой список.")
CHANGE_SCHEMA = {"type": "object", "properties": {"changes": {"type": "array", "maxItems": 2, "items": {
    "type": "object", "properties": {
        "name": {"type": "string"}, "field": {"type": "string", "enum": list(CHANGE_FIELDS)},
        "value": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["name", "field", "value", "reason"]}}}, "required": ["changes"]}

DESCRIBE_PROMPT = (
    "Это изображение нарисовано ранее в нашем диалоге. Опиши его по-русски в 1–2 предложениях: "
    "кто или что изображено, внешность, одежда, обстановка, стиль. Только описание, без вступлений.")

# Общие правила хорошего промпта для модели изображений — и для инструмента, и для «улучшить».
PROMPT_RULES = (
    "Промпт для модели изображений пишется по-английски, подробно, 40–120 слов. Модель изображений "
    "не видит диалог, поэтому промпт должен быть самодостаточным: кто в кадре и как выглядит "
    "(возраст, волосы, глаза, телосложение, одежда), что делает, обстановка, время суток, освещение, "
    "ракурс и план, стиль (фото, аниме, масляная живопись…). Внешность персонажей бери из описания "
    "чата и фактов и повторяй её каждый раз одинаково, чтобы картинки были согласованы. "
    "Без русских слов, без пояснений вне промпта.")

PROMPT_PROMPT = (
    "Ты помогаешь составить промпт для нейросети, рисующей изображения. По запросу пользователя и "
    "контексту чата составь промпт. " + PROMPT_RULES +
    " В negative — коротко по-английски то, чего на картинке быть не должно (можно пусто).")

PROMPT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}, "negative": {"type": "string"}},
    "required": ["prompt", "negative"],
}


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n] + "…"


def _meta(row) -> dict:
    try:
        return json.loads(row["meta"] or "{}")
    except ValueError:
        return {}


def _images(row) -> list:
    """Картинки, которые модель видит как пиксели всегда: присланные пользователем."""
    if row["role"] != "user":
        return []
    return _meta(row).get("images") or []


def _generated(row) -> list:
    """Картинки, нарисованные в этом сообщении (по запросу или самой моделью)."""
    if row["role"] != "assistant" or row["status"] != "done":
        return []
    m = _meta(row)
    if m.get("kind") == "image" or m.get("drawn"):
        return m.get("images") or []
    return []


def last_state(rows) -> dict:
    """Последнее состояние квеста на пути ветки."""
    for r in reversed(rows):
        st = _meta(r).get("state")
        if st:
            return st
    return {}


def _seen(m: dict) -> str:
    """Что на картинке: описание, сделанное моделью по пикселям, или хотя бы подпись/промпт."""
    d = m.get("drawn") or m
    return (d.get("seen") or d.get("caption") or d.get("prompt") or "").strip()


def _text(row) -> str:
    """Текст сообщения для модели, с пометками о рисовании."""
    m = _meta(row)
    if m.get("kind") == "image":
        what = m.get("request") or m.get("prompt", "")
        if row["status"] != "done":
            return f"[Изображение по запросу «{what}» не получилось]"
        seen = m.get("seen")
        return f"[По запросу пользователя нарисовано изображение: {what}]" + \
            (f"\n[На нём: {seen}]" if seen else "")
    if m.get("kind") == "image_request":
        return f"[Запрос изображения] {row['content']}"
    d = m.get("drawn")
    if d and row["role"] == "assistant":
        note = f"[Ты нарисовал иллюстрацию: {_seen(m)}]" if m.get("images") else \
            "[Ты пытался нарисовать иллюстрацию, но не получилось]"
        return (row["content"].rstrip() + "\n\n" + note).strip()
    return row["content"]


def _transcript(rows, limit=2000) -> str:
    out = []
    for r in rows:
        n = len(_images(r))
        pics = f" [фото: {n}]" if n else ""
        out.append(f"{ROLE_NAMES.get(r['role'], r['role'])}: {_clip(_text(r), limit)}{pics}")
    return "\n\n".join(out)


def _content(row, extra_images=()):
    """Содержимое сообщения для llama-server: текст или текст + картинки.
    extra_images — нарисованные ранее картинки, которые модель должна увидеть (в сообщении пользователя)."""
    imgs = _images(row)
    if not imgs and not extra_images:
        return _text(row)
    parts = []
    for img in imgs:
        url = data_url(img.get("name", ""))
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url}})
    if extra_images:
        parts.append({"type": "text", "text": "(Ниже — изображения, нарисованные ранее в этом диалоге, "
                                              "чтобы ты видел, как они получились.)"})
        for img in extra_images:
            url = data_url(img.get("name", ""))
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
    text = _text(row)
    if text.strip():
        parts.append({"type": "text", "text": text})
    return parts or text


class Llama:
    """Служебные вызовы llama-server: подсчёт токенов и короткие ответы без потока."""

    def __init__(self, session: ClientSession, url: str):
        self.session = session
        self.url = url

    async def tokens(self, text: str) -> int:
        if not text:
            return 0
        try:
            async with self.session.post(f"{self.url}/tokenize", json={"content": text},
                                         timeout=ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return len((await r.json()).get("tokens", []))
        except (ClientError, asyncio.TimeoutError, ConnectionError, ValueError):
            pass
        return len(text) // 3 + 1   # грубая оценка, если сервер не ответил

    async def complete(self, messages, max_tokens: int, schema=None) -> str:
        payload = {
            "messages": messages, "stream": False, "max_tokens": max_tokens,
            "temperature": 0.3,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
        async with self.session.post(f"{self.url}/v1/chat/completions", json=payload,
                                     timeout=ClientTimeout(total=600)) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"llama-server {r.status}: {text[:200]}")
        obj = json.loads(text)
        return (obj["choices"][0]["message"].get("content") or "").strip()


class Memory:
    def __init__(self, store, llama: Llama, emit, log):
        self.store = store
        self.llama = llama
        self.emit = emit
        self.log = log
        self.vision = lambda: False   # загружена ли модель со зрением (mmproj)
        self.bg = None                # фоновая маленькая модель (Llama) — если запущена
        self.bg_ok = lambda: False

    def bg_llm(self):
        """Фоновая модель, если готова; иначе None — тогда фон делает большая модель."""
        return self.bg if self.bg and self.bg_ok() else None

    async def _count(self, row) -> int:
        if row["tokens"] is not None:
            return row["tokens"]
        n = await self.llama.tokens(_text(row)) + MSG_OVERHEAD
        n += sum(image_tokens(i) for i in _images(row))
        self.store.set_tokens(row["id"], n)
        return n

    # -------------------------------------------------------- сборка контекста
    async def build(self, msg_id: int, n_ctx: int, settings: dict, continuing: bool,
                    on_stage=None, hint: str = "") -> tuple:
        """→ (messages для llama-server, статистика раскладки контекста)."""
        msg = self.store.msg_row(msg_id)
        chat_id = msg["chat_id"]
        chat = self.store.chat_row(chat_id)
        until = msg_id if continuing else msg["parent_id"]
        hist = self.store.history_rows(chat_id, until)
        path_ids = self.store.path(chat_id, until)
        pos = {mid: i for i, mid in enumerate(path_ids)}

        reserve = int(effective_settings(settings)["max_tokens"])
        budget = n_ctx - reserve - SAFETY

        counts = [await self._count(r) for r in hist]
        # последние нарисованные картинки модель видит пикселями — резервируем под них место
        seen_imgs = []
        if self.vision():
            for r in reversed(hist):
                for img in _generated(r):
                    if len(seen_imgs) < SEE_LAST_IMAGES:
                        seen_imgs.append((r["id"], img))
        pix = sum(image_tokens(i) for _, i in seen_imgs)
        budget -= pix
        facts = self.store.facts(chat_id)
        chron = self.store.chronicle_for(chat_id, path_ids)

        prompt, volatile = self.chat_prompt(chat, hist, split=True)
        budget -= await self.llama.tokens(volatile) + 8 if volatile else 0
        for _attempt in range(3):
            system, parts = await self._system(prompt, facts, chron, [], hint)
            fixed = sum(parts.values())
            # окно: с конца, пока помещается; последнее сообщение — всегда
            start = len(hist)
            used = 0
            while start > 0 and (used + counts[start - 1] <= budget - fixed or start == len(hist)):
                start -= 1
                used += counts[start]
            dropped = hist[:start]
            chron_pos = -1 if not chron or chron["until_id"] == 0 else pos.get(chron["until_id"], -1)
            uncovered = [r for r in dropped if pos.get(r["id"], -1) > chron_pos]
            if not uncovered:
                break
            # дописать хронику: с запасом, чтобы история заняла не больше доли бюджета
            target = int((budget - fixed) * HISTORY_AFTER_SUMMARY)
            cut, tail = start, used
            while cut < len(hist) - 1 and tail > target:
                tail -= counts[cut]
                cut += 1
            chunk = [r for r in hist[:cut] if pos.get(r["id"], -1) > chron_pos]
            if not chunk:
                break
            if on_stage:
                on_stage("summarizing")
            self.log(f"Сжатие истории: {len(chunk)} сообщ. в хронику")
            text = await self._summarize(chron["text"] if chron else "", chunk)
            chron = self.store.save_chronicle(chat_id, chunk[-1]["id"], text)
            self.emit({"type": "memory.updated", "chat_id": chat_id})

        # закреплённые сообщения, выпавшие из окна
        pinned = [r for r in hist[:start] if r["pinned"]]
        system, parts = await self._system(prompt, facts, chron, pinned, hint)
        window = hist[start:]
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        # картинку показываем в ближайшем следующем сообщении пользователя внутри окна
        attach = {}
        win_ids = [r["id"] for r in window]
        for mid, img in reversed(seen_imgs):
            if mid not in win_ids:
                continue
            after = [r for r in window[win_ids.index(mid) + 1:] if r["role"] == "user"]
            if after:
                attach.setdefault(after[0]["id"], []).append(img)
        messages += [{"role": r["role"], "content": _content(r, attach.get(r["id"], ()))}
                     for r in window]
        if volatile:   # время, отношения, состояние — в последнее сообщение пользователя
            note = f"[Обстановка сейчас — для тебя, не цитируй]\n{volatile}\n[Конец обстановки]\n\n"
            for m in reversed(messages):
                if m["role"] == "user":
                    if isinstance(m["content"], list):
                        m["content"] = [{"type": "text", "text": note}] + m["content"]
                    else:
                        m["content"] = note + m["content"]
                    break
            else:
                messages.append({"role": "user", "content": note.strip()})
        stats = {
            "n_ctx": n_ctx, "reserve": reserve,
            "system": parts["system"] + parts["tools"], "memory": parts["memory"],
            "chronicle": parts["chronicle"], "pinned": parts["pinned"],
            "history": sum(counts[start:]) + sum(image_tokens(i) for v in attach.values() for i in v),
            "messages": len(window), "dropped": start,
        }
        return messages, stats

    # ------------------------------------------------- сцена чата
    def scene(self, chat) -> dict:
        """Кто и что в чате: персонажи, персона, мир, режим."""
        st = json.loads(chat["settings"] or "{}")
        ids = st.get("character_ids") or ([st["character_id"]] if st.get("character_id") else [])
        chars = [c for c in (self.store.card_or_none(i) for i in ids) if c]
        return {"chars": chars, "persona": self.store.card_or_none(st.get("persona_id")),
                "world": self.store.card_or_none(st.get("world_id")),
                "mode": st.get("mode") or "chat", "style": st.get("chat_style") or "roleplay",
                "initiative": st.get("initiative", True), "date_of": st.get("date_of")}

    def user_name(self, sc: dict) -> str:
        return (sc["persona"] or {}).get("data", {}).get("name") or "собеседник"

    def chat_prompt(self, chat, hist=None, split: bool = False):
        """Промпт сцены. Постоянная часть (режим, мир, роли, лорбук, промпт чата) идёт в системное
        сообщение; меняющаяся каждый ход (время, отношения, состояние квеста) — отдельно, её build
        кладёт в последнее сообщение пользователя: так начало контекста не меняется и llama-server
        не пересчитывает его заново. split=False — всё одной строкой."""
        sc = self.scene(chat)
        pid = sc["persona"]["id"] if sc["persona"] else 0
        rel_on = sc["mode"] == "chat" or bool(sc["date_of"])
        rels = {c["id"]: dict(rel.new(), **self.store.relation(c["id"], pid))
                for c in sc["chars"]} if rel_on else {}
        user = self.user_name(sc)
        stable = [scene_block(sc["chars"], sc["persona"], sc["world"], sc["mode"], sc["style"],
                              {cid: r["trust"] for cid, r in rels.items()})]
        if sc["date_of"] and sc["chars"]:
            stable.append(DATE_TEXT.format(char=sc["chars"][0]["data"].get("name") or "персонаж",
                                           user=user))
        if sc["world"] and hist is not None:
            stable.append(self.lore_text(sc["world"]["id"], hist))
        stable.append(chat["system_prompt"].strip())
        volatile = []
        others = []
        if rels:   # с кем ещё общается пользователь — персонаж может об этом знать
            here = {c["id"] for c in sc["chars"]}
            for cid, data in self.store.relations_of(pid):
                if cid not in here and data.get("interactions", 0) >= 3:
                    oc = self.store.card_or_none(cid)
                    if oc:
                        others.append((oc["name"], rel.status(data)))
        for c in sc["chars"]:
            if c["id"] in rels:
                volatile.append(rel.prompt_block(c["data"].get("name") or "персонаж", user,
                                                 rels[c["id"]]))
        if others:
            volatile.append(rel.others_block(user, others[:6]))
        if sc["mode"] == "chat" and sc["chars"] and sc["style"] == "messenger":
            volatile.append(MESSENGER_NOTE)
        if sc["mode"] == "chat":   # в квесте и истории своё время — реальное только мешает
            gap = None
            if hist:
                users = [i for i, r in enumerate(hist) if r["role"] == "user"]
                if users and users[-1] > 0:
                    gap = hist[users[-1]]["created"] - hist[users[-1] - 1]["created"]
            volatile.append(rel.time_block(gap=gap, user=user))
        if sc["mode"] == "story":   # известные места — чтобы названия (и фоны) не плодились
            places = [v.get("place") for v in self.store.vn_backgrounds(chat["id"]).values()
                      if isinstance(v, dict) and v.get("place")]
            if places:
                volatile.append("Места этой истории, уже показанные: " +
                                "; ".join(f"«{x}»" for x in places[-12:]) +
                                ". Если сцена в одном из них — пиши название слово в слово так же.")
        if sc["mode"] in ("quest", "gm") and hist is not None:
            st = last_state(hist)
            if st:
                coins = self.store.wallet(pid)
                volatile.append("## Состояние игры (актуальное)\n" + quest.text(st) +
                                f"\n- Монеты: {coins}")
        a = "\n\n".join(x for x in stable if x)
        b = "\n\n".join(x for x in volatile if x)
        if split:
            return a, b
        return "\n\n".join(x for x in (a, b) if x)

    def style(self, chat) -> str:
        """Единый стиль картинок чата ('' — в обычном чате без персонажей и мира)."""
        sc = self.scene(chat)
        return art_style(sc["chars"], sc["world"]) if (sc["chars"] or sc["world"]) else ""

    def look(self, chat) -> str:
        sc = self.scene(chat)
        return look_block(sc["chars"], sc["persona"], sc["world"])

    def lore_text(self, world_id: int, hist) -> str:
        """Записи лорбука, о которых сейчас идёт речь (ключи в последних сообщениях) + «всегда»."""
        recent = " ".join(r["content"] for r in hist[-LORE_SCAN:]).lower()
        picked, size = [], 0
        for e in self.store.lore(world_id):
            keys = [k.strip().lower() for k in e["keys"].split(",") if len(k.strip()) >= 3]
            if e["always"] or any(k in recent for k in keys):
                line = f"- {e['title']}: {e['content']}" if e["title"] else f"- {e['content']}"
                if size + len(line) > LORE_CHARS:
                    break
                picked.append(line)
                size += len(line)
        return ("### Справка о мире (лорбук)\n" + "\n".join(picked)) if picked else ""

    async def _system(self, prompt: str, facts: list, chron, pinned: list, hint: str = "") -> tuple:
        blocks = {"system": prompt.strip(), "memory": "", "chronicle": "", "pinned": "",
                  "tools": hint.strip()}
        if facts:
            blocks["memory"] = "## Память — важные факты, держи их в уме\n" + \
                "\n".join(f"- {f['text']}" for f in facts)
        if chron and chron["text"].strip():
            blocks["chronicle"] = "## Хроника — что было раньше в этом диалоге\n" + chron["text"].strip()
        if pinned:
            blocks["pinned"] = "## Закреплённые сообщения из начала диалога\n" + _transcript(pinned, 4000)
        parts = {k: (await self.llama.tokens(v) + 4 if v else 0) for k, v in blocks.items()}
        text = "\n\n".join(v for v in blocks.values() if v)
        return text, parts

    async def _summarize(self, previous: str, rows) -> str:
        user = (f"ПРЕДЫДУЩАЯ ХРОНИКА:\n{previous.strip() or '(пусто)'}\n\n"
                f"НОВЫЕ СООБЩЕНИЯ:\n{_transcript(rows, 3000)}")
        try:
            text = await self.llama.complete(
                [{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": user}],
                max_tokens=SUMMARY_TOKENS)
        except (ClientError, asyncio.TimeoutError, ConnectionError, RuntimeError, ValueError,
                KeyError) as e:
            self.log(f"Хроника не обновлена: {e}")
            text = ""
        if not text:
            # без модели — хотя бы сохранить суть механически, чтобы не потерять сообщения совсем
            text = (previous.strip() + "\n\n" + _transcript(rows, 300)).strip()
        return text

    # ------------------------------------------------------------- факты
    def needs_facts(self, chat_id: int) -> bool:
        try:
            since = self.store.memory_until(chat_id)
            rows = self.store.history_rows(chat_id, self.store.chat_row(chat_id)["head_id"])
        except LookupError:
            return False
        new = [r for r in rows if r["id"] > since and r["status"] in ("done", "cancelled")]
        return len(new) >= FACTS_EVERY

    async def extract_facts(self, chat_id: int, force: bool = False, llm=None) -> bool:
        since = self.store.memory_until(chat_id)
        rows = self.store.history_rows(chat_id, self.store.chat_row(chat_id)["head_id"])
        new = [r for r in rows if r["id"] > since and r["status"] in ("done", "cancelled")]
        if not new or (len(new) < FACTS_EVERY and not force):
            return False
        new = new[-12:]
        facts = self.store.facts(chat_id)
        mem = "\n".join(f"[{f['id']}] {f['text']}" for f in facts) or "(пусто)"
        user = f"ПАМЯТЬ:\n{mem}\n\nНОВЫЕ СООБЩЕНИЯ:\n{_transcript(new, 1500)}"
        self.log(f"Обновление памяти чата {chat_id}: {len(new)} новых сообщ.")
        text = await (llm or self.llama).complete(
            [{"role": "system", "content": FACTS_PROMPT}, {"role": "user", "content": user}],
            max_tokens=700, schema=FACTS_SCHEMA)
        try:
            data = json.loads(text)
        except ValueError:
            self.log("Память: модель вернула не JSON — пропуск")
            self.store.set_memory_until(chat_id, new[-1]["id"])
            return False
        by_id = {f["id"]: f for f in facts}
        editable = {fid for fid, f in by_id.items() if f["auto"] and not f["pinned"]}
        known = {f["text"].lower() for f in facts}
        changed = 0
        for fid in data.get("remove") or []:
            if isinstance(fid, int) and fid in editable:
                self.store.delete_fact(fid)
                changed += 1
        for u in data.get("update") or []:
            fid, t = u.get("id"), str(u.get("text", "")).strip()
            if fid in editable and t and t.lower() != by_id[fid]["text"].lower():
                self.store.update_fact(fid, text=t, by_model=True)
                changed += 1
        count = len(self.store.facts(chat_id))
        for t in data.get("add") or []:
            t = " ".join(str(t).split())
            if t and t.lower() not in known and count < MAX_FACTS:
                self.store.add_fact(chat_id, t, auto=True)
                known.add(t.lower())
                count += 1
                changed += 1
        self.store.set_memory_until(chat_id, new[-1]["id"])
        self.log(f"Память чата {chat_id}: изменений {changed}, фактов {count}")
        if changed:
            self.emit({"type": "memory.updated", "chat_id": chat_id})
        try:
            await self.propose_changes(chat_id, new, llm or self.llama)
        except Exception as e:  # noqa: BLE001 — необязательная часть
            self.log(f"Изменения персонажей не проверены: {e}")
        return changed > 0

    async def propose_changes(self, chat_id: int, rows, llm) -> int:
        """Персонаж меняется: если в последних сообщениях с ним случилось что-то надолго
        (шрам, новая работа, перемена во взглядах), предложить правку карточки. Решает человек."""
        sc = self.scene(self.store.chat_row(chat_id))
        if not sc["chars"] or sc["mode"] == "gm":
            return 0
        cards_text = "\n\n".join(
            f"ПЕРСОНАЖ {c['data'].get('name')}:\n" + "\n".join(
                f"{k}: {c['data'].get(k, '')[:600]}" for k in CHANGE_FIELDS if c["data"].get(k))
            for c in sc["chars"])
        out = await llm.complete(
            [{"role": "system", "content": CHANGE_PROMPT},
             {"role": "user", "content": f"{cards_text}\n\nПОСЛЕДНИЕ СООБЩЕНИЯ:\n{_transcript(rows, 1200)}"}],
            max_tokens=700, schema=CHANGE_SCHEMA)
        by_name = {(c["data"].get("name") or "").strip().lower(): c for c in sc["chars"]}
        pending = self.store.get_setting("proposals", []) or []
        added = 0
        for ch in (json.loads(out).get("changes") or [])[:2]:
            c = by_name.get(str(ch.get("name", "")).strip().lower())
            field, value = ch.get("field"), " ".join(str(ch.get("value") or "").split())
            if not c or field not in CHANGE_FIELDS or not value or value == c["data"].get(field):
                continue
            if any(p["card_id"] == c["id"] and p["field"] == field for p in pending):
                continue   # по этому полю уже есть неразобранное предложение
            prop = {"id": int(time.time() * 1000) + added, "card_id": c["id"], "name": c["name"],
                    "field": field, "value": value[:3000], "chat_id": chat_id,
                    "reason": " ".join(str(ch.get("reason") or "").split())[:200]}
            pending.append(prop)
            added += 1
            self.emit({"type": "card.proposal", "proposal": prop})
            self.log(f"Предложение изменить карточку «{c['name']}»: {prop['reason']}")
        if added:
            self.store.set_setting("proposals", pending[-20:])
        return added

    # ------------------------------------------------------ картинки и промпты
    async def describe_images(self, chat_id: int, limit: int = 4) -> int:
        """Подписать нарисованные картинки по пикселям: так модель «помнит» старые иллюстрации,
        которые уже не показываются ей целиком."""
        if not self.vision():
            return 0
        rows = self.store.history_rows(chat_id, self.store.chat_row(chat_id)["head_id"])
        todo = [r for r in rows if _generated(r) and not (
            (_meta(r).get("drawn") or _meta(r)).get("seen"))][-limit:]
        done = 0
        for r in todo:
            m = _meta(r)
            parts = [{"type": "image_url", "image_url": {"url": data_url(i.get("name", ""))}}
                     for i in _generated(r) if data_url(i.get("name", ""))]
            if not parts:
                continue
            parts.append({"type": "text", "text": DESCRIBE_PROMPT})
            text = await self.llama.complete([{"role": "user", "content": parts}], max_tokens=200)
            text = " ".join(text.split())
            if not text:
                continue
            if m.get("drawn"):
                d = dict(m["drawn"], seen=text)
                self.store.merge_meta(r["id"], {"drawn": d})
            else:
                self.store.merge_meta(r["id"], {"seen": text})
            self.store.set_tokens(r["id"], None)
            done += 1
            self.emit({"type": "message.updated", "chat_id": chat_id,
                       "message": self.store.msg_dict(r["id"])})
        if done:
            self.log(f"Подписано картинок в чате {chat_id}: {done}")
        return done

    async def image_prompt(self, chat_id, text: str) -> dict:
        """Запрос человека (по-русски, коротко) → подробный английский промпт по контексту чата."""
        ctx = []
        if chat_id:
            try:
                chat = self.store.chat_row(chat_id)
                prompt = self.chat_prompt(chat)
                if prompt:
                    ctx.append("ОПИСАНИЕ ЧАТА / ПЕРСОНАЖЕЙ:\n" + _clip(prompt, 4000))
                look = self.look(chat)
                if look:
                    ctx.append(look)
                facts = self.store.facts(chat_id)
                if facts:
                    ctx.append("ФАКТЫ:\n" + "\n".join(f"- {f['text']}" for f in facts[:40]))
                rows = self.store.history_rows(chat_id, chat["head_id"])[-6:]
                if rows:
                    ctx.append("ПОСЛЕДНИЕ СООБЩЕНИЯ:\n" + _transcript(rows, 800))
            except LookupError:
                pass
        user = ("\n\n".join(ctx) + "\n\n" if ctx else "") + f"ЗАПРОС НА РИСУНОК:\n{text.strip()}"
        out = await self.llama.complete(
            [{"role": "system", "content": PROMPT_PROMPT}, {"role": "user", "content": user}],
            max_tokens=500, schema=PROMPT_SCHEMA)
        data = json.loads(out)
        prompt = " ".join(str(data.get("prompt", "")).split())
        if not prompt:
            raise ValueError("пустой промпт")
        return {"prompt": prompt, "negative": " ".join(str(data.get("negative", "")).split())}
