"""Conversation storage, always scoped to the signed-in user.

The pgvector store writes as the rag_api role, which may change only conversations and messages.
Without a database, an in-memory store keeps conversations until the process restarts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Protocol
import uuid

import psycopg

STATUSES = ("complete", "length", "cancelled", "failed")


class ConversationsUnavailable(Exception):
    """The database could not be reached."""


@dataclass
class StoredMessage:
    role: str
    content: str
    status: str
    sources: list[dict]


@dataclass
class Conversation:
    id: str
    title: str
    updated_at: str
    messages: list[StoredMessage] = field(default_factory=list)


class ConversationStore(Protocol):
    async def create(self, user: str, title: str) -> str: ...

    async def get(self, user: str, conversation_id: str) -> Conversation | None: ...

    async def list(self, user: str) -> list[Conversation]: ...

    async def add_message(self, user: str, conversation_id: str, message: StoredMessage) -> None: ...

    async def delete(self, user: str, conversation_id: str) -> bool: ...


def valid_id(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def history(conversation: Conversation) -> list[dict[str, str]]:
    """Question-and-answer turns whose answer finished, oldest first, for the prompt budget."""
    turns: list[dict[str, str]] = []
    messages = conversation.messages
    for question, answer in zip(messages, messages[1:]):
        if question.role == "user" and answer.role == "assistant" and answer.status in ("complete", "length") and answer.content:
            turns += [{"role": "user", "content": question.content}, {"role": "assistant", "content": answer.content}]
    return turns


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryConversationStore:
    def __init__(self):
        self.conversations: dict[str, tuple[str, Conversation]] = {}

    async def create(self, user, title):
        conversation = Conversation(str(uuid.uuid4()), title, now())
        self.conversations[conversation.id] = (user, conversation)
        return conversation.id

    async def get(self, user, conversation_id):
        owner, conversation = self.conversations.get(conversation_id, (None, None))
        return conversation if owner == user else None

    async def list(self, user):
        return sorted((c for owner, c in self.conversations.values() if owner == user), key=lambda c: c.updated_at, reverse=True)

    async def add_message(self, user, conversation_id, message):
        conversation = await self.get(user, conversation_id)
        if conversation is not None:
            conversation.messages.append(message)
            conversation.updated_at = now()

    async def delete(self, user, conversation_id):
        if await self.get(user, conversation_id) is None:
            return False
        del self.conversations[conversation_id]
        return True


class PgConversationStore:
    def __init__(self, conninfo: dict):
        self.conninfo = conninfo

    async def _run(self, work):
        try:
            async with await psycopg.AsyncConnection.connect(**self.conninfo, autocommit=True, connect_timeout=5) as db:
                return await work(db)
        except psycopg.Error as exc:
            raise ConversationsUnavailable(type(exc).__name__) from None

    async def create(self, user, title):
        conversation_id = str(uuid.uuid4())
        await self._run(lambda db: db.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)", (conversation_id, user, title)))
        return conversation_id

    async def get(self, user, conversation_id):
        async def work(db):
            row = await (await db.execute(
                "SELECT id, title, updated_at FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user))).fetchone()
            if row is None:
                return None
            rows = await (await db.execute(
                "SELECT role, content, status, citations FROM messages WHERE conversation_id = %s ORDER BY id",
                (conversation_id,))).fetchall()
            return Conversation(str(row[0]), row[1], row[2].isoformat(),
                                [StoredMessage(r[0], r[1], r[2], r[3] or []) for r in rows])
        return await self._run(work)

    async def list(self, user):
        async def work(db):
            rows = await (await db.execute(
                "SELECT id, title, updated_at FROM conversations WHERE user_id = %s ORDER BY updated_at DESC LIMIT 200",
                (user,))).fetchall()
            return [Conversation(str(r[0]), r[1], r[2].isoformat()) for r in rows]
        return await self._run(work)

    async def add_message(self, user, conversation_id, message):
        async def work(db):
            async with db.transaction():
                updated = await db.execute("UPDATE conversations SET updated_at = now() WHERE id = %s AND user_id = %s",
                                           (conversation_id, user))
                if updated.rowcount == 1:
                    await db.execute(
                        "INSERT INTO messages (conversation_id, role, content, status, citations) VALUES (%s, %s, %s, %s, %s)",
                        (conversation_id, message.role, message.content, message.status, json.dumps(message.sources)))
        await self._run(work)

    async def delete(self, user, conversation_id):
        async def work(db):
            result = await db.execute("DELETE FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user))
            return result.rowcount == 1
        return await self._run(work)
