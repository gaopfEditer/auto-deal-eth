"""形态追踪状态机 + 自选币种列表 — SQLite 持久化。"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oi_mornitor.config import PATTERN_PIN_TTL_SEC, PATTERN_STATE_DB, PATTERN_WATCH_MAX_SEC
from oi_mornitor.pattern_detector import (
    STATUS_EXPIRED,
    STATUS_LH,
    STATUS_SEARCHING,
    STATUS_TRIGGER,
    STATUS_WAITING,
)

MAX_WATCH_SYMBOLS = 30


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


@dataclass
class PatternWatchItem:
    symbol: str
    interval: str
    added_at: float
    pinned_until: float = 0.0

    @property
    def is_pinned(self) -> bool:
        return self.pinned_until > time.time()


@dataclass
class PatternStateRow:
    symbol: str
    status: str
    h_max: float
    lh_price: float
    l1: float
    hl: float
    trigger_price: float
    hh_price: float
    last_kline_close_time: int
    trigger_emitted: bool
    updated_at: float
    message: str = ""


class PatternStateTracker:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or PATTERN_STATE_DB
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
                CREATE TABLE IF NOT EXISTS pattern_watchlist (
                    symbol TEXT PRIMARY KEY,
                    interval TEXT NOT NULL DEFAULT '15m',
                    added_at REAL NOT NULL,
                    pinned_until REAL NOT NULL DEFAULT 0
                )
                """
            )
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(pattern_watchlist)").fetchall()
            }
            if "pinned_until" not in cols:
                conn.execute(
                    "ALTER TABLE pattern_watchlist ADD COLUMN pinned_until REAL NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pattern_state (
                    symbol TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    h_max REAL NOT NULL DEFAULT 0,
                    lh_price REAL NOT NULL DEFAULT 0,
                    l1 REAL NOT NULL DEFAULT 0,
                    hl REAL NOT NULL DEFAULT 0,
                    trigger_price REAL NOT NULL DEFAULT 0,
                    hh_price REAL NOT NULL DEFAULT 0,
                    last_kline_close_time INTEGER NOT NULL DEFAULT 0,
                    trigger_emitted INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()
            self._repair_corrupt_rows(conn)

    def _repair_corrupt_rows(self, conn: sqlite3.Connection) -> None:
        """修复早期错误写入导致数值列存了 status 字符串的脏数据。"""
        rows = conn.execute("SELECT symbol, h_max, updated_at FROM pattern_state").fetchall()
        for row in rows:
            bad = False
            for key in ("h_max", "updated_at"):
                try:
                    float(row[key])
                except (TypeError, ValueError):
                    bad = True
                    break
            if bad:
                conn.execute(
                    """
                    UPDATE pattern_state
                    SET status = ?, h_max = 0, lh_price = 0, l1 = 0, hl = 0,
                        trigger_price = 0, hh_price = 0, last_kline_close_time = 0,
                        trigger_emitted = 0, message = '', updated_at = ?
                    WHERE symbol = ?
                    """,
                    (STATUS_SEARCHING, time.time(), row["symbol"]),
                )
        conn.commit()

    def _insert_fresh_state(self, conn: sqlite3.Connection, sym: str, now: float) -> None:
        conn.execute(
            """
            INSERT INTO pattern_state
                (symbol, status, h_max, lh_price, l1, hl, trigger_price, hh_price,
                 last_kline_close_time, trigger_emitted, message, updated_at)
            VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, 0, '', ?)
            """,
            (sym, STATUS_SEARCHING, now),
        )

    def list_watchlist(self) -> list[PatternWatchItem]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM pattern_watchlist
                ORDER BY
                    CASE WHEN pinned_until > ? THEN 0 ELSE 1 END ASC,
                    pinned_until DESC,
                    added_at ASC
                """,
                (now,),
            ).fetchall()
        return [
            PatternWatchItem(
                symbol=r["symbol"],
                interval=r["interval"],
                added_at=_safe_float(r["added_at"]),
                pinned_until=_safe_float(r["pinned_until"] if "pinned_until" in r.keys() else 0),
            )
            for r in rows
        ]

    def add_watch(self, symbol: str, interval: str = "15m") -> bool:
        sym = symbol.strip().upper()
        if not sym:
            return False
        now = time.time()
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM pattern_watchlist").fetchone()[0]
            exists = conn.execute(
                "SELECT 1 FROM pattern_watchlist WHERE symbol = ?", (sym,)
            ).fetchone()
            if not exists and count >= MAX_WATCH_SYMBOLS:
                return False
            conn.execute(
                """
                INSERT INTO pattern_watchlist (symbol, interval, added_at, pinned_until)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(symbol) DO NOTHING
                """,
                (sym, interval, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO pattern_state
                    (symbol, status, h_max, lh_price, l1, hl, trigger_price, hh_price,
                     last_kline_close_time, trigger_emitted, message, updated_at)
                VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, 0, '', ?)
                """,
                (sym, STATUS_SEARCHING, now),
            )
            conn.commit()
        return True

    def remove_watch(self, symbol: str) -> bool:
        sym = symbol.strip().upper()
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM pattern_watchlist WHERE symbol = ?", (sym,))
            conn.execute("DELETE FROM pattern_state WHERE symbol = ?", (sym,))
            conn.commit()
            return cur.rowcount > 0

    def pin_watch(self, symbol: str, *, ttl_sec: float | None = None) -> bool:
        """手动置顶：维持至少 ttl_sec（默认一天），到期自动失效。"""
        sym = symbol.strip().upper()
        if not sym:
            return False
        ttl = float(ttl_sec if ttl_sec is not None else PATTERN_PIN_TTL_SEC)
        until = time.time() + max(1.0, ttl)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM pattern_watchlist WHERE symbol = ?", (sym,)
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                "UPDATE pattern_watchlist SET pinned_until = ? WHERE symbol = ?",
                (until, sym),
            )
            conn.commit()
        return True

    def unpin_watch(self, symbol: str) -> bool:
        """手动取消置顶。"""
        sym = symbol.strip().upper()
        if not sym:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE pattern_watchlist SET pinned_until = 0 WHERE symbol = ? AND pinned_until > 0",
                (sym,),
            )
            conn.commit()
            return cur.rowcount > 0

    def expire_pins(self) -> int:
        """清除已到期的置顶标记。"""
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE pattern_watchlist SET pinned_until = 0 WHERE pinned_until > 0 AND pinned_until <= ?",
                (now,),
            )
            conn.commit()
            return cur.rowcount

    def bump_watch_to_top(self, symbol: str) -> bool:
        """软置顶：仅调整排序（不设 sticky pin），供自动入池用。"""
        sym = symbol.strip().upper()
        if not sym:
            return False
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM pattern_watchlist WHERE symbol = ?", (sym,)
            ).fetchone()
            if not exists:
                return False
            min_at = conn.execute("SELECT MIN(added_at) FROM pattern_watchlist").fetchone()[0]
            new_at = (float(min_at) if min_at is not None else time.time()) - 1.0
            conn.execute(
                "UPDATE pattern_watchlist SET added_at = ? WHERE symbol = ?",
                (new_at, sym),
            )
            conn.commit()
        return True

    def pin_watch_to_top(self, symbol: str) -> bool:
        """兼容旧调用：改为 sticky 置顶一天。"""
        return self.pin_watch(symbol)

    def clear_watchlist(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pattern_watchlist")
            conn.execute("DELETE FROM pattern_state")
            conn.commit()

    def replace_watchlist(self, symbols: list[str], interval: str = "15m") -> int:
        """清空并批量写入监听列表，返回实际写入数量。"""
        unique = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))[:MAX_WATCH_SYMBOLS]
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM pattern_watchlist")
            conn.execute("DELETE FROM pattern_state")
            for sym in unique:
                conn.execute(
                    """
                    INSERT INTO pattern_watchlist (symbol, interval, added_at, pinned_until)
                    VALUES (?, ?, ?, 0)
                    """,
                    (sym, interval, now),
                )
                self._insert_fresh_state(conn, sym, now)
            conn.commit()
        return len(unique)

    def get_state(self, symbol: str) -> PatternStateRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pattern_state WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if not row:
            return None
        return self._row_to_state(row)

    def list_states(self) -> list[PatternStateRow]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ps.* FROM pattern_state ps
                INNER JOIN pattern_watchlist pw ON pw.symbol = ps.symbol
                ORDER BY
                    CASE WHEN pw.pinned_until > ? THEN 0 ELSE 1 END ASC,
                    pw.pinned_until DESC,
                    pw.added_at ASC
                """,
                (now,),
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def save_state(
        self,
        symbol: str,
        *,
        status: str,
        h_max: float = 0.0,
        lh_price: float = 0.0,
        l1: float = 0.0,
        hl: float = 0.0,
        trigger_price: float = 0.0,
        hh_price: float = 0.0,
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
                INSERT INTO pattern_state
                    (symbol, status, h_max, lh_price, l1, hl, trigger_price, hh_price,
                     last_kline_close_time, trigger_emitted, message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    status = excluded.status,
                    h_max = excluded.h_max,
                    lh_price = excluded.lh_price,
                    l1 = excluded.l1,
                    hl = excluded.hl,
                    trigger_price = excluded.trigger_price,
                    hh_price = excluded.hh_price,
                    last_kline_close_time = excluded.last_kline_close_time,
                    trigger_emitted = excluded.trigger_emitted,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol.upper(),
                    status,
                    h_max,
                    lh_price,
                    l1,
                    hl,
                    trigger_price,
                    hh_price,
                    kline_close_time,
                    emitted,
                    message,
                    now,
                ),
            )
            conn.commit()

    def mark_triggered(self, symbol: str, kline_close_time: int) -> None:
        state = self.get_state(symbol)
        if not state:
            return
        self.save_state(
            symbol,
            status=STATUS_TRIGGER,
            h_max=state.h_max,
            lh_price=state.lh_price,
            l1=state.l1,
            hl=state.hl,
            trigger_price=state.trigger_price,
            hh_price=state.hh_price,
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

    def expire_stale(self, max_age_sec: float = PATTERN_WATCH_MAX_SEC) -> int:
        cutoff = time.time() - max_age_sec
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE pattern_state
                SET status = ?, message = '观察超时', updated_at = ?
                WHERE status IN (?, ?) AND updated_at < ?
                """,
                (STATUS_EXPIRED, time.time(), STATUS_LH, STATUS_WAITING, cutoff),
            )
            conn.commit()
            return cur.rowcount

    @staticmethod
    def _row_to_state(row: sqlite3.Row | dict[str, Any]) -> PatternStateRow:
        return PatternStateRow(
            symbol=str(row["symbol"]),
            status=str(row["status"]),
            h_max=_safe_float(row["h_max"]),
            lh_price=_safe_float(row["lh_price"]),
            l1=_safe_float(row["l1"]),
            hl=_safe_float(row["hl"]),
            trigger_price=_safe_float(row["trigger_price"]),
            hh_price=_safe_float(row["hh_price"]),
            last_kline_close_time=_safe_int(row["last_kline_close_time"]),
            trigger_emitted=bool(row["trigger_emitted"]),
            updated_at=_safe_float(row["updated_at"]),
            message=str(row["message"] or ""),
        )
