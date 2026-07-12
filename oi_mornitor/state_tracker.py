"""
突破状态机 — SQLite 持久化。

状态流转：BREAKOUT_DETECTED → TRIGGER_SIGNAL（已发射）→ 冷却/过期
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oi_mornitor.config import BREAKOUT_STATE_DB, BREAKOUT_WATCH_MAX_SEC

STATUS_DETECTED = "BREAKOUT_DETECTED"
STATUS_TRIGGERED = "TRIGGER_SIGNAL"
STATUS_EXPIRED = "EXPIRED"


@dataclass
class BreakoutState:
    symbol: str
    status: str
    supply_wall: float
    detected_at: float
    categories: str
    last_kline_close_time: int
    trigger_emitted: bool


class BreakoutStateTracker:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or BREAKOUT_STATE_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS breakout_state (
                    symbol TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    supply_wall REAL NOT NULL,
                    detected_at REAL NOT NULL,
                    categories TEXT NOT NULL DEFAULT '',
                    last_kline_close_time INTEGER NOT NULL DEFAULT 0,
                    trigger_emitted INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, symbol: str) -> BreakoutState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM breakout_state WHERE symbol = ?", (symbol,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_state(row)

    def upsert_detected(
        self,
        symbol: str,
        supply_wall: float,
        categories: str,
        kline_close_time: int,
    ) -> None:
        now = time.time()
        existing = self.get(symbol)
        with self._connect() as conn:
            if existing is None or existing.status in (STATUS_EXPIRED, STATUS_TRIGGERED):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO breakout_state
                        (symbol, status, supply_wall, detected_at, categories,
                         last_kline_close_time, trigger_emitted, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (symbol, STATUS_DETECTED, supply_wall, now, categories, kline_close_time, now),
                )
            elif existing.status == STATUS_DETECTED:
                wall_changed = abs(existing.supply_wall - supply_wall) > 1e-8
                conn.execute(
                    """
                    UPDATE breakout_state
                    SET supply_wall = ?, categories = ?, detected_at = ?,
                        last_kline_close_time = ?, trigger_emitted = ?,
                        updated_at = ?
                    WHERE symbol = ?
                    """,
                    (
                        supply_wall,
                        categories,
                        now if wall_changed else existing.detected_at,
                        kline_close_time,
                        0 if wall_changed else int(existing.trigger_emitted),
                        now,
                        symbol,
                    ),
                )
            conn.commit()

    def mark_triggered(self, symbol: str, kline_close_time: int) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE breakout_state
                SET status = ?, trigger_emitted = 1, last_kline_close_time = ?, updated_at = ?
                WHERE symbol = ?
                """,
                (STATUS_TRIGGERED, kline_close_time, now, symbol),
            )
            conn.commit()

    def list_watching(self) -> list[BreakoutState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM breakout_state WHERE status = ?",
                (STATUS_DETECTED,),
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def expire_stale(self, max_age_sec: float = BREAKOUT_WATCH_MAX_SEC) -> int:
        cutoff = time.time() - max_age_sec
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE breakout_state
                SET status = ?, updated_at = ?
                WHERE status = ? AND detected_at < ?
                """,
                (STATUS_EXPIRED, time.time(), STATUS_DETECTED, cutoff),
            )
            conn.commit()
            return cur.rowcount

    def prune_old(self, keep_days: int = 7) -> int:
        cutoff = time.time() - keep_days * 86400
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM breakout_state WHERE updated_at < ? AND status != ?",
                (cutoff, STATUS_DETECTED),
            )
            conn.commit()
            return cur.rowcount

    @staticmethod
    def _row_to_state(row: sqlite3.Row | dict[str, Any]) -> BreakoutState:
        return BreakoutState(
            symbol=str(row["symbol"]),
            status=str(row["status"]),
            supply_wall=float(row["supply_wall"]),
            detected_at=float(row["detected_at"]),
            categories=str(row["categories"] or ""),
            last_kline_close_time=int(row["last_kline_close_time"] or 0),
            trigger_emitted=bool(row["trigger_emitted"]),
        )
