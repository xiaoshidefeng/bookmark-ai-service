import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings


@dataclass(frozen=True)
class FeedbackSnapshot:
    limit: int
    used: int
    date: str


class FeedbackLimitExceededError(Exception):
    def __init__(self, snapshot: FeedbackSnapshot):
        super().__init__("Daily feedback limit exceeded")
        self.snapshot = snapshot


_db_lock = asyncio.Lock()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _get_today() -> str:
    return datetime.now(SHANGHAI_TZ).date().isoformat()


def _get_now_timestamp() -> str:
    return datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _get_connection() -> sqlite3.Connection:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db_sync() -> None:
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id TEXT NOT NULL,
              content TEXT NOT NULL,
              contact TEXT,
              locale TEXT,
              app_version TEXT,
              feedback_date TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


async def init_feedback_db() -> None:
    await asyncio.to_thread(_init_db_sync)


def _submit_feedback_sync(
    client_id: str,
    content: str,
    contact: str | None,
    locale: str | None,
    app_version: str | None,
) -> int:
    today = _get_today()
    now_timestamp = _get_now_timestamp()
    _init_db_sync()
    with _get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT COUNT(*) AS used FROM feedback WHERE client_id = ? AND feedback_date = ?",
            (client_id, today),
        ).fetchone()
        used = int(row["used"]) if row else 0
        if used >= settings.feedback_daily_limit:
            connection.rollback()
            raise FeedbackLimitExceededError(
                FeedbackSnapshot(limit=settings.feedback_daily_limit, used=used, date=today)
            )

        cursor = connection.execute(
            """
            INSERT INTO feedback (client_id, content, contact, locale, app_version, feedback_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (client_id, content, contact, locale, app_version, today, now_timestamp),
        )
        connection.commit()
        return int(cursor.lastrowid)


async def submit_feedback(
    client_id: str,
    content: str,
    contact: str | None = None,
    locale: str | None = None,
    app_version: str | None = None,
) -> int:
    async with _db_lock:
        return await asyncio.to_thread(
            _submit_feedback_sync, client_id, content, contact, locale, app_version
        )
