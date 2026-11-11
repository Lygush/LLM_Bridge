"""Хранилище чатов: SQLite в data/chats.db

Сообщения образуют дерево (parent_id): варианты ответа и правки — это «братья»
с общим родителем. У чата есть head_id — последнее сообщение активной ветки;
активная история — путь от head вверх до корня.

Используется только из потока HTTP-сервера (одно соединение, без блокировок).
"""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id            INTEGER PRIMARY KEY,
    title         TEXT    NOT NULL DEFAULT '',
    system_prompt TEXT    NOT NULL DEFAULT '',
    settings      TEXT    NOT NULL DEFAULT '{}',
    head_id       INTEGER,
    created       REAL    NOT NULL,
    updated       REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id                INTEGER PRIMARY KEY,
    chat_id           INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    parent_id         INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    role              TEXT    NOT NULL,
    content           TEXT    NOT NULL DEFAULT '',
    reasoning         TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'done',   -- done | generating | cancelled | error
    error             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    meta              TEXT    NOT NULL DEFAULT '{}',
    created           REAL    NOT NULL,
    updated           REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat   ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- память чата: долговременные факты
CREATE TABLE IF NOT EXISTS facts (
    id      INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    text    TEXT    NOT NULL,
    pinned  INTEGER NOT NULL DEFAULT 0,   -- закреплённый факт модель не меняет и не удаляет
    auto    INTEGER NOT NULL DEFAULT 1,   -- 1 — извлечён моделью, 0 — добавлен вручную
    created REAL    NOT NULL,
    updated REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_chat ON facts(chat_id);
-- хроника: краткое содержание ветки до сообщения until_id (0 — ни одного)
CREATE TABLE IF NOT EXISTS chronicles (
    id       INTEGER PRIMARY KEY,
    chat_id  INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    until_id INTEGER NOT NULL,
    text     TEXT    NOT NULL,
    created  REAL    NOT NULL,
    updated  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chronicles_chat ON chronicles(chat_id);
-- карточки: персонажи, персоны пользователя (позже — миры)
CREATE TABLE IF NOT EXISTS cards (
    id       INTEGER PRIMARY KEY,
    kind     TEXT    NOT NULL,              -- character | persona | world
    name     TEXT    NOT NULL DEFAULT '',
    data     TEXT    NOT NULL DEFAULT '{}', -- поля карточки (см. cards.FIELDS)
    portrait TEXT,                          -- {"name","w","h"} картинки-портрета
    created  REAL    NOT NULL,
    updated  REAL    NOT NULL
);
-- лорбук мира: записи попадают в контекст, когда в разговоре встречаются их ключи
CREATE TABLE IF NOT EXISTS lore (
    id      INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    title   TEXT    NOT NULL DEFAULT '',
    keys    TEXT    NOT NULL DEFAULT '',   -- основы слов через запятую
    content TEXT    NOT NULL,
    always  INTEGER NOT NULL DEFAULT 0,    -- 1 — в контексте всегда
    created REAL    NOT NULL,
    updated REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lore_card ON lore(card_id);
-- отношения персонажа с персоной (0 — без персоны); общие для всех их чатов
CREATE TABLE IF NOT EXISTS relations (
    character_id INTEGER NOT NULL,
    persona_id   INTEGER NOT NULL DEFAULT 0,
    data         TEXT    NOT NULL DEFAULT '{}',
    updated      REAL    NOT NULL,
    PRIMARY KEY (character_id, persona_id)
);
"""

# столбцы, добавленные после первой версии: (таблица, столбец, определение)
MIGRATIONS = [
    ("messages", "tokens", "INTEGER"),                      # длина в токенах (кэш)
    ("messages", "pinned", "INTEGER NOT NULL DEFAULT 0"),   # всегда в контексте
    ("chats", "memory_until", "INTEGER NOT NULL DEFAULT 0"),  # до какого сообщения извлечены факты
    ("cards", "sprites", "TEXT"),                           # {эмоция: картинка} для новеллы
]

# параметры генерации, которые можно задать чату (передаются в llama-server как есть)
SAMPLING_KEYS = {
    "temperature": float, "top_p": float, "top_k": int, "min_p": float,
    "repeat_penalty": float, "repeat_last_n": int, "presence_penalty": float,
    "frequency_penalty": float, "dry_multiplier": float, "dry_base": float,
    "dry_allowed_length": int, "xtc_probability": float, "xtc_threshold": float,
    "max_tokens": int, "seed": int,
}


# рисование моделью в диалоге: выкл / когда попросят / сама иллюстрирует ключевые моменты
ILLUSTRATE = ("off", "on_request", "auto")
# привязки чата к карточкам; при сохранении параметров без них — сохраняются прежние
BIND_KEYS = ("character_id", "persona_id", "world_id")
KEEP_KEYS = BIND_KEYS + ("character_ids", "mode", "chat_style", "initiative", "date_of", "vn_bg")
MODES = ("chat", "quest", "story", "gm")
CHAT_STYLES = ("messenger", "roleplay")
WALLET_START = 100


class NotFound(LookupError):
    pass


class BadRequest(ValueError):
    pass


def clean_settings(d: dict) -> dict:
    """Параметры генерации чата: сэмплинг llama-server и thinking (размышления, по умолчанию выкл)."""
    out = {}
    for k, v in (d or {}).items():
        if k == "thinking" and v is not None:
            out[k] = bool(v)
        elif k == "image_profile" and v:
            out[k] = str(v)[:64]
        elif k == "illustrate" and v:
            if v not in ILLUSTRATE:
                raise BadRequest("settings.illustrate: off | on_request | auto")
            out[k] = v
        elif k == "character_ids":
            try:
                ids = [int(x) for x in (v or [])]
            except (TypeError, ValueError):
                raise BadRequest("settings.character_ids: список чисел")
            if ids:
                out[k] = list(dict.fromkeys(ids))[:8]
        elif k == "mode" and v:
            if v not in MODES:
                raise BadRequest("settings.mode: chat | quest | story | gm")
            out[k] = v
        elif k == "chat_style" and v:
            if v not in CHAT_STYLES:
                raise BadRequest("settings.chat_style: messenger | roleplay")
            out[k] = v
        elif k == "vn_bg" and v:
            if v not in ("auto", "manual"):
                raise BadRequest("settings.vn_bg: auto | manual")
            out[k] = v   # фоны новеллы: рисовать сами при смене места / только по кнопке
        elif k == "date_of" and v:
            out[k] = int(v)   # история-свидание: из какого чата с персонажем начата
        elif k == "likeness" and v is not None:
            out[k] = bool(v)   # рисовать персонажей по образцам портретов
        elif k == "initiative" and v is not None:
            out[k] = bool(v)   # персонаж может написать первым при входе
        elif k in BIND_KEYS:
            if v not in (None, "", 0):
                try:
                    out[k] = int(v)
                except (TypeError, ValueError):
                    raise BadRequest(f"settings.{k}: некорректное значение")
        elif k in SAMPLING_KEYS and v is not None:
            try:
                out[k] = SAMPLING_KEYS[k](v)
            except (TypeError, ValueError):
                raise BadRequest(f"settings.{k}: некорректное значение")
    return out


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    def close(self):
        self.db.close()

    # ------------------------------------------------------------- настройки
    def get_setting(self, key: str, default=None):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_setting(self, key: str, value):
        self.db.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    # ------------------------------------------------------- восстановление
    def recover(self) -> int:
        """После перезапуска: незавершённые генерации помечаются прерванными."""
        cur = self.db.execute(
            "UPDATE messages SET status='error', error='Прервано перезапуском моста', updated=? "
            "WHERE status='generating'", (time.time(),))
        self.db.commit()
        return cur.rowcount

    # ------------------------------------------------------------------ чаты
    def _chat_row(self, chat_id: int) -> sqlite3.Row:
        r = self.db.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not r:
            raise NotFound(f"чат {chat_id} не найден")
        return r

    def chat_dict(self, chat_id: int) -> dict:
        r = self._chat_row(chat_id)
        last = None
        if r["head_id"]:
            m = self.db.execute("SELECT content, role FROM messages WHERE id=?",
                                (r["head_id"],)).fetchone()
            if m:
                last = m["content"][:120]
        return {
            "id": r["id"], "title": r["title"], "system_prompt": r["system_prompt"],
            "settings": json.loads(r["settings"]), "head_id": r["head_id"],
            "created": r["created"], "updated": r["updated"], "preview": last or "",
        }

    def list_chats(self) -> list:
        ids = [r["id"] for r in self.db.execute("SELECT id FROM chats ORDER BY updated DESC")]
        return [self.chat_dict(i) for i in ids]

    def create_chat(self, title: str = "", system_prompt=None, settings=None) -> dict:
        if system_prompt is None:
            system_prompt = self.get_setting("default_system_prompt", "")
        if settings is None:
            settings = self.get_setting("default_settings", {})
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO chats(title, system_prompt, settings, created, updated) VALUES(?,?,?,?,?)",
            (title.strip(), system_prompt, json.dumps(clean_settings(settings)), now, now))
        self.db.commit()
        return self.chat_dict(cur.lastrowid)

    def update_chat(self, chat_id: int, title=None, system_prompt=None, settings=None) -> dict:
        self._chat_row(chat_id)
        sets, args = [], []
        if title is not None:
            sets.append("title=?"); args.append(str(title).strip())
        if system_prompt is not None:
            sets.append("system_prompt=?"); args.append(str(system_prompt).strip())
        if settings is not None:
            new = clean_settings(settings)
            old = json.loads(self._chat_row(chat_id)["settings"] or "{}")
            for k in KEEP_KEYS:   # null/0 — отвязать, отсутствие ключа — оставить как было
                if k not in settings and k in old:
                    new[k] = old[k]
            sets.append("settings=?"); args.append(json.dumps(new))
        if sets:
            sets.append("updated=?"); args.append(time.time())
            self.db.execute(f"UPDATE chats SET {', '.join(sets)} WHERE id=?", (*args, chat_id))
            self.db.commit()
        return self.chat_dict(chat_id)

    def delete_chat(self, chat_id: int):
        self._chat_row(chat_id)
        self.db.execute("DELETE FROM settings WHERE key=?", (f"vn:{chat_id}",))
        self.db.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        self.db.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        self.db.commit()

    def touch(self, chat_id: int):
        self.db.execute("UPDATE chats SET updated=? WHERE id=?", (time.time(), chat_id))
        self.db.commit()

    # ------------------------------------------------------------- сообщения
    def _msg_row(self, msg_id: int) -> sqlite3.Row:
        r = self.db.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        if not r:
            raise NotFound(f"сообщение {msg_id} не найдено")
        return r

    def _siblings(self, r: sqlite3.Row) -> list:
        if r["parent_id"] is None:
            rows = self.db.execute(
                "SELECT id FROM messages WHERE chat_id=? AND parent_id IS NULL ORDER BY id",
                (r["chat_id"],))
        else:
            rows = self.db.execute(
                "SELECT id FROM messages WHERE parent_id=? ORDER BY id", (r["parent_id"],))
        return [x["id"] for x in rows]

    def msg_dict(self, msg_id: int) -> dict:
        r = self._msg_row(msg_id)
        sib = self._siblings(r)
        return {
            "id": r["id"], "chat_id": r["chat_id"], "parent_id": r["parent_id"],
            "role": r["role"], "content": r["content"], "reasoning": r["reasoning"],
            "status": r["status"], "error": r["error"],
            "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
            "meta": json.loads(r["meta"]),
            "pinned": bool(r["pinned"]),
            "variant": sib.index(r["id"]) + 1 if r["id"] in sib else 1,
            "variants": len(sib), "variant_ids": sib,
            "created": r["created"],
        }

    def path(self, chat_id: int, head_id=None) -> list:
        """Активная ветка от корня до head — список id."""
        if head_id is None:
            head_id = self._chat_row(chat_id)["head_id"]
        ids = []
        cur = head_id
        while cur is not None:
            r = self.db.execute("SELECT id, parent_id FROM messages WHERE id=?", (cur,)).fetchone()
            if not r:
                break
            ids.append(r["id"])
            cur = r["parent_id"]
        ids.reverse()
        return ids

    def messages(self, chat_id: int) -> list:
        return [self.msg_dict(i) for i in self.path(chat_id)]

    def _set_head(self, chat_id: int, head_id):
        self.db.execute("UPDATE chats SET head_id=?, updated=? WHERE id=?",
                        (head_id, time.time(), chat_id))

    def _insert(self, chat_id, parent_id, role, content="", status="done") -> int:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO messages(chat_id, parent_id, role, content, status, created, updated) "
            "VALUES(?,?,?,?,?,?,?)", (chat_id, parent_id, role, content, status, now, now))
        return cur.lastrowid

    def add_user_message(self, chat_id: int, content: str, replace_id=None, images=None) -> int:
        """Новое сообщение пользователя: в конец активной ветки
        или новым вариантом рядом с replace_id (правка с повторной отправкой).
        images — [{"name","w","h"}]; при замене без новых картинок берутся прежние."""
        chat = self._chat_row(chat_id)
        content = content.strip()
        if replace_id is not None:
            old = self._msg_row(replace_id)
            if old["chat_id"] != chat_id or old["role"] != "user":
                raise BadRequest("заменять можно только своё сообщение в этом чате")
            parent = old["parent_id"]
            if images is None:
                images = json.loads(old["meta"]).get("images")
        else:
            parent = chat["head_id"]
        if not content and not images:
            raise BadRequest("пустое сообщение")
        mid = self._insert(chat_id, parent, "user", content)
        if images:
            self.db.execute("UPDATE messages SET meta=? WHERE id=?",
                            (json.dumps({"images": images}), mid))
        self._set_head(chat_id, mid)
        if not chat["title"]:
            first = (content.splitlines()[0].strip() if content else "Фото")
            title = first[:48] + ("…" if len(first) > 48 else "")
            self.db.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))
        self.db.commit()
        return mid

    def add_assistant(self, chat_id: int, parent_id: int) -> int:
        mid = self._insert(chat_id, parent_id, "assistant", status="generating")
        self._set_head(chat_id, mid)
        self.db.commit()
        return mid

    def add_greeting(self, chat_id: int, content: str, meta=None) -> int:
        """Первое сообщение персонажа в новом чате."""
        mid = self._insert(chat_id, None, "assistant", content)
        if meta:
            self.db.execute("UPDATE messages SET meta=? WHERE id=?", (json.dumps(meta), mid))
        self._set_head(chat_id, mid)
        self.db.commit()
        return mid

    # ------------------------------------------------------------- карточки
    def _card_row(self, card_id: int) -> sqlite3.Row:
        r = self.db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not r:
            raise NotFound(f"карточка {card_id} не найдена")
        return r

    def card(self, card_id: int) -> dict:
        r = self._card_row(card_id)
        return {"id": r["id"], "kind": r["kind"], "name": r["name"], "data": json.loads(r["data"]),
                "portrait": json.loads(r["portrait"]) if r["portrait"] else None,
                "sprites": json.loads(r["sprites"]) if r["sprites"] else {},
                "created": r["created"], "updated": r["updated"]}

    def card_or_none(self, card_id):
        try:
            return self.card(int(card_id)) if card_id else None
        except (LookupError, TypeError, ValueError):
            return None

    def cards(self, kind=None) -> list:
        q, a = "SELECT id FROM cards", ()
        if kind:
            q, a = q + " WHERE kind=?", (kind,)
        return [self.card(r["id"]) for r in self.db.execute(q + " ORDER BY updated DESC", a)]

    def save_card(self, kind: str, data: dict, card_id=None) -> dict:
        now = time.time()
        name = str(data.get("name", "")).strip()[:80]
        if card_id is None:
            cur = self.db.execute("INSERT INTO cards(kind, name, data, created, updated) "
                                  "VALUES(?,?,?,?,?)", (kind, name, json.dumps(data), now, now))
            card_id = cur.lastrowid
        else:
            self._card_row(card_id)
            self.db.execute("UPDATE cards SET name=?, data=?, updated=? WHERE id=?",
                            (name, json.dumps(data), now, card_id))
        self.db.commit()
        return self.card(card_id)

    def set_portrait(self, card_id: int, image: dict) -> dict:
        self.db.execute("UPDATE cards SET portrait=?, updated=? WHERE id=?",
                        (json.dumps(image), time.time(), card_id))
        self.db.commit()
        return self.card(card_id)

    # ---------------------------------------------------------------- лорбук
    @staticmethod
    def _lore_dict(r) -> dict:
        return {"id": r["id"], "card_id": r["card_id"], "title": r["title"], "keys": r["keys"],
                "content": r["content"], "always": bool(r["always"])}

    def lore(self, card_id: int) -> list:
        return [self._lore_dict(r) for r in self.db.execute(
            "SELECT * FROM lore WHERE card_id=? ORDER BY always DESC, title", (card_id,))]

    def add_lore(self, card_id: int, title: str, keys: str, content: str, always=False) -> dict:
        self._card_row(card_id)
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO lore(card_id, title, keys, content, always, created, updated) "
            "VALUES(?,?,?,?,?,?,?)", (card_id, title.strip(), keys.strip(), content.strip(),
                                      int(bool(always)), now, now))
        self.db.commit()
        return self.lore_item(cur.lastrowid)

    def lore_item(self, lore_id: int) -> dict:
        r = self.db.execute("SELECT * FROM lore WHERE id=?", (lore_id,)).fetchone()
        if not r:
            raise NotFound(f"запись лорбука {lore_id} не найдена")
        return self._lore_dict(r)

    def update_lore(self, lore_id: int, **kw) -> dict:
        self.lore_item(lore_id)
        sets, args = [], []
        for k in ("title", "keys", "content"):
            if kw.get(k) is not None:
                sets.append(f"{k}=?"); args.append(str(kw[k]).strip())
        if kw.get("always") is not None:
            sets.append("always=?"); args.append(int(bool(kw["always"])))
        if sets:
            sets.append("updated=?"); args.append(time.time())
            self.db.execute(f"UPDATE lore SET {', '.join(sets)} WHERE id=?", (*args, lore_id))
            self.db.commit()
        return self.lore_item(lore_id)

    def delete_lore(self, lore_id: int) -> int:
        card_id = self.lore_item(lore_id)["card_id"]
        self.db.execute("DELETE FROM lore WHERE id=?", (lore_id,))
        self.db.commit()
        return card_id

    # ------------------------------------------------------------ отношения
    def relation(self, character_id: int, persona_id) -> dict:
        r = self.db.execute("SELECT data FROM relations WHERE character_id=? AND persona_id=?",
                            (character_id, persona_id or 0)).fetchone()
        return json.loads(r["data"]) if r else {}

    def save_relation(self, character_id: int, persona_id, data: dict):
        self.db.execute(
            "INSERT INTO relations(character_id, persona_id, data, updated) VALUES(?,?,?,?) "
            "ON CONFLICT(character_id, persona_id) DO UPDATE SET data=excluded.data, "
            "updated=excluded.updated", (character_id, persona_id or 0, json.dumps(data), time.time()))
        self.db.commit()

    def relations_of(self, persona_id) -> list:
        """Все отношения персоны: [(character_id, data)]."""
        return [(r["character_id"], json.loads(r["data"])) for r in self.db.execute(
            "SELECT character_id, data FROM relations WHERE persona_id=?", (persona_id or 0,))]

    def reset_relation(self, character_id: int, persona_id):
        self.db.execute("DELETE FROM relations WHERE character_id=? AND persona_id=?",
                        (character_id, persona_id or 0))
        self.db.commit()

    # --------------------------------------------------------------- кошелёк
    def wallet(self, persona_id) -> int:
        """Монеты персоны (0 — без персоны): зарабатываются в квестах, тратятся на подарки."""
        w = self.get_setting("wallets", {}) or {}
        return int(w.get(str(persona_id or 0), WALLET_START))

    def add_coins(self, persona_id, delta: int) -> int:
        w = self.get_setting("wallets", {}) or {}
        key = str(persona_id or 0)
        w[key] = max(0, int(w.get(key, WALLET_START)) + int(delta))
        self.set_setting("wallets", w)
        return w[key]

    def set_sprites(self, card_id: int, sprites: dict) -> dict:
        self.db.execute("UPDATE cards SET sprites=?, updated=? WHERE id=?",
                        (json.dumps(sprites), time.time(), card_id))
        self.db.commit()
        return self.card(card_id)

    # ------------------------------------------------------- фоны новеллы
    def vn_backgrounds(self, chat_id: int) -> dict:
        """{ключ места: картинка} — фоны локаций истории, рисуются один раз."""
        return self.get_setting(f"vn:{chat_id}", {}) or {}

    def first_user_text(self, chat_id: int) -> str:
        """Первое сообщение пользователя в чате — завязка истории."""
        r = self.db.execute("SELECT content FROM messages WHERE chat_id=? AND role='user' "
                            "ORDER BY id LIMIT 1", (chat_id,)).fetchone()
        return (r[0] if r else "") or ""

    def set_vn_background(self, chat_id: int, key: str, image: dict):
        m = self.vn_backgrounds(chat_id)
        m[key] = image
        self.set_setting(f"vn:{chat_id}", m)

    def children(self, msg_id: int) -> list:
        return self.db.execute("SELECT * FROM messages WHERE parent_id=? ORDER BY id",
                               (msg_id,)).fetchall()

    def chat_images(self, chat_id: int) -> list:
        """Все картинки чата (во всех ветках): [{name, w, h, msg_id, caption}]."""
        out = []
        for r in self.db.execute("SELECT id, role, meta FROM messages WHERE chat_id=? ORDER BY id",
                                 (chat_id,)):
            m = json.loads(r["meta"] or "{}")
            d = m.get("drawn") or m
            for img in m.get("images") or []:
                out.append(dict(img, msg_id=r["id"], role=r["role"],
                                caption=d.get("caption") or d.get("request") or d.get("prompt") or ""))
        return out

    def delete_card(self, card_id: int):
        self._card_row(card_id)
        self.db.execute("DELETE FROM lore WHERE card_id=?", (card_id,))
        self.db.execute("DELETE FROM relations WHERE character_id=? OR persona_id=?",
                        (card_id, card_id))
        self.db.execute("DELETE FROM cards WHERE id=?", (card_id,))
        self.db.commit()

    def regenerate(self, msg_id: int) -> int:
        """Новый вариант ответа рядом с msg_id (тот же родитель)."""
        r = self._msg_row(msg_id)
        if r["role"] != "assistant":
            raise BadRequest("перегенерировать можно только ответ модели")
        if r["status"] == "generating":
            raise BadRequest("ответ ещё генерируется")
        return self.add_assistant(r["chat_id"], r["parent_id"])

    def edit_message(self, msg_id: int, content: str) -> dict:
        r = self._msg_row(msg_id)
        if r["status"] == "generating":
            raise BadRequest("сообщение ещё генерируется")
        self.db.execute("UPDATE messages SET content=?, tokens=NULL, updated=? WHERE id=?",
                        (content, time.time(), msg_id))
        self.db.commit()
        self.touch(r["chat_id"])
        return self.msg_dict(msg_id)

    def set_status(self, msg_id: int, status: str):
        self.db.execute("UPDATE messages SET status=?, error=NULL, updated=? WHERE id=?",
                        (status, time.time(), msg_id))
        self.db.commit()

    def merge_meta(self, msg_id: int, extra: dict):
        r = self._msg_row(msg_id)
        meta = json.loads(r["meta"] or "{}")
        meta.update(extra)
        self.db.execute("UPDATE messages SET meta=? WHERE id=?", (json.dumps(meta), msg_id))
        self.db.commit()

    def set_chat_setting(self, chat_id: int, key: str, value):
        r = self._chat_row(chat_id)
        s = json.loads(r["settings"] or "{}")
        s[key] = value
        self.db.execute("UPDATE chats SET settings=? WHERE id=?", (json.dumps(clean_settings(s)), chat_id))
        self.db.commit()

    def set_pinned(self, msg_id: int, pinned: bool) -> dict:
        self._msg_row(msg_id)
        self.db.execute("UPDATE messages SET pinned=? WHERE id=?", (int(pinned), msg_id))
        self.db.commit()
        return self.msg_dict(msg_id)

    def reopen(self, msg_id: int) -> dict:
        """Продолжение ответа: сообщение снова становится генерируемым."""
        r = self._msg_row(msg_id)
        if r["role"] != "assistant":
            raise BadRequest("продолжить можно только ответ модели")
        if r["status"] == "generating":
            raise BadRequest("ответ ещё генерируется")
        if not r["content"].strip():
            raise BadRequest("ответ пустой — используйте перегенерацию")
        if self.deepest_leaf(msg_id) != msg_id:
            raise BadRequest("продолжить можно только последний ответ ветки")
        self.db.execute("UPDATE messages SET status='generating', error=NULL, tokens=NULL, updated=? "
                        "WHERE id=?", (time.time(), msg_id))
        self._set_head(r["chat_id"], self.deepest_leaf(msg_id))
        self.db.commit()
        return self.msg_dict(msg_id)

    def deepest_leaf(self, msg_id: int) -> int:
        """Спуск по самым новым потомкам — куда ведёт ветка."""
        cur = msg_id
        while True:
            r = self.db.execute("SELECT id FROM messages WHERE parent_id=? ORDER BY id DESC LIMIT 1",
                                (cur,)).fetchone()
            if not r:
                return cur
            cur = r["id"]

    def select_variant(self, msg_id: int) -> int:
        r = self._msg_row(msg_id)
        head = self.deepest_leaf(msg_id)
        self._set_head(r["chat_id"], head)
        self.db.commit()
        return r["chat_id"]

    def subtree(self, msg_id: int) -> list:
        ids, stack = [], [msg_id]
        while stack:
            cur = stack.pop()
            ids.append(cur)
            stack.extend(x["id"] for x in
                         self.db.execute("SELECT id FROM messages WHERE parent_id=?", (cur,)))
        return ids

    def delete_message(self, msg_id: int) -> int:
        """Удаляет сообщение со всеми продолжениями. Возвращает chat_id."""
        r = self._msg_row(msg_id)
        chat_id = r["chat_id"]
        chat = self._chat_row(chat_id)
        doomed = set(self.subtree(msg_id))
        if chat["head_id"] in doomed:
            sib = [s for s in self._siblings(r) if s != msg_id]
            if sib:
                new_head = self.deepest_leaf(sib[-1])
            else:
                new_head = r["parent_id"]
            self._set_head(chat_id, new_head)
        self.db.execute("DELETE FROM messages WHERE id=?", (msg_id,))  # каскад по parent_id
        self.db.commit()
        self.touch(chat_id)
        return chat_id

    # ------------------------------------------------ данные для генерации
    def chat_row(self, chat_id: int) -> sqlite3.Row:
        return self._chat_row(chat_id)

    def msg_row(self, msg_id: int) -> sqlite3.Row:
        return self._msg_row(msg_id)

    def history_rows(self, chat_id: int, until_id) -> list:
        """Сообщения ветки от корня до until_id включительно, пригодные для контекста."""
        rows = []
        for mid in self.path(chat_id, until_id):
            m = self._msg_row(mid)
            if m["status"] == "error":
                continue
            if not m["content"].strip() and not json.loads(m["meta"]).get("images"):
                continue
            rows.append(m)
        return rows

    def set_tokens(self, msg_id: int, n: int):
        self.db.execute("UPDATE messages SET tokens=? WHERE id=?", (n, msg_id))
        self.db.commit()

    def save_progress(self, msg_id: int, content: str, reasoning: str):
        self.db.execute("UPDATE messages SET content=?, reasoning=?, updated=? WHERE id=?",
                        (content, reasoning, time.time(), msg_id))
        self.db.commit()

    def finish(self, msg_id: int, content: str, reasoning: str, status: str,
               error=None, usage=None, meta=None):
        usage = usage or {}
        self.db.execute(
            "UPDATE messages SET content=?, reasoning=?, status=?, error=?, prompt_tokens=?, "
            "completion_tokens=?, meta=?, tokens=NULL, updated=? WHERE id=?",
            (content, reasoning, status, error, usage.get("prompt_tokens"),
             usage.get("completion_tokens"), json.dumps(meta or {}), time.time(), msg_id))
        self.db.commit()

    # ---------------------------------------------------------------- факты
    def _fact_row(self, fact_id: int) -> sqlite3.Row:
        r = self.db.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
        if not r:
            raise NotFound(f"факт {fact_id} не найден")
        return r

    @staticmethod
    def _fact_dict(r) -> dict:
        return {"id": r["id"], "chat_id": r["chat_id"], "text": r["text"],
                "pinned": bool(r["pinned"]), "auto": bool(r["auto"])}

    def facts(self, chat_id: int) -> list:
        return [self._fact_dict(r) for r in self.db.execute(
            "SELECT * FROM facts WHERE chat_id=? ORDER BY pinned DESC, id", (chat_id,))]

    def add_fact(self, chat_id: int, text: str, pinned=False, auto=False) -> dict:
        self._chat_row(chat_id)
        text = " ".join(str(text).split())
        if not text:
            raise BadRequest("пустой факт")
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO facts(chat_id, text, pinned, auto, created, updated) VALUES(?,?,?,?,?,?)",
            (chat_id, text, int(pinned), int(auto), now, now))
        self.db.commit()
        return self._fact_dict(self._fact_row(cur.lastrowid))

    def update_fact(self, fact_id: int, text=None, pinned=None, by_model=False) -> dict:
        r = self._fact_row(fact_id)
        if text is not None:
            text = " ".join(str(text).split())
            if not text:
                raise BadRequest("пустой факт")
            # правка человеком делает факт «ручным» — модель его больше не трогает
            self.db.execute("UPDATE facts SET text=?, auto=?, updated=? WHERE id=?",
                            (text, r["auto"] if by_model else 0, time.time(), fact_id))
        if pinned is not None:
            self.db.execute("UPDATE facts SET pinned=?, updated=? WHERE id=?",
                            (int(bool(pinned)), time.time(), fact_id))
        self.db.commit()
        return self._fact_dict(self._fact_row(fact_id))

    def delete_fact(self, fact_id: int) -> int:
        r = self._fact_row(fact_id)
        self.db.execute("DELETE FROM facts WHERE id=?", (fact_id,))
        self.db.commit()
        return r["chat_id"]

    def memory_until(self, chat_id: int) -> int:
        return self._chat_row(chat_id)["memory_until"] or 0

    def set_memory_until(self, chat_id: int, msg_id: int):
        self.db.execute("UPDATE chats SET memory_until=? WHERE id=?", (msg_id, chat_id))
        self.db.commit()

    # --------------------------------------------------------------- хроника
    def chronicle_for(self, chat_id: int, path_ids: list):
        """Хроника, применимая к ветке: её until_id лежит на пути (или 0).
        Из подходящих — покрывающая больше всего."""
        pos = {mid: i for i, mid in enumerate(path_ids)}
        best, best_pos = None, -2
        for r in self.db.execute("SELECT * FROM chronicles WHERE chat_id=?", (chat_id,)):
            p = -1 if r["until_id"] == 0 else pos.get(r["until_id"])
            if p is not None and p > best_pos:
                best, best_pos = r, p
        if best is None:
            return None
        return {"id": best["id"], "until_id": best["until_id"], "text": best["text"]}

    def save_chronicle(self, chat_id: int, until_id: int, text: str, replace_id=None) -> dict:
        now = time.time()
        if replace_id:
            self.db.execute("UPDATE chronicles SET until_id=?, text=?, updated=? WHERE id=?",
                            (until_id, text, now, replace_id))
            cid = replace_id
        else:
            cid = self.db.execute(
                "INSERT INTO chronicles(chat_id, until_id, text, created, updated) VALUES(?,?,?,?,?)",
                (chat_id, until_id, text, now, now)).lastrowid
        self.db.commit()
        return {"id": cid, "until_id": until_id, "text": text}

    def edit_chronicle(self, chat_id: int, text: str) -> dict:
        """Правка хроники текущей ветки человеком."""
        path_ids = self.path(chat_id)
        cur = self.chronicle_for(chat_id, path_ids)
        text = text.strip()
        if cur:
            if not text:
                self.db.execute("DELETE FROM chronicles WHERE id=?", (cur["id"],))
                self.db.commit()
                return {}
            return self.save_chronicle(chat_id, cur["until_id"], text, replace_id=cur["id"])
        if not text:
            return {}
        return self.save_chronicle(chat_id, 0, text)
