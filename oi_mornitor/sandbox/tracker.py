"""沙盒 SQLite：日池 / 持仓 / 成交 / 账户。"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from oi_mornitor.config import SANDBOX_INITIAL_BALANCE, SANDBOX_INTERVAL, SANDBOX_STATE_DB
from oi_mornitor.sandbox.logics import (
    entry_source_label,
    ref_intervals_for_logic,
    resolve_entry_source,
    sandbox_leverage,
)


@dataclass
class PaperPosition:
    symbol: str
    side: str
    logic: str
    size: float
    entry_price: float
    entry_time: int
    sl: float
    tp1: float | None
    tp2: float | None
    breakeven_armed: bool
    meta_json: str
    id: int = 0


class SandboxTracker:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or SANDBOX_STATE_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_pool (
                    day TEXT PRIMARY KEY,
                    symbols_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    logic TEXT NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time INTEGER NOT NULL,
                    sl REAL NOT NULL,
                    tp1 REAL,
                    tp2 REAL,
                    breakeven_armed INTEGER NOT NULL DEFAULT 0,
                    meta_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    logic TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    entry_time INTEGER NOT NULL,
                    exit_time INTEGER NOT NULL,
                    size REAL NOT NULL,
                    pnl_usd REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    reason TEXT NOT NULL,
                    day TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_day ON trades(day);
                CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
                """
            )
            self._migrate_positions_pk(conn)
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(trades)").fetchall()
            }
            if "leverage" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN leverage REAL NOT NULL DEFAULT 30"
                )
            if "roe_pct" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN roe_pct REAL NOT NULL DEFAULT 0"
                )
            if "events_json" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN events_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "is_partial" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN is_partial INTEGER NOT NULL DEFAULT 0"
                )
            if "entry_reason" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN entry_reason TEXT NOT NULL DEFAULT ''"
                )
            if "interval" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN interval TEXT NOT NULL DEFAULT '15m'"
                )
            if "ref_intervals" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN ref_intervals TEXT NOT NULL DEFAULT '15m'"
                )
            if "source" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN source TEXT NOT NULL DEFAULT 'auto'"
                )
            if "exit_code" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN exit_code TEXT NOT NULL DEFAULT ''"
                )
            if "exit_label" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN exit_label TEXT NOT NULL DEFAULT ''"
                )
            if "fee_usd" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN fee_usd REAL NOT NULL DEFAULT 0"
                )
            if "fee_pct" not in cols:
                conn.execute(
                    "ALTER TABLE trades ADD COLUMN fee_pct REAL NOT NULL DEFAULT 0"
                )
            row = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO account (id, balance, updated_at) VALUES (1, ?, ?)",
                    (SANDBOX_INITIAL_BALANCE, time.time()),
                )

    def _migrate_positions_pk(self, conn: sqlite3.Connection) -> None:
        """旧表 symbol PRIMARY KEY → 新表 id AUTOINCREMENT（支持同币多仓）。"""
        info = conn.execute("PRAGMA table_info(positions)").fetchall()
        if not info:
            return
        cols = {str(r[1]): r for r in info}
        pk_cols = [str(r[1]) for r in info if int(r[5] or 0) == 1]
        # 已是 id 主键
        if pk_cols == ["id"] and "symbol" in cols:
            return
        # 旧版：symbol 为主键
        if "symbol" in cols and ("id" not in cols or pk_cols == ["symbol"]):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    logic TEXT NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time INTEGER NOT NULL,
                    sl REAL NOT NULL,
                    tp1 REAL,
                    tp2 REAL,
                    breakeven_armed INTEGER NOT NULL DEFAULT 0,
                    meta_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO positions_v2 (
                    symbol, side, logic, size, entry_price, entry_time,
                    sl, tp1, tp2, breakeven_armed, meta_json
                )
                SELECT
                    symbol, side, logic, size, entry_price, entry_time,
                    sl, tp1, tp2, breakeven_armed, meta_json
                FROM positions
                """
            )
            conn.execute("DROP TABLE positions")
            conn.execute("ALTER TABLE positions_v2 RENAME TO positions")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)"
            )

    def get_balance(self) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
            return float(row["balance"]) if row else SANDBOX_INITIAL_BALANCE

    def set_balance(self, balance: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE account SET balance = ?, updated_at = ? WHERE id = 1",
                (balance, time.time()),
            )

    def get_daily_pool(self, day: str | None = None) -> list[str] | None:
        day = day or date.today().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT symbols_json FROM daily_pool WHERE day = ?", (day,)
            ).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["symbols_json"])
                return [str(s).upper() for s in data] if isinstance(data, list) else None
            except json.JSONDecodeError:
                return None

    def set_daily_pool(self, symbols: list[str], day: str | None = None) -> None:
        day = day or date.today().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_pool (day, symbols_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    symbols_json = excluded.symbols_json,
                    created_at = excluded.created_at
                """,
                (day, json.dumps([s.upper() for s in symbols]), time.time()),
            )

    def list_positions(self) -> list[PaperPosition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions ORDER BY entry_time ASC, id ASC"
            ).fetchall()
        return [self._row_to_pos(r) for r in rows]

    def list_positions_for_symbol(self, symbol: str) -> list[PaperPosition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE symbol = ? ORDER BY entry_time ASC, id ASC",
                (symbol.upper(),),
            ).fetchall()
        return [self._row_to_pos(r) for r in rows]

    def get_position(self, symbol: str) -> PaperPosition | None:
        """兼容：返回该币最早一笔持仓。"""
        rows = self.list_positions_for_symbol(symbol)
        return rows[0] if rows else None

    def get_position_by_id(self, pos_id: int) -> PaperPosition | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE id = ?", (int(pos_id),)
            ).fetchone()
        return self._row_to_pos(row) if row else None

    def insert_position(self, pos: PaperPosition) -> PaperPosition:
        """新开一笔仓（同币可多笔）。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO positions (
                    symbol, side, logic, size, entry_price, entry_time,
                    sl, tp1, tp2, breakeven_armed, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pos.symbol.upper(),
                    pos.side,
                    pos.logic,
                    pos.size,
                    pos.entry_price,
                    pos.entry_time,
                    pos.sl,
                    pos.tp1,
                    pos.tp2,
                    1 if pos.breakeven_armed else 0,
                    pos.meta_json,
                ),
            )
            pos.id = int(cur.lastrowid or 0)
        return pos

    def upsert_position(self, pos: PaperPosition) -> PaperPosition:
        """有 id 则更新；无 id 则插入新仓。"""
        if pos.id and pos.id > 0:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE positions SET
                        symbol=?, side=?, logic=?, size=?, entry_price=?, entry_time=?,
                        sl=?, tp1=?, tp2=?, breakeven_armed=?, meta_json=?
                    WHERE id=?
                    """,
                    (
                        pos.symbol.upper(),
                        pos.side,
                        pos.logic,
                        pos.size,
                        pos.entry_price,
                        pos.entry_time,
                        pos.sl,
                        pos.tp1,
                        pos.tp2,
                        1 if pos.breakeven_armed else 0,
                        pos.meta_json,
                        int(pos.id),
                    ),
                )
            return pos
        return self.insert_position(pos)

    def delete_position(self, symbol_or_id: str | int) -> None:
        """按仓位 id 删除；若传入 symbol 字符串则删除该币全部持仓（兼容旧调用）。"""
        with self._connect() as conn:
            if isinstance(symbol_or_id, int) or (
                isinstance(symbol_or_id, str) and symbol_or_id.isdigit()
            ):
                conn.execute(
                    "DELETE FROM positions WHERE id = ?", (int(symbol_or_id),)
                )
            else:
                conn.execute(
                    "DELETE FROM positions WHERE symbol = ?",
                    (str(symbol_or_id).upper(),),
                )

    def delete_position_by_id(self, pos_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM positions WHERE id = ?", (int(pos_id),))

    def add_trade(self, trade: dict[str, Any]) -> None:
        day = trade.get("day") or date.today().isoformat()
        lev = float(trade.get("leverage") or sandbox_leverage(str(trade["symbol"])))
        pnl_pct = float(trade["pnl_pct"])
        roe_pct = float(trade.get("roe_pct", pnl_pct * lev))
        events_json = trade.get("events_json")
        if events_json is None:
            events_json = "[]"
        elif not isinstance(events_json, str):
            events_json = json.dumps(events_json, ensure_ascii=False)
        refs = trade.get("ref_intervals")
        if isinstance(refs, list):
            refs_s = ",".join(str(x) for x in refs)
        else:
            refs_s = str(refs or "15m")
        source = resolve_entry_source(
            {
                "source": trade.get("source"),
                "source_label": trade.get("source_label"),
                "manual": trade.get("manual"),
                "entry_reason": trade.get("entry_reason"),
            }
        )
        exit_code = str(trade.get("exit_code") or "")
        exit_label = str(trade.get("exit_label") or "")
        if not exit_code and trade.get("reason"):
            # reason 形如 code|label|message
            parts = str(trade["reason"]).split("|", 2)
            if len(parts) >= 2 and parts[0] and not parts[0].startswith("partial_"):
                exit_code = parts[0]
                exit_label = exit_label or parts[1]
        if not exit_label and exit_code:
            from oi_mornitor.sandbox.logics import exit_reason_label as _erl

            exit_label = _erl(exit_code)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (
                    symbol, side, logic, entry_price, exit_price, entry_time, exit_time,
                    size, leverage, pnl_usd, pnl_pct, roe_pct, reason, day,
                    events_json, is_partial, entry_reason, interval, ref_intervals, source,
                    exit_code, exit_label, fee_usd, fee_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trade["symbol"]).upper(),
                    trade["side"],
                    trade["logic"],
                    float(trade["entry_price"]),
                    float(trade["exit_price"]),
                    int(trade["entry_time"]),
                    int(trade["exit_time"]),
                    float(trade["size"]),
                    lev,
                    float(trade["pnl_usd"]),
                    pnl_pct,
                    roe_pct,
                    str(trade.get("reason") or ""),
                    day,
                    events_json,
                    int(trade.get("is_partial") or 0),
                    str(trade.get("entry_reason") or ""),
                    str(trade.get("interval") or SANDBOX_INTERVAL or "15m"),
                    refs_s,
                    source,
                    exit_code,
                    exit_label,
                    float(trade.get("fee_usd") or 0),
                    float(trade.get("fee_pct") or 0),
                ),
            )

    def list_trades(
        self,
        *,
        symbol: str | None = None,
        day: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM trades"
        args: list[Any] = []
        where: list[str] = []
        if symbol:
            where.append("symbol = ?")
            args.append(symbol.upper())
        if day:
            where.append("day = ?")
            args.append(day)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY exit_time DESC LIMIT ?"
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._normalize_trade(dict(r)) for r in rows]

    def stats(self, day: str | None = None) -> dict[str, Any]:
        day = day or date.today().isoformat()
        with self._connect() as conn:
            trades = [
                self._normalize_trade(dict(r))
                for r in conn.execute(
                    "SELECT * FROM trades WHERE day = ? ORDER BY exit_time DESC",
                    (day,),
                ).fetchall()
            ]
            open_n = conn.execute("SELECT COUNT(*) AS n FROM positions").fetchone()["n"]
        wins = [t for t in trades if float(t["pnl_usd"]) > 0]
        losses = [t for t in trades if float(t["pnl_usd"]) <= 0]
        by_logic: dict[str, dict[str, Any]] = {}
        for t in trades:
            logic = str(t.get("logic") or "?")
            bucket = by_logic.setdefault(
                logic, {"trades": 0, "wins": 0, "pnl_usd": 0.0}
            )
            bucket["trades"] += 1
            bucket["pnl_usd"] += float(t["pnl_usd"])
            if float(t["pnl_usd"]) > 0:
                bucket["wins"] += 1
        total_pnl = sum(float(t["pnl_usd"]) for t in trades)
        return {
            "day": day,
            "balance": self.get_balance(),
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(trades)) if trades else 0.0,
            "pnl_usd": total_pnl,
            "avg_pnl_pct": (
                sum(float(t["pnl_pct"]) for t in trades) / len(trades) if trades else 0.0
            ),
            "open_positions": int(open_n),
            "by_logic": by_logic,
            "recent_trades": trades[:40],
        }

    def _normalize_trade(self, t: dict[str, Any]) -> dict[str, Any]:
        lev = float(t.get("leverage") or sandbox_leverage(str(t.get("symbol") or "")))
        pnl_pct = float(t.get("pnl_pct") or 0)
        stored_roe = t.get("roe_pct")
        if (
            abs(float(stored_roe or 0)) < 1e-12 and abs(pnl_pct) > 1e-12
        ):
            t["roe_pct"] = pnl_pct * lev
        else:
            t["roe_pct"] = float(stored_roe or 0)
        t["leverage"] = lev
        try:
            raw_events = json.loads(t.get("events_json") or "[]")
        except json.JSONDecodeError:
            raw_events = []
        t["events"] = raw_events if isinstance(raw_events, list) else []
        t["is_partial"] = int(t.get("is_partial") or 0)
        raw_refs = t.get("ref_intervals") or ""
        if isinstance(raw_refs, str):
            refs = [x.strip() for x in raw_refs.split(",") if x.strip()]
        elif isinstance(raw_refs, list):
            refs = [str(x) for x in raw_refs]
        else:
            refs = []
        if not refs:
            refs = ref_intervals_for_logic(str(t.get("logic") or "S"))
        t["ref_intervals"] = refs
        t["ref_intervals_label"] = " · ".join(refs)
        if not t.get("entry_reason"):
            for e in t.get("events") or []:
                if e.get("type") == "entry":
                    t["entry_reason"] = str(e.get("entry_reason") or e.get("message") or "")
                    break
        t["entry_reason"] = str(t.get("entry_reason") or "")
        t["interval"] = str(t.get("interval") or SANDBOX_INTERVAL or "15m")
        source = resolve_entry_source(
            {
                "source": t.get("source"),
                "manual": t.get("manual"),
                "entry_reason": t.get("entry_reason"),
                "message": next(
                    (
                        e.get("message")
                        for e in (t.get("events") or [])
                        if e.get("type") == "entry"
                    ),
                    "",
                ),
            }
        )
        # 从 entry 事件补全旧成交
        if not t.get("source"):
            for e in t.get("events") or []:
                if e.get("type") == "entry" and (e.get("source") or e.get("source_label")):
                    source = resolve_entry_source(e)  # type: ignore[arg-type]
                    break
        t["source"] = source
        t["source_label"] = entry_source_label(source)
        exit_code = str(t.get("exit_code") or "")
        exit_label = str(t.get("exit_label") or "")
        if not exit_code:
            reason = str(t.get("reason") or "")
            if "|" in reason:
                parts = reason.split("|", 2)
                exit_code = parts[0]
                if not exit_label and len(parts) > 1:
                    exit_label = parts[1]
            else:
                for e in t.get("events") or []:
                    if e.get("type") == "exit":
                        exit_code = str(e.get("exit_code") or e.get("reason") or "")
                        exit_label = str(e.get("exit_label") or "")
                        break
        if exit_code and not exit_label:
            from oi_mornitor.sandbox.logics import exit_reason_label as _erl

            exit_label = _erl(exit_code, str(t.get("reason") or ""))
        t["exit_code"] = exit_code
        t["exit_label"] = exit_label
        t["fee_usd"] = float(t.get("fee_usd") or 0)
        t["fee_pct"] = float(t.get("fee_pct") or 0)
        return t

    @staticmethod
    def _row_to_pos(row: sqlite3.Row) -> PaperPosition:
        keys = set(row.keys())
        return PaperPosition(
            id=int(row["id"]) if "id" in keys and row["id"] is not None else 0,
            symbol=str(row["symbol"]),
            side=str(row["side"]),
            logic=str(row["logic"]),
            size=float(row["size"]),
            entry_price=float(row["entry_price"]),
            entry_time=int(row["entry_time"]),
            sl=float(row["sl"]),
            tp1=float(row["tp1"]) if row["tp1"] is not None else None,
            tp2=float(row["tp2"]) if row["tp2"] is not None else None,
            breakeven_armed=bool(row["breakeven_armed"]),
            meta_json=str(row["meta_json"] or "{}"),
        )
