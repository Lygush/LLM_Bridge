"""Квест: состояние игры и варианты действий.

После каждого хода ведущего отдельный короткий запрос со схемой JSON обновляет состояние
(надёжнее, чем просить модель вставлять его в текст ответа). Состояние хранится в meta
сообщения ведущего — поэтому оно следует веткам: перегенерация или правка хода даёт своё состояние.
"""
import json

STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "location": {"type": "string"},
        "time": {"type": "string"},
        "health": {"type": "string"},
        "inventory": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
        "goals": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "relations": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
        "notes": {"type": "string"},
        "coins_delta": {"type": "integer", "minimum": -1000, "maximum": 1000},
        "choices": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
    },
    "required": ["location", "time", "health", "inventory", "goals", "relations", "notes",
                 "coins_delta", "choices"],
}

STATE_PROMPT = (
    "Ты ведёшь учёт состояния текстового квеста. По прежнему состоянию и последнему ходу "
    "(действие игрока и ответ ведущего) верни новое состояние. Меняй только то, что изменилось "
    "по тексту; ничего не выдумывай. Пиши по-русски, коротко.\n"
    "- location: где игрок сейчас; time: время суток/день;\n"
    "- health: самочувствие и раны игрока одной строкой (например «ранен в плечо, устал»);\n"
    "- inventory: предметы и деньги игрока; goals: текущие цели и задания;\n"
    "- relations: важные отношения «Имя — отношение»; notes: важные открытые обстоятельства;\n"
    "- coins_delta: сколько монет игрок получил (+) или потратил (−) за этот ход по тексту "
    "(награда, плата, находка, кража), иначе 0; деньги не пиши в inventory;\n"
    "- choices: 3–4 разных разумных действия игрока в текущей ситуации, каждое — короткая фраза "
    "от первого лица («Осмотреть дверь», «Спросить стражника о караване»).")

LISTS = ("inventory", "goals", "relations")
TITLES = (("location", "Где"), ("time", "Время"), ("health", "Состояние"),
          ("inventory", "Инвентарь"), ("goals", "Цели"), ("relations", "Отношения"),
          ("notes", "Заметки"))


def clean(state) -> dict:
    s = state if isinstance(state, dict) else {}
    out = {}
    for k, _ in TITLES:
        v = s.get(k)
        if k in LISTS:
            out[k] = [str(x).strip()[:200] for x in (v or []) if str(x).strip()][:30]
        else:
            out[k] = str(v or "").strip()[:1000]
    return out


def clean_choices(v) -> list:
    return [str(x).strip()[:160] for x in (v or []) if str(x).strip()][:4]


def text(state: dict) -> str:
    """Состояние для системного промпта и для запроса обновления."""
    if not state:
        return ""
    lines = []
    for k, title in TITLES:
        v = state.get(k)
        if isinstance(v, list):
            v = "; ".join(v)
        if v:
            lines.append(f"- {title}: {v}")
    return "\n".join(lines)


def update_messages(prev: dict, player: str, master: str) -> list:
    user = (f"ПРЕЖНЕЕ СОСТОЯНИЕ:\n{text(prev) or '(начало игры — состояние ещё пустое)'}\n\n"
            f"ДЕЙСТВИЕ ИГРОКА:\n{player.strip() or '(начало)'}\n\nОТВЕТ ВЕДУЩЕГО:\n{master.strip()}")
    return [{"role": "system", "content": STATE_PROMPT}, {"role": "user", "content": user}]


def parse(out: str) -> tuple:
    """→ (состояние, варианты действий, изменение монет)."""
    obj = json.loads(out)
    try:
        coins = max(-1000, min(1000, int(obj.get("coins_delta") or 0)))
    except (TypeError, ValueError):
        coins = 0
    return clean(obj), clean_choices(obj.get("choices")), coins
