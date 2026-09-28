"""
Live text from a worker to a waiting HTTP request, over Postgres NOTIFY.

A patient's message is answered inside a Temporal activity, in another
process, while the gateway holds the patient's request open. The activity
publishes each piece of the reply to a channel named after a stream id the
gateway chose; the gateway LISTENs on that channel and relays the pieces to
the browser as they come. Postgres is already there, works across processes
and replicas, and needs no table or privilege for this.

Best effort by design: a lost piece costs only the typing effect, never the
reply, which the request still receives whole when the turn ends.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from sqlalchemy import text

from nafas_core.config import get_setting
from nafas_core.db.session import get_engine
from nafas_core.logger import get_logger

logger = get_logger(__name__)

# NOTIFY payloads are capped at 8000 bytes; pieces are far smaller, but split to be safe
MAX_PIECE_CHARS = 1500
_STREAM_ID = re.compile(r"^[0-9a-f]{32}$")


def channel(stream_id: str) -> str:
    """The channel for one stream. Stream ids are uuid hex, so the name is a safe identifier."""
    if not _STREAM_ID.match(stream_id):
        raise ValueError("a stream id is 32 lowercase hex characters")
    return f"nafas_stream_{stream_id}"


async def publish(stream_id: str, event: dict[str, Any]) -> None:
    """Sends one event to whoever listens on the stream; never raises (the reply does not depend on it)."""
    events = [event]
    if event.get("type") == "delta" and len(event.get("text", "")) > MAX_PIECE_CHARS:
        piece = event["text"]
        events = [{"type": "delta", "text": piece[i : i + MAX_PIECE_CHARS]} for i in range(0, len(piece), MAX_PIECE_CHARS)]
    try:
        async with get_engine().connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            for item in events:
                await connection.execute(
                    text("SELECT pg_notify(:channel, :payload)"),
                    {"channel": channel(stream_id), "payload": json.dumps(item, ensure_ascii=False)},
                )
    except Exception:
        logger.warning("could not publish to stream %s", stream_id, exc_info=True)


def _asyncpg_dsn(url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)


@asynccontextmanager
async def listen(stream_id: str) -> AsyncIterator[asyncio.Queue]:
    """
    A queue that receives the stream's events. Enter it before starting the
    work that publishes, so the first piece is not missed.
    """
    queue: asyncio.Queue = asyncio.Queue()

    def received(_connection, _pid, _channel, payload: str) -> None:
        try:
            queue.put_nowait(json.loads(payload))
        except json.JSONDecodeError:
            logger.warning("dropped an unreadable stream event")

    connection = await asyncpg.connect(_asyncpg_dsn(get_setting().database_url))
    name = channel(stream_id)
    try:
        await connection.add_listener(name, received)
        yield queue
    finally:
        try:
            await connection.remove_listener(name, received)
        finally:
            await connection.close()
