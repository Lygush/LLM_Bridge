"""Карточки персонажей и персон: поля, заполнение моделью, сборка в системный промпт.

Человек пишет как удобно («девушка-эльф, ворчливая, любит книги…»), модель раскладывает
это по полям и додумывает недостающее. Поле appearance_tags — английские теги внешности:
из них собираются промпты рисования, чтобы персонаж выглядел одинаково на всех картинках.
"""
import json
import re

import vn

KINDS = ("character", "persona", "world")
MODES = ("chat", "quest", "story", "gm")   # gm — квест, где ведущий пользователь
CHAT_STYLES = ("messenger", "roleplay")    # переписка на расстоянии / рядом, с действиями

# (ключ, подпись, подсказка для модели, многострочное)
FIELDS = {
    "character": [
        ("name", "Имя", "имя персонажа", False),
        ("short", "Кратко", "одна строка: кто это (для списка)", False),
        ("appearance", "Внешность", "внешность по-русски: возраст, рост, телосложение, волосы, "
                                    "глаза, лицо, одежда, особые приметы", True),
        ("appearance_tags", "Теги внешности (англ.)",
         "English comma-separated tags for an image model: gender, age, hair color and style, "
         "eye color, body type, typical clothing, distinctive features. No names, no style words", True),
        ("art_style", "Стиль картинок (англ.)",
         "English visual style tags for ALL images of this character, e.g. «photorealistic, "
         "natural skin texture, 35mm photo» or «anime illustration, cel shading» or «oil painting». "
         "If the user did not ask for a style — photorealistic", False),
        ("personality", "Характер", "характер, привычки, ценности, что любит и не любит", True),
        ("background", "Предыстория", "прошлое персонажа, кем работает, где живёт, отношения", True),
        ("speech", "Манера речи", "как говорит: тон, словечки, 2–3 примера реплик", True),
        ("scenario", "Сценарий", "обстановка и ситуация, с которой начинается общение", True),
        ("likes", "Вкусы", "что любит и что терпеть не может: еда, вещи, занятия, подарки, "
                           "темы разговора", True),
        ("schedule", "Распорядок дня", "обычный день по часам: когда встаёт, работает или учится, "
                                       "свободное время, когда спит; выходные", True),
        ("secret", "Тайна", "то, что персонаж скрывает и откроет только тому, кому очень доверяет",
         True),
        ("ties", "Знакомства", "с кем из других людей знаком (друзья, соперники, бывшие) и как к ним "
                               "относится; ревнив ли", True),
        ("greeting", "Первое сообщение", "первое сообщение персонажа в чате: от его лица, с "
                                         "действиями *курсивом*, 2–5 предложений, завязка сцены", True),
    ],
    "persona": [
        ("name", "Имя", "как персонажи обращаются к пользователю", False),
        ("short", "Кратко", "одна строка: кто это", False),
        ("appearance", "Внешность", "внешность по-русски", True),
        ("appearance_tags", "Теги внешности (англ.)",
         "English comma-separated tags for an image model: gender, age, hair, eyes, body, "
         "clothing, distinctive features", True),
        ("about", "О себе", "кто это, чем занимается, что важно знать собеседнику", True),
    ],
    "world": [
        ("name", "Название", "название мира или места действия", False),
        ("short", "Кратко", "одна строка: что за мир", False),
        ("description", "Описание", "сеттинг: эпоха, география, общество, магия или технологии, "
                                    "главные силы и конфликты — то, что верно всегда", True),
        ("tone", "Тон и жанр", "жанр, настроение, правила повествования (насколько опасно, "
                               "реалистично, есть ли юмор)", True),
        ("style_tags", "Стиль картинок (англ.)",
         "English comma-separated visual style tags for an image model for this world: medium, "
         "palette, mood, era (e.g. dark fantasy, oil painting, muted colors)", True),
    ],
}

# Записи лорбука: попадают в контекст, только когда о них заходит речь (по ключам).
LORE_SCHEMA_ITEM = {"type": "object", "properties": {
    "title": {"type": "string"}, "keys": {"type": "string"}, "content": {"type": "string"}},
    "required": ["title", "keys", "content"]}
LORE_RULES = ("Записи лорбука: места, фракции, персонажи второго плана, предметы, термины, "
              "обычаи. title — название; keys — 2–5 ключей через запятую: короткие основы слов "
              "без окончаний, по которым запись узнаётся в тексте (например «гильди, вор» или "
              "«Карн, мост»); content — 1–4 предложения фактов.")

KIND_TEXT = {"character": "персонажа для ролевого чата", "persona": "персону — то, каким "
             "пользователь предстаёт в ролевых чатах", "world": "мир для ролевых игр и историй"}


def fields_info() -> dict:
    return {k: [{"key": f[0], "label": f[1], "multiline": f[3]} for f in v] for k, v in FIELDS.items()}


def clean_data(kind: str, data: dict) -> dict:
    keys = [f[0] for f in FIELDS[kind]]
    return {k: str(data.get(k) or "").strip()[:6000] for k in keys}


def fill_schema(kind: str) -> dict:
    keys = [f[0] for f in FIELDS[kind]]
    props = {k: {"type": "string"} for k in keys}
    if kind == "world":
        props["lore"] = {"type": "array", "items": LORE_SCHEMA_ITEM, "minItems": 4, "maxItems": 14}
        keys = keys + ["lore"]
    return {"type": "object", "properties": props, "required": keys}


def fill_prompt(kind: str) -> str:
    lines = "\n".join(f"- {k}: {hint}" for k, _, hint, _ in FIELDS[kind])
    extra = ("\n- lore: " + LORE_RULES + " Сделай 6–12 записей.") if kind == "world" else ""
    return (f"Пользователь своими словами, возможно сумбурно, описал {KIND_TEXT[kind]}. Заполни "
            "карточку по полям. Всё, что пользователь сказал, сохрани; недостающее додумай так, "
            "чтобы получился цельный, живой образ, без противоречий. Пиши по-русски, кроме "
            f"полей с английскими тегами. Поля:\n{lines}{extra}")


LORE_ADD_SCHEMA = {"type": "object", "properties": {
    "lore": {"type": "array", "items": LORE_SCHEMA_ITEM, "minItems": 1, "maxItems": 10}},
    "required": ["lore"]}


def lore_add_prompt() -> str:
    return ("Дополни лорбук мира новыми записями по просьбе пользователя, не повторяя "
            "существующие и не противореча им. " + LORE_RULES)


def clean_lore(items) -> list:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        content = str(it.get("content") or "").strip()
        if content:
            out.append({"title": str(it.get("title") or "").strip()[:120],
                        "keys": str(it.get("keys") or "").strip()[:300],
                        "content": content[:4000]})
    return out


REWRITE_SCHEMA = {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}


def rewrite_prompt(kind: str, key: str) -> str:
    hint = next((f[2] for f in FIELDS[kind] if f[0] == key), key)
    return (f"Перепиши одно поле карточки ({KIND_TEXT[kind]}): «{key}» — {hint}. Учитывай остальные "
            "поля, чтобы не было противоречий. Если есть пожелание пользователя — выполни его, "
            "иначе предложи свежий, более выразительный вариант. В ответе только новое значение поля.")


def card_text(card: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in card["data"].items() if v)


def _sub(text: str, char: str, user: str) -> str:
    return text.replace("{{char}}", char).replace("{{user}}", user)


MODE_TEXT = {
    "chat": None,
    "quest": (
        "## Режим: текстовый квест\nТы — ведущий игры (мастер). Описывай мир, неигровых персонажей "
        "и последствия действий игрока живо и конкретно, во втором лице («ты видишь…»). Мир живёт "
        "по своим правилам: действия могут провалиться, ресурсы кончаются, раны мешают. Не решай "
        "за игрока и не говори за него. Держи темп: 1–4 абзаца за ход, в конце — ситуация, "
        "требующая решения. Учитывай «Состояние игры» и не противоречь ему."),
    "story": (
        "## Режим: совместное повествование\nВы с пользователем вместе пишете историю. Ты — "
        "соавтор: пиши художественной прозой (по умолчанию от третьего лица, в прошедшем времени), "
        "с диалогами, деталями и ритмом. Сообщения пользователя — это его фрагменты текста, "
        "которые надо органично продолжить, либо указания в квадратных скобках — их выполняй, "
        "не обсуждая. Не подводи итогов и не заканчивай историю без просьбы." + vn.FORMAT),
}

CHAR_SECTIONS = (("appearance", "Внешность"), ("personality", "Характер"),
                 ("background", "Предыстория"), ("speech", "Манера речи"), ("likes", "Вкусы"),
                 ("schedule", "Распорядок дня"), ("ties", "Знакомства"), ("scenario", "Сценарий"))

MESSENGER = (
    "### Как писать — переписка в мессенджере\nВы не рядом: вы переписываетесь в мессенджере "
    "с телефонов. Пиши ТОЛЬКО то, что человек реально набрал бы в чате:\n"
    "- коротко и разговорно: обычно 1–2 предложения;\n"
    "- НИКАКИХ описаний действий, жестов и мыслей: ни в *звёздочках*, ни в (скобках), ни от "
    "третьего лица — ты не можешь «пожать руку» или «улыбнуться» через телефон; вместо этого "
    "эмодзи или слова («ахах», «ну привет 😏»), если это в характере;\n"
    "- обычно это ОДНО сообщение. Второе (через пустую строку) — только если есть что добавить "
    "к первому: новая мысль, вопрос, уточнение. Второе сообщение продолжает твою же речь: не "
    "отвечай в нём на собственное первое, не спорь с собой, не повторяй его другими словами. "
    "Больше трёх не пиши никогда;\n"
    "- отвечай на последнее сообщение собеседника. Не возвращайся к теме, которую уже обсудили, "
    "и не топчись на одной мысли: если тема исчерпана — меняй её, спрашивай о другом, "
    "рассказывай своё;\n"
    "- без кавычек вокруг реплик, без имени перед репликой, без пересказа чужих слов.\n"
    "Фото присылаешь как снимок с телефона.")

# напоминание перед каждым ответом — модель легко сползает в «ролевой» стиль с действиями
MESSENGER_NOTE = ("Формат ответа: переписка в мессенджере — коротко, без действий в звёздочках "
                  "и скобках. Обычно одно сообщение; второе через пустую строку — только с новой "
                  "мыслью, не ответ самому себе и не повтор. Не зацикливайся на одной теме.")

ROLEPLAY = ("Пиши живо: речь персонажа, его действия и ощущения (действия — *курсивом*). ")

DEFAULT_STYLE = "photorealistic, natural lighting, realistic skin texture, high detail photo"


def _char_sections(d: dict, name: str, user: str, level: str) -> list:
    return [f"{level} {title}\n{_sub(d[key], name, user)}" for key, title in CHAR_SECTIONS if d.get(key)]


GM_TEXT = (
    "## Режим: квест, ведущий — пользователь\nПользователь — ведущий (мастер) игры: он описывает "
    "мир, ситуации и исход действий. Ты играешь за героев: говоришь и действуешь от их лица, "
    "заявляешь намерения и попытки («пробую вскрыть замок»), задаёшь ведущему вопросы о мире. "
    "Не решай сам, чем закончилось действие, и не описывай мир за ведущего. Каждый герой "
    "действует по своему характеру; герои могут спорить между собой. Реплику героя начинай с его "
    "имени жирным: «**Имя:** …».\nЕсли сообщение ведущего начинается с «[Помощник ведущего]» — "
    "ответь вне игры, как помощник мастера: предложи идеи, описание места, реплики неигровых "
    "персонажей, осложнения, награды — коротко и по делу.")


def scene_block(chars: list, persona, world, mode: str = "chat", style: str = "roleplay",
                secrets: dict = None) -> str:
    """Системный промпт сцены: режим, мир, кого играет модель, кто собеседник.
    secrets — {card_id: доверие}: тайна персонажа выдаётся с условием раскрытия."""
    out = []
    secrets = secrets or {}
    if mode == "gm":
        out.append(GM_TEXT)
    user = (persona or {}).get("data", {}).get("name") or "собеседник"
    chars = [c for c in chars if c]
    if MODE_TEXT.get(mode):
        out.append(MODE_TEXT[mode])
    if world:
        d = world["data"]
        w = [f"## Мир: {d.get('name') or 'без названия'}"]
        if d.get("description"):
            w.append(d["description"])
        if d.get("tone"):
            w.append("Тон и жанр: " + d["tone"])
        out.append("\n".join(w))
    if mode == "chat" and len(chars) == 1:
        d = chars[0]["data"]
        name = d.get("name") or "персонаж"
        out.append(f"## Роль\nТы — {name}. Веди диалог от лица {name} и оставайся в роли; не "
                   "говори, что ты ИИ или языковая модель. "
                   + ("" if style == "messenger" else ROLEPLAY) +
                   "Не пиши реплики и поступки за собеседника.")
        out += _char_sections(d, name, user, "###")
        out += _secret(chars[0], secrets)
        if style == "messenger":
            out.append(MESSENGER)
    elif chars:
        names = ", ".join(c["data"].get("name") or "?" for c in chars)
        if mode == "chat":
            out.append(f"## Роли\nТы ведёшь нескольких персонажей: {names}. Каждую реплику или "
                       "действие персонажа начинай с новой строки с его имени жирным, например "
                       f"«**{chars[0]['data'].get('name') or 'Имя'}:** …»"
                       + ("" if style == "messenger" else "; действия — *курсивом*") + ". "
                       "Отвечают только те, кому уместно, у каждого свой характер и манера речи. "
                       "Оставайся в ролях, не пиши реплики и поступки за собеседника.")
        elif mode == "gm":
            out.append(f"## Твои герои: {names}")
        else:
            title = "Неигровые персонажи" if mode == "quest" else "Герои истории"
            out.append(f"## {title}: {names}\nКогда персонаж говорит, начинай реплику с его имени "
                       "жирным: «**Имя:** …».")
        for c in chars:
            d = c["data"]
            name = d.get("name") or "?"
            out.append(f"### {name}" + (f" — {d['short']}" if d.get("short") else ""))
            out += _char_sections(d, name, user, "####")
            if mode == "chat":
                out += _secret(c, secrets)
        if mode == "chat" and style == "messenger":
            out.append(MESSENGER + "\nЭто общий чат: реплику каждого персонажа начинай с его имени "
                       "жирным, одно сообщение на персонажа.")
    if persona and mode != "gm":
        d = persona["data"]
        bits = [f"{'Игрока' if mode == 'quest' else 'Собеседника'} зовут {d.get('name') or user}."]
        if d.get("about"):
            bits.append(d["about"])
        if d.get("appearance"):
            bits.append("Внешность: " + d["appearance"])
        out.append(("## Игрок\n" if mode == "quest" else "## Собеседник\n") + " ".join(bits))
    young = [c["data"].get("name") or "?" for c in chars + ([persona] if persona else [])
             if is_minor(c)]
    if young:
        out.append(MINOR_NOTE.format(names=", ".join(young)))
    return "\n\n".join(out)


# Возраст из карточки («17 лет», «10 years old»). Для несовершеннолетних персонажей романтика
# выключена: свидание недоступно, в промпте — прямое ограничение для текста и картинок.
_AGE = re.compile(r"(?<![\d.,])(\d{1,2})\s*[- ]?\s*(?:years?[- ]old|y\.?o\b|лет(?!\s+назад)\b|"
                  r"год(?:а|ик|ика)?(?!\s+назад)\b)", re.I)
MINOR_NOTE = (
    "## Ограничение\nНесовершеннолетние в этой сцене: {names}. С ними и о них — никакой романтики, "
    "флирта и сексуального подтекста, ни в тексте, ни в картинках; одежда и позы на картинках "
    "обычные, повседневные. Отношения — дружеские, семейные, приятельские. Если разговор уводят "
    "в эту сторону, персонаж не поддерживает тему и сцена идёт дальше по-другому.")


def age(card) -> int:
    """Возраст персонажа из карточки или -1, если не указан."""
    d = (card or {}).get("data") or {}
    found = []
    for k in ("short", "appearance_tags", "appearance", "about"):
        found += [int(x) for x in _AGE.findall(str(d.get(k) or ""))]
    return min(found) if found else -1


def is_minor(card) -> bool:
    return 0 <= age(card) < 18


DATE_TEXT = (
    "\n### Свидание\nЭто свидание или вечер {char} и {user} — короткая история о нём. Описывай "
    "место, атмосферу и {char}: реплики, жесты, реакции — по характеру, вкусам и отношениям. "
    "Реплики и поступки {user} пишет сам; ты их не придумываешь. Иногда давай повод выбрать: "
    "куда пойти, что сказать, что заказать.")


def _secret(card: dict, secrets: dict) -> list:
    d = card["data"]
    if not d.get("secret"):
        return []
    return [f"#### Тайна {d.get('name') or ''} (не раскрывай и не намекай прямо, пока доверие "
            f"к собеседнику ниже 60 — см. «Отношения»)\n{d['secret']}"]


def look_block(chars: list, persona=None, world=None) -> str:
    """Внешность для промптов рисования — английскими тегами, одинаково на каждой картинке."""
    lines = [f"- {c['data'].get('name') or '?'}: {c['data']['appearance_tags']}"
             for c in [*chars, persona] if c and c["data"].get("appearance_tags")]
    out = []
    if lines:
        out.append("Внешность для промптов рисования (используй эти теги дословно, когда персонаж "
                   "в кадре):\n" + "\n".join(lines))
    if chars or world:   # в обычном чате без персонажей стиль не навязываем
        st = art_style(chars, world)
        out.append("Стиль ВСЕХ картинок этого чата (добавляй в конец каждого промпта дословно): " + st)
    return "\n".join(out)


def art_style(chars: list, world=None, card=None) -> str:
    """Единый стиль картинок: мир → карточка → первый персонаж сцены → фотореализм.
    Один стиль на портрет, эмоции, селфи и иллюстрации — иначе портрет мультяшный, а чат в реализме."""
    if world and world["data"].get("style_tags"):
        return world["data"]["style_tags"].strip()
    for c in [card, *chars]:
        if c and c["data"].get("art_style"):
            return c["data"]["art_style"].strip()
    return DEFAULT_STYLE


def with_style(prompt: str, style: str) -> str:
    """Дописать стиль в промпт, если модель его не вставила сама."""
    head = style.split(",")[0].strip().lower()
    if not style or (head and head in prompt.lower()):
        return prompt
    return prompt.rstrip(" ,.") + ", " + style


def speaker_ids(text: str, chars: list) -> list:
    """Кто из персонажей говорит в ответе (по «**Имя:**» в начале строк)."""
    found = []
    for c in chars:
        n = (c["data"].get("name") or "").strip()
        if n and (f"**{n}:**" in text or f"**{n}**:" in text or text.startswith(f"{n}:")
                  or f"\n{n}:" in text):
            found.append(c["id"])
    return found


def portrait_prompt(card: dict) -> str:
    d = card["data"]
    tags = d.get("appearance_tags") or d.get("appearance") or d.get("name", "")
    return (f"portrait of a single character, {tags}, upper body, looking at viewer, expressive "
            f"face, detailed eyes, soft lighting, simple blurred background, {art_style([], card=card)}")


def greeting(card: dict, persona) -> str:
    d = card["data"]
    user = (persona or {}).get("data", {}).get("name") or "ты"
    return _sub(d.get("greeting", ""), d.get("name", ""), user).strip()


def parse_fill(kind: str, text: str) -> tuple:
    """→ (поля карточки, записи лорбука)."""
    obj = json.loads(text)
    return clean_data(kind, obj), clean_lore(obj.get("lore")) if kind == "world" else []
