"""回踩策略状态机 — SQLite 持久化（与形态页共用 watchlist）。"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oi_mornitor.config import STRATEGY_STATE_DB, STRATEGY_WATCH_MAX_SEC
from oi_mornitor.strategy.pullback import (
    STATUS_BREAKOUT,
    STATUS_EXPIRED,
    STATUS_REVERSAL_WATCH,
    STATUS_SEARCHING,
    STATUS_TRIGGER,
    STATUS_WAIT_PULLBACK,
)


@dataclass
class PullbackStateRow:
    symbol: str
    status: str
    signal_type: str
    supply_wall: float
    anchor_level: float
    anchor_kind: str
    last_kline_close_time: int
    trigger_emitted: bool
    updated_at: float
    message: str = ""


class PullbackStateTracker:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or STRATEGY_STATE_DB
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
                CREATE TABLE IF NOT EXISTS pullback_state (
                    symbol TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    signal_type TEXT NOT NULL DEFAULT '',
                    supply_wall REAL NOT NULL DEFAULT 0,
                    anchor_level REAL NOT NULL DEFAULT 0,
                    anchor_kind TEXT NOT NULL DEFAULT '',
                    last_kline_close_time INTEGER NOT NULL DEFAULT 0,
                    trigger_emitted INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def get_state(self, symbol: str) -> PullbackStateRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pullback_state WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if not row:
            return None
        return self._row_to_state(row)

    def ensure_symbol(self, symbol: str) -> None:
        sym = symbol.upper()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO pullback_state
                    (symbol, status, signal_type, supply_wall, anchor_level, anchor_kind,
                     last_kline_close_time, trigger_emitted, message, updated_at)
                VALUES (?, ?, '', 0, 0, '', 0, 0, '', ?)
                """,
                (sym, STATUS_SEARCHING, now),
            )
            conn.commit()

    def save_state(
        self,
        symbol: str,
        *,
        status: str,
        signal_type: str = "",
        supply_wall: float = 0.0,
        anchor_level: float = 0.0,
        anchor_kind: str = "",
        kline_close_time: int = 0,
        message: str = "",
        trigger_emitted: bool | None = None,
    ) -> None:
        now = time.time()
        existing = self.get_state(symbol)
        emitted = (
            int(trigger_emitted)
            if trigger_emitted is not None
            else (existing.trigger_emitted if existing else 0)
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pullback_state
                    (symbol, status, signal_type, supply_wall, anchor_level, anchor_kind,
                     last_kline_close_time, trigger_emitted, message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    status = excluded.status,
                    signal_type = excluded.signal_type,
                    supply_wall = excluded.supply_wall,
                    anchor_level = excluded.anchor_level,
                    anchor_kind = excluded.anchor_kind,
                    last_kline_close_time = excluded.last_kline_close_time,
                    trigger_emitted = excluded.trigger_emitted,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol.upper(),
                    status,
                    signal_type,
                    supply_wall,
                    anchor_level,
                    anchor_kind,
                    kline_close_time,
                    emitted,
                    message,
                    now,
                ),
            )
            conn.commit()

    def mark_triggered(self, symbol: str, kline_close_time: int, signal_type: str) -> None:
        state = self.get_state(symbol)
        if not state:
            return
        self.save_state(
            symbol,
            status=STATUS_TRIGGER,
            signal_type=signal_type,
            supply_wall=state.supply_wall,
            anchor_level=state.anchor_level,
            anchor_kind=state.anchor_kind,
            kline_close_time=kline_close_time,
            message=state.message,
            trigger_emitted=True,
        )

    def reset_symbol(self, symbol: str) -> None:
        self.save_state(
            symbol,
            status=STATUS_SEARCHING,
            kline_close_time=0,
            message="",
            trigger_emitted=False,
        )

    def expire_stale(self, max_age_sec: float = STRATEGY_WATCH_MAX_SEC) -> int:
        cutoff = time.time() - max_age_sec
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE pullback_state
                SET status = ?, message = '观察超时', updated_at = ?
                WHERE status IN (?, ?, ?) AND updated_at < ?
                """,
                (
                    STATUS_EXPIRED,
                    time.time(),
                    STATUS_BREAKOUT,
                    STATUS_WAIT_PULLBACK,
                    STATUS_REVERSAL_WATCH,
                    cutoff,
                ),
            )
            conn.commit()
            return cur.rowcount

    @staticmethod
    def _row_to_state(row: sqlite3.Row | dict[str, Any]) -> PullbackStateRow:
        return PullbackStateRow(
            symbol=str(row["symbol"]),
            status=str(row["status"]),
            signal_type=str(row["signal_type"] or ""),
            supply_wall=float(row["supply_wall"] or 0),
            anchor_level=float(row["anchor_level"] or 0),
            anchor_kind=str(row["anchor_kind"] or ""),
            last_kline_close_time=int(row["last_kline_close_time"] or 0),
            trigger_emitted=bool(row["trigger_emitted"]),
            updated_at=float(row["updated_at"] or 0),
            message=str(row["message"] or ""),
        )
