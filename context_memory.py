"""Bounded, persistent history of messages actually delivered by Telegram."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


class ConversationMemory:
    def __init__(self, path, limit=20):
        self.path = Path(path)
        self.limit = limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS messages (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                scope TEXT NOT NULL, role TEXT NOT NULL,
                speaker TEXT NOT NULL, text TEXT,
                UNIQUE(chat_id, message_id))""")
            db.execute("CREATE INDEX IF NOT EXISTS history_scope ON messages(scope, sequence)")

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def scope_for(self, message):
        chat_id = message.chat_id
        thread = getattr(message, "message_thread_id", None)
        if message.chat.type == "private":
            return f"{chat_id}:private:{thread or 0}"
        if getattr(message, "is_topic_message", False) and thread:
            return f"{chat_id}:topic:{thread}"
        if getattr(message, "is_automatic_forward", False):
            return f"{chat_id}:post:{message.message_id}"
        reply = getattr(message, "reply_to_message", None)
        if reply:
            with self._connection() as db:
                known = db.execute(
                    "SELECT scope FROM messages WHERE chat_id=? AND message_id=?",
                    (chat_id, reply.message_id),
                ).fetchone()
            if known:
                return known[0]
            if getattr(reply, "is_automatic_forward", False):
                return f"{chat_id}:post:{reply.message_id}"
        if thread:
            return f"{chat_id}:thread:{thread}"
        if reply:
            # Without a known ancestor, keep this branch separate rather than
            # guessing that it belongs to another post or the general chat.
            return f"{chat_id}:reply:{reply.message_id}"
        return f"{chat_id}:general"

    @staticmethod
    def _content(message):
        text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        if getattr(message, "photo", None):
            text = "[Фото; в истории доступна только подпись] " + text
        elif not text:
            for kind, label in (("video", "Видео"), ("voice", "Голосовое сообщение"),
                                ("document", "Документ"), ("sticker", "Стикер")):
                if getattr(message, kind, None):
                    text = f"[{label}; содержимое недоступно]"
                    break
        return text[:2000]

    @staticmethod
    def _speaker(message, role):
        if role == "assistant":
            return "Бот"
        sender_chat = getattr(message, "sender_chat", None)
        user = getattr(message, "from_user", None)
        if sender_chat:
            return f"{sender_chat.title} (чат {sender_chat.id})"[:120]
        if user:
            return f"{user.full_name} (id {user.id})"[:120]
        return "Неизвестный участник"

    def record(self, message, scope=None, role="user"):
        scope = scope or self.scope_for(message)
        reply = getattr(message, "reply_to_message", None)
        with self._connection() as db:
            if reply:
                known = db.execute(
                    "SELECT scope FROM messages WHERE chat_id=? AND message_id=?",
                    (message.chat_id, reply.message_id),
                ).fetchone()
                if known is None:
                    self._insert(db, reply, scope, "user")
            self._insert(db, message, scope, role)
            db.execute("""UPDATE messages SET text=NULL WHERE scope=? AND sequence NOT IN
                (SELECT sequence FROM messages WHERE scope=? AND text IS NOT NULL
                 ORDER BY sequence DESC LIMIT ?)""", (scope, scope, self.limit))
            db.execute("""DELETE FROM messages WHERE chat_id=? AND sequence NOT IN
                (SELECT sequence FROM messages WHERE chat_id=?
                 ORDER BY sequence DESC LIMIT 2000)""", (message.chat_id, message.chat_id))
        return scope

    def _insert(self, db, message, scope, role):
        text = self._content(message)
        db.execute("""INSERT OR IGNORE INTO messages
            (chat_id,message_id,scope,role,speaker,text) VALUES (?,?,?,?,?,?)""",
            (message.chat_id, message.message_id, scope, role,
             self._speaker(message, role), text or None))

    def history(self, scope, exclude_message_id=None, max_chars=12000):
        with self._connection() as db:
            rows = db.execute("""SELECT role,speaker,text FROM messages
                WHERE scope=? AND text IS NOT NULL AND (? IS NULL OR message_id!=?)
                ORDER BY sequence DESC LIMIT ?""",
                (scope, exclude_message_id, exclude_message_id, self.limit)).fetchall()
        selected = []
        for role, speaker, text in rows:
            entry = {"role": role, "speaker": speaker, "text": text}
            candidate = [entry] + selected
            encoded = json.dumps(candidate, ensure_ascii=False)
            if len(encoded) > max_chars:
                break
            selected = candidate
        return json.dumps(selected, ensure_ascii=False)
