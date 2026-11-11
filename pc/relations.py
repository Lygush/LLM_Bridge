"""Отношения персонажа с пользователем (персоной) и чувство времени.

Отношения общие для всех чатов этой пары «персонаж × персона». После каждого обмена репликами
фоновая модель оценивает, как он повлиял: симпатия и доверие меняются понемногу, настроение —
сразу, но со временем возвращается к обычному. Статус (незнакомец… близкий, неприязнь… враг)
считается из чисел, чтобы не прыгал от одной фразы.
"""
import json
import time
from datetime import datetime

MOOD_FADE = 8 * 3600       # через столько часов настроение возвращается к обычному
MAX_EVENTS = 12
MAX_PROMISES = 8

UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "sympathy": {"type": "integer", "minimum": -10, "maximum": 10},
        "trust": {"type": "integer", "minimum": -10, "maximum": 10},
        "mood": {"type": "string"},
        "event": {"type": "string"},
        "promises_new": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "promises_kept": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "promises_broken": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "money_given": {"type": "integer", "minimum": 0, "maximum": 1000},
    },
    "required": ["sympathy", "trust", "mood", "event", "promises_new", "promises_kept",
                 "promises_broken", "money_given"],
}

UPDATE_PROMPT = (
    "Ты оцениваешь, как последний обмен репликами повлиял на отношения персонажа к собеседнику. "
    "Смотри глазами персонажа, с учётом его характера, вкусов, прошлых отношений и настроения.\n"
    "- sympathy, trust: изменение симпатии и доверия от −10 до +10. Обычная болтовня — 0…+2; "
    "приятное, забота, общие интересы — +3…+6; грубость, ложь, равнодушие — отрицательные; "
    "сильные поступки — до ±10. Отношения меняются постепенно.\n"
    "- mood: настроение персонажа после этого одним-двумя словами (весёлое, усталое, обижена…).\n"
    "- event: если было что-то заметное — короткая подсказка для собеседника от третьего лица, "
    "без чисел («Мире понравился комплимент», «Торин обиделся на шутку»); иначе пусто.\n"
    "- promises_new: что собеседник пообещал персонажу (кратко), promises_kept / promises_broken — "
    "какие из прежних обещаний он выполнил или нарушил (дословно как в списке).\n"
    "- money_given: сколько монет персонаж по своему ответу реально дал собеседнику (взаймы или "
    "просто так); 0 — если отказал, не дал или речь не о деньгах.")


def new() -> dict:
    return {"sympathy": 0, "trust": 10, "mood": "", "mood_at": 0, "events": [], "promises": [],
            "interactions": 0}


def status(r: dict) -> str:
    s, t, n = r.get("sympathy", 0), r.get("trust", 0), r.get("interactions", 0)
    if s <= -60:
        return "враг"
    if s <= -20:
        return "неприязнь"
    if n < 3 and s < 30:
        return "незнакомец"
    if s < 30:
        return "знакомый"
    if s < 60 or t < 40:
        return "друг"
    return "близкий"


def mood(r: dict, now: float = None) -> str:
    now = now or time.time()
    if r.get("mood") and now - r.get("mood_at", 0) < MOOD_FADE:
        return r["mood"]
    return "обычное"


def public(r: dict) -> dict:
    """Для телефона: числа, статус, настроение, последние события, долг."""
    return {"sympathy": r.get("sympathy", 0), "trust": r.get("trust", 0), "status": status(r),
            "mood": mood(r), "events": r.get("events", [])[-5:],
            "promises": [p["text"] for p in r.get("promises", [])], "debt": r.get("debt", 0)}


def others_block(user: str, others: list) -> str:
    """Что персонаж знает о других знакомствах собеседника — повод для ревности и вопросов."""
    if not others:
        return ""
    return (f"Ты знаешь, что {user} также общается с: " +
            ", ".join(f"{n} ({st})" for n, st in others) +
            ". Относись к этому по своему характеру и знакомствам.")


def ago(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 60:
        return f"{m} мин"
    h = m // 60
    if h < 24:
        return f"{h} ч"
    d = h // 24
    return f"{d} дн"


def prompt_block(char_name: str, user: str, r: dict, now: float = None) -> str:
    now = now or time.time()
    lines = [f"## Отношения {char_name} с {user}",
             f"Статус: {status(r)} (симпатия {r.get('sympathy', 0)}/100, доверие "
             f"{r.get('trust', 0)}/100). Настроение сейчас: {mood(r, now)}."]
    ev = [e["text"] for e in r.get("events", [])[-4:]]
    if ev:
        lines.append("Что было между вами недавно (это фон для твоего отношения, а не тема: "
                     "не пересказывай и не возвращайся к этому без повода): " + "; ".join(ev) + ".")
    pr = r.get("promises", [])
    if pr:
        lines.append(f"Обещания {user}: " + "; ".join(
            f"«{p['text']}» ({ago(now - p.get('at', now))} назад)" for p in pr) + ".")
    if r.get("debt"):
        lines.append(f"{user} должен(на) тебе {r['debt']} монет (занял(а) "
                     f"{ago(now - r.get('debt_at', now))} назад).")
    lines.append(
        "Веди себя в соответствии с отношениями и настроением. На просьбы, требующие близости "
        "или доверия (личные фото, откровенность, встреча, тайны, одолжения), соглашайся, только "
        "если отношения это позволяют; иначе откажи в своём стиле — мягко или резко, по "
        "характеру. Можешь напомнить о невыполненном обещании.")
    return "\n".join(lines)


def apply(r: dict, upd: dict, now: float = None) -> tuple:
    """Применить оценку модели → (новые отношения, подсказка-событие или '')."""
    now = now or time.time()
    r = dict(new(), **r)
    clamp = lambda v, lo, hi: max(lo, min(hi, v))  # noqa: E731
    ds = clamp(int(upd.get("sympathy") or 0), -10, 10)
    dt = clamp(int(upd.get("trust") or 0), -10, 10)
    promises = list(r.get("promises", []))
    kept = {str(x).strip().lower() for x in upd.get("promises_kept") or []}
    broken = {str(x).strip().lower() for x in upd.get("promises_broken") or []}
    left = []
    for p in promises:
        k = p["text"].strip().lower()
        if k in kept:
            ds, dt = ds + 2, dt + 3
        elif k in broken:
            ds, dt = ds - 3, dt - 6
        else:
            left.append(p)
    for t in upd.get("promises_new") or []:
        t = " ".join(str(t).split())[:160]
        if t and all(t.lower() != p["text"].lower() for p in left):
            left.append({"text": t, "at": now})
    r["promises"] = left[-MAX_PROMISES:]
    r["sympathy"] = clamp(r["sympathy"] + ds, -100, 100)
    r["trust"] = clamp(r["trust"] + dt, 0, 100)
    m = " ".join(str(upd.get("mood") or "").split())[:40]
    if m:
        r["mood"], r["mood_at"] = m, now
    r["interactions"] = r.get("interactions", 0) + 1
    event = " ".join(str(upd.get("event") or "").split())[:160]
    if event:
        r["events"] = (r.get("events", []) + [{"text": event, "at": now}])[-MAX_EVENTS:]
    return r, event


def update_messages(char: dict, user: str, r: dict, player: str, answer: str) -> list:
    d = char["data"]
    card = "\n".join(f"{k}: {d[k]}" for k in ("personality", "likes", "speech") if d.get(k))
    prom = "\n".join(f"- {p['text']}" for p in r.get("promises", [])) or "(нет)"
    user_msg = (f"ПЕРСОНАЖ: {d.get('name')}\n{card}\n\nОТНОШЕНИЯ СЕЙЧАС: {status(r)}, симпатия "
                f"{r.get('sympathy', 0)}, доверие {r.get('trust', 0)}, настроение {mood(r)}\n"
                f"ОБЕЩАНИЯ {user}:\n{prom}\n\nСОБЕСЕДНИК ({user}) НАПИСАЛ:\n{player.strip()[:2000]}\n\n"
                f"ПЕРСОНАЖ ОТВЕТИЛ:\n{answer.strip()[:2500]}")
    return [{"role": "system", "content": UPDATE_PROMPT}, {"role": "user", "content": user_msg}]


def parse(out: str) -> dict:
    return json.loads(out)


# ------------------------------------------------------------------ время
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")


def part_of_day(h: int) -> str:
    return "ночь" if h < 5 else "утро" if h < 12 else "день" if h < 18 else "вечер" if h < 23 else "ночь"


def time_block(now: float = None, gap: float = None, user: str = "собеседник") -> str:
    """Текущее время (часы ПК) и пауза с прошлого сообщения."""
    t = datetime.fromtimestamp(now or time.time())
    line = (f"## Время\nСейчас {WEEKDAYS[t.weekday()]}, {t.day} {MONTHS[t.month - 1]} {t.year}, "
            f"{t:%H:%M} ({part_of_day(t.hour)}).")
    if gap and gap >= 30 * 60:
        line += f" {user[:1].upper() + user[1:]} не писал(а) {ago(gap)}."
    return line
