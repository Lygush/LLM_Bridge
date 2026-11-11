"""Визуальная новелла: разметка ответа на кадры, фоны локаций, спрайты эмоций.

Модель пишет историю в простой разметке (её же удобно читать и как текст):
  [Место: старая таверна]          — смена места: под него рисуется фон (один раз, кэшируется)
  **Мира** (радость): Ты пришёл!    — реплика с эмоцией: на экране спрайт Миры с этой эмоцией
  остальное — повествование абзацами.
"""
import re

EMOTIONS = ("calm", "joy", "anger", "sadness", "embarrassed", "surprise")
EMOTION_RU = {"calm": "спокойствие", "joy": "радость", "anger": "злость", "sadness": "грусть",
              "embarrassed": "смущение", "surprise": "удивление"}
EMOTION_EN = {"calm": "calm neutral expression", "joy": "happy smiling expression",
              "anger": "angry frowning expression", "sadness": "sad teary expression",
              "embarrassed": "embarrassed blushing expression",
              "surprise": "surprised expression, wide eyes"}
_STEMS = (("joy", ("радост", "весел", "улыб", "смех", "смеё", "счаст", "восторг", "довол")),
          ("anger", ("зл", "гнев", "ярост", "раздраж", "сердит", "бешен")),
          ("sadness", ("грус", "печал", "слез", "тоск", "плач", "уныл")),
          ("embarrassed", ("смущ", "стыд", "красне", "неловк", "застенч")),
          ("surprise", ("удив", "изум", "шок", "ошелом", "ошараш")))

FORMAT = (
    "\n### Разметка сцены (визуальная новелла)\nТекст показывается по кадрам: фон места, "
    "персонаж с эмоцией, его реплика. Поэтому держи разметку строго.\n"
    "1. Каждый ответ начинай строкой «[Место: название]» — где сейчас идёт сцена. Название "
    "короткое и обычное («школьный коридор», «кухня Мирона»); пока место не сменилось, пиши его "
    "слово в слово так же. Сменилось место посреди ответа — новая строка «[Место: …]».\n"
    "2. Реплика персонажа — отдельная строка «**Имя** (эмоция): слова персонажа». В этой строке "
    "только прямая речь одного персонажа, без авторских слов и описаний. Имя — точно как в "
    "списке героев. Эмоция одна из: спокойствие, радость, злость, грусть, смущение, удивление.\n"
    "3. Действия, описания, мысли — отдельными короткими абзацами между репликами, без имени "
    "в начале. Не пиши диалог через тире внутри абзаца.\n"
    "4. Реплики героя пользователя не придумывай.\n"
    "5. У настоящей развилки (не чаще раза в несколько сцен) закончи ответ двумя-тремя строками "
    "«[Выбор: что сделать]».\n"
    "Пример:\n[Место: школьный коридор]\nНа перемене в коридоре было не протолкнуться.\n"
    "**Аня** (радость): Ты пришёл! Я уже думала, опоздаешь.\nОна поправила рюкзак и кивнула в "
    "сторону лестницы.\n**Аня** (смущение): Пойдём вместе?\n"
    "Указание пользователя «[Кадр: …]» разверни в полноценную сцену: место, позы, эмоции, реплики.")

_PLACE = re.compile(r"^\[(?:место|локация|место действия)\s*:\s*(.+?)\]\s*$", re.I)
_CHOICE = re.compile(r"^\[(?:выбор|вариант)\s*:\s*(.+?)\]\s*$", re.I)
_LINE = re.compile(r"^\*\*(.+?)\*\*\s*(?:\(([^)]{1,30})\))?\s*[:：—-]\s*(.+)$")
_LINE2 = re.compile(r"^\*\*(.+?):\*\*\s*(?:\(([^)]{1,30})\))?\s*(.+)$")


_DASH = re.compile(r"^[—–]\s*(.+)$")
_DASH_SPLIT = re.compile(r"(?<=[,.!?…])\s*[—–]\s+")
_TAIL = re.compile(r"^([«\"„“].+?[»\"”][.!?…]*)\s+([А-ЯЁA-Z].{12,})$")


def _split_tail(text: str):
    """«Привет!» Она подошла ближе. → реплика и авторский хвост отдельно."""
    m = _TAIL.match(text)
    return (m.group(1), m.group(2)) if m else (text, "")


def _who(text: str, chars: list):
    """Кто из героев упомянут в авторских словах (имя может быть в другом падеже)."""
    low = text.lower().replace("ё", "е")
    best = None
    for c in chars:
        name = (c["data"].get("name") or "").strip().lower().replace("ё", "е")
        if len(name) < 2:
            continue
        stem = name[:-1] if len(name) >= 3 else name
        m = re.search(r"(?<![а-яa-z])" + re.escape(stem) + r"[а-яa-z]{0,2}(?![а-яa-z])", low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), c)
    return best[1] if best else None


def emotion(word: str) -> str:
    w = (word or "").lower()
    for key, stems in _STEMS:
        if any(s in w for s in stems):
            return key
    return "calm"


def place_key(name: str) -> str:
    return " ".join(name.lower().replace("ё", "е").split())[:80]


def choices(text: str) -> list:
    """Варианты развилки из ответа: строки «[Выбор: …]»."""
    out = []
    for raw in text.splitlines():
        m = _CHOICE.match(raw.strip())
        if m:
            out.append(m.group(1).strip()[:160])
    return out[:4]


def parse(text: str, chars: list) -> list:
    """Текст ответа → кадры: place / narration / line (строки выбора — отдельно, см. choices)."""
    by_name = {(c["data"].get("name") or "").strip().lower(): c["id"] for c in chars}
    beats, para = [], []

    def flush():
        if para:
            t = " ".join(para).strip()
            if t:
                beats.append({"type": "narration", "text": t})
            para.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if _CHOICE.match(line):
            flush()
            continue
        m = _PLACE.match(line)
        if m:
            flush()
            beats.append({"type": "place", "name": m.group(1).strip(), "key": place_key(m.group(1))})
            continue
        m = _LINE2.match(line) or _LINE.match(line)
        if m and len(m.group(1)) <= 40:
            flush()
            name = m.group(1).strip().rstrip(":")
            said, tail = _split_tail(m.group(3).strip())
            cid = by_name.get(name.lower())
            if cid is None:   # «Аней», «Миры» — имя в другом падеже
                hit = _who(name, chars)
                if hit:
                    cid, name = hit["id"], hit["data"].get("name") or name
            beats.append({"type": "line", "name": name, "character_id": cid,
                          "emotion": emotion(m.group(2) or ""), "text": said})
            if tail:
                beats.append({"type": "narration", "text": tail})
            continue
        m = _DASH.match(line)
        if m:   # обычная проза: «— Привет, — улыбнулась Аня. — Ты рано.»
            parts = [x.strip() for x in _DASH_SPLIT.split(m.group(1)) if x.strip()]
            author = " ".join(parts[1::2])
            hit = _who(author, chars)
            if hit:
                flush()
                beats.append({"type": "line", "name": hit["data"].get("name") or "",
                              "character_id": hit["id"], "emotion": emotion(author),
                              "text": " ".join(re.sub(r",$", ".", x) for x in parts[0::2])})
                if author:
                    beats.append({"type": "narration", "text": author[:1].upper() + author[1:]})
                continue
        para.append(line)
    flush()
    return beats


BG_PROMPT = (
    "Ты составляешь промпт для нейросети, которая рисует фон сцены визуальной новеллы. "
    "Опиши по-английски, 40–80 слов, именно это место — таким, каким оно показано в сцене и "
    "каким бывает в этом мире и времени.\n"
    "Правила:\n"
    "- Эпоха, страна и тип места — из описания истории (современная школа остаётся современной "
    "школой: светлой, чистой, обычной).\n"
    "- Настроение и время суток — из сцены. Ничего не добавляй от себя: ни мрака, ни разрухи, "
    "ни тумана, ни неона, ни заброшенности, если их нет в тексте. По умолчанию место обжитое, "
    "ухоженное, нормально освещённое.\n"
    "- Героев сцены не описывай (они рисуются отдельно). Если место людное (перемена, рынок, "
    "вечеринка) — толпа вдалеке, без лиц крупным планом; иначе людей нет.\n"
    "- Вид с уровня глаз, широкий план, место узнаётся с первого взгляда.\n"
    "Только промпт.")
BG_SCHEMA = {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}


def bg_messages(place: str, world, context: str, premise: str = "", cast: str = "") -> list:
    w = ""
    if world:
        d = world["data"]
        w = (f"МИР: {d.get('name', '')}. {d.get('description', '')[:800]}\n"
             f"ТОН: {d.get('tone', '')}\n")
    if premise:
        w += f"О ЧЁМ ИСТОРИЯ: {premise[:600]}\n"
    if cast:
        w += f"ГЕРОИ (для понимания эпохи, не рисовать): {cast[:400]}\n"
    return [{"role": "system", "content": BG_PROMPT},
            {"role": "user", "content": f"{w}МЕСТО: {place}\nСЦЕНА:\n{context[:1800]}"}]


def bg_prompt(llm_prompt: str, world, style: str = "") -> str:
    style = ((world or {}).get("data", {}).get("style_tags", "") if world else "") or style
    tail = ", visual novel background, eye-level wide shot, no characters in the foreground"
    return " ".join((llm_prompt.strip() + (f", {style}" if style else "") + tail).split())


def sprite_prompt(card: dict, emo: str) -> str:
    d = card["data"]
    tags = d.get("appearance_tags") or d.get("appearance") or d.get("name", "")
    style = (d.get("art_style") or "").strip() or \
        "photorealistic, natural lighting, realistic skin texture, high detail photo"
    return (f"portrait of a single character, {tags}, {EMOTION_EN[emo]}, upper body, "
            f"facing viewer, plain light grey background, soft even lighting, {style}")
