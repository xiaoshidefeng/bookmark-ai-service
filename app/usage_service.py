import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings


@dataclass(frozen=True)
class UsageSnapshot:
    limit: int
    used: int
    remaining: int
    date: str


class DailyLimitExceededError(Exception):
    def __init__(self, snapshot: UsageSnapshot):
        super().__init__("Daily request limit exceeded")
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
            CREATE TABLE IF NOT EXISTS daily_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id TEXT NOT NULL,
              usage_date TEXT NOT NULL,
              request_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(client_id, usage_date)
            )
            """
        )
        connection.commit()


async def init_usage_db() -> None:
    await asyncio.to_thread(_init_db_sync)


def _get_usage_sync(client_id: str) -> UsageSnapshot:
    today = _get_today()
    _init_db_sync()
    with _get_connection() as connection:
        row = connection.execute(
            "SELECT request_count FROM daily_usage WHERE client_id = ? AND usage_date = ?",
            (client_id, today),
        ).fetchone()
    used = int(row["request_count"]) if row else 0
    remaining = max(0, settings.daily_limit - used)
    return UsageSnapshot(limit=settings.daily_limit, used=used, remaining=remaining, date=today)


async def get_usage(client_id: str) -> UsageSnapshot:
    async with _db_lock:
        return await asyncio.to_thread(_get_usage_sync, client_id)


def _consume_quota_sync(client_id: str) -> UsageSnapshot:
    today = _get_today()
    now_timestamp = _get_now_timestamp()
    _init_db_sync()
    with _get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT request_count FROM daily_usage WHERE client_id = ? AND usage_date = ?",
            (client_id, today),
        ).fetchone()
        current = int(row["request_count"]) if row else 0

        if current >= settings.daily_limit:
            connection.rollback()
            return UsageSnapshot(
                limit=settings.daily_limit,
                used=current,
                remaining=0,
                date=today,
            )

        next_count = current + 1
        if row:
            connection.execute(
                """
                UPDATE daily_usage
                SET request_count = ?, updated_at = ?
                WHERE client_id = ? AND usage_date = ?
                """,
                (next_count, now_timestamp, client_id, today),
            )
        else:
            connection.execute(
                """
                INSERT INTO daily_usage (client_id, usage_date, request_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (client_id, today, next_count, now_timestamp, now_timestamp),
            )
        connection.commit()

    return UsageSnapshot(
        limit=settings.daily_limit,
        used=next_count,
        remaining=max(0, settings.daily_limit - next_count),
        date=today,
    )


async def consume_quota(client_id: str) -> UsageSnapshot:
    async with _db_lock:
        snapshot = await asyncio.to_thread(_consume_quota_sync, client_id)
    if snapshot.used >= settings.daily_limit and snapshot.remaining == 0:
        return snapshot
    return snapshot


async def enforce_daily_limit(client_id: str) -> UsageSnapshot:
    before = await get_usage(client_id)
    if before.used >= settings.daily_limit:
        raise DailyLimitExceededError(before)
    snapshot = await consume_quota(client_id)
    if snapshot.used > settings.daily_limit:
        raise DailyLimitExceededError(snapshot)
    return snapshot
