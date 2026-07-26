"""沙盒引擎：每日随机 12 币 × K 线入场出场 × 弹窗告警。"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import date
from typing import Any

import aiohttp

from oi_mornitor.breakout_detector import klines_to_df
from oi_mornitor.config import (
    CARD_DEFAULT_LEVERAGE,
    CARD_EVAL_INTERVAL,
    CARD_NEAR_ENTRY_PCT,
    CARD_NEAR_ENTRY_PCT_MAJOR,
    FAPI_BASE_URL,
    SANDBOX_DAILY_COUNT,
    SANDBOX_ENABLED,
    SANDBOX_FEE_PCT,
    SANDBOX_INTERVAL,
    SANDBOX_KLINE_LIMIT,
    SANDBOX_KLINE_LIMIT_1H,
    SANDBOX_MAX_CONCURRENT,
    SANDBOX_NOTIONAL_USD,
    SANDBOX_REENTRY_COOLDOWN_BARS,
)
from oi_mornitor.market_snapshot import TIER_HEAVY
from oi_mornitor.pattern_monitor import fetch_pattern_klines, fetch_pattern_klines_batch
from oi_mornitor.sandbox.card_parser import ParsedCard, parse_card_message
from oi_mornitor.sandbox.logics import (
    SandboxSignal,
    apply_entry_sl_cap,
    apply_sandbox_fees,
    bar_time_sec,
    build_manual_entry_signal,
    enrich_sandbox_df,
    entry_source_label,
    card_near_entry_pct,
    evaluate_card_exit,
    evaluate_entry,
    evaluate_exit_and_trail,
    exit_reason_label,
    normalize_sandbox_interval,
    ref_intervals_for_logic,
    resolve_entry_source,
    sandbox_intervals,
    sandbox_leverage,
)
from oi_mornitor.sandbox.tracker import PaperPosition, SandboxTracker

logger = logging.getLogger("OI_Radar")

CARD_INTERVAL = "card"

_INTERVAL_SEC = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class SandboxEngine:
    def __init__(self) -> None:
        self.tracker = SandboxTracker()
        self._last_alerts: list[dict[str, Any]] = []
        self._last_scan_ts: float = 0.0
        # key: "SYMBOL|15m" — 同币同周期同已收盘 K 只评估一次
        self._last_eval_bar: dict[str, int] = {}
        self._last_entry_bar: dict[str, int] = {}
        self._last_exit_bar: dict[str, int] = {}
        # key: position id
        self._last_trail_sl: dict[int, float] = {}

    @staticmethod
    def _slot_key(symbol: str, interval: str) -> str:
        return f"{symbol.upper()}|{normalize_sandbox_interval(interval)}"

    @staticmethod
    def _pos_interval(pos: PaperPosition) -> str:
        try:
            meta = json.loads(pos.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        return normalize_sandbox_interval(str(meta.get("interval") or SANDBOX_INTERVAL))

    @staticmethod
    def _kline_limit(interval: str) -> int:
        iv = normalize_sandbox_interval(interval)
        if iv in ("1h", "4h", "1d"):
            return max(SANDBOX_KLINE_LIMIT, SANDBOX_KLINE_LIMIT_1H)
        return SANDBOX_KLINE_LIMIT

    def _bar_cooldown_sec(self, interval: str) -> int:
        iv = normalize_sandbox_interval(interval)
        return _INTERVAL_SEC.get(iv, 900) * max(1, SANDBOX_REENTRY_COOLDOWN_BARS)

    def _can_reenter(self, symbol: str, bar_time: int, interval: str) -> bool:
        sym = symbol.upper()
        iv = normalize_sandbox_interval(interval)
        key = self._slot_key(sym, iv)
        cool = self._bar_cooldown_sec(iv)
        last_exit = self._last_exit_bar.get(key)
        if last_exit is not None and bar_time <= last_exit:
            return False
        if last_exit is not None and (bar_time - last_exit) < cool:
            return False
        # 持久化成交：同币同执行周期
        for t in self.tracker.list_trades(symbol=sym, limit=20):
            t_iv = normalize_sandbox_interval(str(t.get("interval") or SANDBOX_INTERVAL))
            if t_iv != iv:
                continue
            exit_t = int(t["exit_time"])
            if bar_time <= exit_t:
                return False
            if (bar_time - exit_t) < cool:
                return False
            break
        if self._last_entry_bar.get(key) == bar_time:
            return False
        return True

    def _has_position_on_interval(self, symbol: str, interval: str) -> bool:
        iv = normalize_sandbox_interval(interval)
        return any(self._pos_interval(p) == iv for p in self.tracker.list_positions_for_symbol(symbol))

    def get_payload(self) -> dict[str, Any]:
        day = date.today().isoformat()
        pool = self.tracker.get_daily_pool(day) or []
        positions = []
        for p in self.tracker.list_positions():
            try:
                meta = json.loads(p.meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            lev = float(meta.get("leverage") or sandbox_leverage(p.symbol))
            source = resolve_entry_source(meta)
            positions.append(
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "logic": p.logic,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "entry_time": p.entry_time,
                    "sl": p.sl,
                    "tp1": p.tp1,
                    "tp2": p.tp2,
                    "breakeven_armed": p.breakeven_armed,
                    "leverage": lev,
                    "module": meta.get("module_label") or meta.get("module"),
                    "stage": meta.get("stage", 0),
                    "events": meta.get("events") or [],
                    "highest_price": meta.get("highest_price"),
                    "lowest_price": meta.get("lowest_price"),
                    "partial_done": bool(meta.get("partial_done")),
                    "entry_reason": meta.get("entry_reason"),
                    "source": source,
                    "source_label": meta.get("source_label") or entry_source_label(source),
                    "interval": meta.get("interval") or SANDBOX_INTERVAL,
                    "ref_intervals": meta.get("ref_intervals")
                    or ref_intervals_for_logic(p.logic),
                    "ref_intervals_label": meta.get("ref_intervals_label")
                    or " · ".join(
                        meta.get("ref_intervals") or ref_intervals_for_logic(p.logic)
                    ),
                    "card_id": meta.get("card_id"),
                    "card_tps": meta.get("card_tps"),
                    "tp3": meta.get("tp3"),
                }
            )
        card_orders = self.tracker.list_card_orders(limit=200)
        return {
            "sandbox_enabled": SANDBOX_ENABLED,
            "sandbox_scan_ts": self._last_scan_ts,
            "sandbox_day": day,
            "sandbox_pool": pool,
            "sandbox_pool_count": len(pool),
            "sandbox_max_concurrent": SANDBOX_MAX_CONCURRENT,
            "sandbox_intervals": list(sandbox_intervals()),
            "sandbox_positions": positions,
            "sandbox_card_orders": card_orders,
            "sandbox_alerts": list(self._last_alerts),
            "sandbox_stats": self.tracker.stats(day),
            "sandbox_trade_history": self.tracker.list_trades(limit=500),
            "card_near_entry_pct": CARD_NEAR_ENTRY_PCT,
            "card_near_entry_pct_major": CARD_NEAR_ENTRY_PCT_MAJOR,
        }

    def get_trade_markers(
        self, symbol: str, interval: str | None = None
    ) -> list[dict[str, Any]]:
        """供图表叠加：开仓/平仓标记。仅返回与图表周期一致的仓位/成交。"""
        sym = symbol.upper()
        chart_iv = normalize_sandbox_interval(interval) if interval else None
        markers: list[dict[str, Any]] = []
        for pos in self.tracker.list_positions_for_symbol(sym):
            try:
                meta = json.loads(pos.meta_json or "{}")
            except (TypeError, json.JSONDecodeError):
                meta = {}
            pos_iv = normalize_sandbox_interval(
                str(meta.get("interval") or SANDBOX_INTERVAL)
            )
            if chart_iv and pos_iv != chart_iv:
                continue
            markers.append(
                {
                    "time": pos.entry_time,
                    "position": "belowBar" if pos.side == "LONG" else "aboveBar",
                    "color": "#00e676" if pos.side == "LONG" else "#ff5252",
                    "shape": "arrowUp" if pos.side == "LONG" else "arrowDown",
                    "text": f"入场{pos.logic}#{pos.id}",
                    "kind": "sandbox_entry",
                    "price": pos.entry_price,
                    "interval": pos_iv,
                }
            )
        for t in self.tracker.list_trades(symbol=sym, limit=40):
            t_iv = normalize_sandbox_interval(
                str(t.get("interval") or SANDBOX_INTERVAL)
            )
            if chart_iv and t_iv != chart_iv:
                continue
            markers.append(
                {
                    "time": int(t["entry_time"]),
                    "position": "belowBar" if t["side"] == "LONG" else "aboveBar",
                    "color": "#66bb6a",
                    "shape": "circle",
                    "text": f"入{t['logic']}",
                    "kind": "sandbox_entry",
                    "price": float(t["entry_price"]),
                    "interval": t_iv,
                }
            )
            markers.append(
                {
                    "time": int(t["exit_time"]),
                    "position": "aboveBar" if t["side"] == "LONG" else "belowBar",
                    "color": "#ffa726",
                    "shape": "circle",
                    "text": f"出{t['logic']}",
                    "kind": "sandbox_exit",
                    "price": float(t["exit_price"]),
                    "interval": t_iv,
                }
            )
        # 去重同 time+kind+interval
        seen: set[tuple[int, str, str]] = set()
        uniq: list[dict[str, Any]] = []
        for m in sorted(markers, key=lambda x: int(x["time"])):
            key = (
                int(m["time"]),
                str(m["kind"]),
                str(m.get("interval") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            uniq.append(m)
        return uniq

    def ensure_daily_pool(
        self,
        candidates: list[str],
        *,
        count: int | None = None,
        force: bool = False,
    ) -> list[str]:
        day = date.today().isoformat()
        count = count or SANDBOX_DAILY_COUNT
        existing = self.tracker.get_daily_pool(day)
        if existing and not force:
            return existing
        pool_src = [s.upper() for s in candidates if s]
        if not pool_src:
            return existing or []
        rng = random.Random(f"sandbox-{day}")
        if len(pool_src) <= count:
            picked = list(pool_src)
        else:
            picked = rng.sample(pool_src, count)
        self.tracker.set_daily_pool(picked, day)
        logger.info("沙盒日池 %s · %d 币: %s", day, len(picked), ",".join(picked))
        return picked

    def card_symbols(self) -> list[str]:
        return sorted(
            {
                str(o.get("symbol") or "").upper()
                for o in self.tracker.list_active_card_orders()
                if o.get("symbol")
            }
            | {
                p.symbol.upper()
                for p in self.tracker.list_positions()
                if p.logic == "C"
            }
        )

    def ingest_card(self, payload: dict[str, Any] | str) -> dict[str, Any]:
        """接入一张卡片：幂等按 card_id；市价立即评估为待入场/已入场。"""
        if not SANDBOX_ENABLED:
            return {"ok": False, "error": "沙盒未启用"}
        card = parse_card_message(payload)
        if not card:
            return {"ok": False, "error": "无法解析卡片（需 ID/币种/方向/止损）"}
        if card.sl is None or card.sl <= 0:
            return {"ok": False, "error": "卡片缺少有效止损"}
        existing = self.tracker.get_card_order(card.card_id)
        if existing and existing.get("status") in ("filled", "closed"):
            return {
                "ok": True,
                "duplicate": True,
                "card_id": card.card_id,
                "status": existing.get("status"),
                "order": existing,
            }

        payload_dict = card.to_dict()
        status = "watching"
        if card.entry_type == "market":
            status = "ordered"  # 下一轮扫描按市价成交入场
        order = {
            "card_id": card.card_id,
            "symbol": card.symbol,
            "side": card.side,
            "status": status,
            "payload": payload_dict,
            "position_id": existing.get("position_id") if existing else None,
            "created_at": (existing or {}).get("created_at") or time.time(),
        }
        self.tracker.upsert_card_order(order)
        logger.info(
            "卡片接入 %s %s %s %s entry=%s SL=%s TPs=%s",
            card.card_id,
            card.symbol,
            card.side,
            card.entry_type,
            card.entry_type if card.entry_type == "market" else f"{card.entry_low}-{card.entry_high}",
            card.sl,
            card.tps,
        )
        alert = {
            "type": "card_watch",
            "symbol": card.symbol,
            "side": card.side,
            "logic": "C",
            "card_id": card.card_id,
            "message": f"卡片接入 · {card.title or card.card_id} · {card.entry_type}",
            "status_label": f"卡片监听 · {card.card_id}",
            "kline_close_time": int(time.time()),
            "entry_type": card.entry_type,
        }
        self._last_alerts = [alert] + self._last_alerts[:19]
        return {
            "ok": True,
            "card_id": card.card_id,
            "status": status,
            "order": self.tracker.get_card_order(card.card_id),
            "alert": alert,
        }

    @staticmethod
    def _entry_zone_distance_pct(
        price: float, entry_low: float | None, entry_high: float | None
    ) -> float | None:
        if price <= 0 or entry_low is None:
            return None
        hi = entry_high if entry_high is not None else entry_low
        lo, hi = min(entry_low, hi), max(entry_low, hi)
        if lo <= price <= hi:
            return 0.0
        if price < lo:
            return (lo - price) / price * 100.0
        return (price - hi) / price * 100.0

    @staticmethod
    def _price_in_entry_zone(
        price: float, entry_low: float | None, entry_high: float | None
    ) -> bool:
        if price <= 0 or entry_low is None:
            return False
        hi = entry_high if entry_high is not None else entry_low
        lo, hi = min(entry_low, hi), max(entry_low, hi)
        return lo <= price <= hi

    def _card_from_order(self, order: dict[str, Any]) -> ParsedCard | None:
        payload = order.get("payload") or order
        return parse_card_message(payload if isinstance(payload, dict) else order)

    def _build_card_enter_signal(
        self, card: ParsedCard, price: float
    ) -> SandboxSignal | None:
        if price <= 0 or not card.sl:
            return None
        tps = list(card.tps or [])
        tp1 = tps[0] if len(tps) > 0 else None
        tp2 = tps[1] if len(tps) > 1 else None
        tp3 = tps[2] if len(tps) > 2 else None
        lev = float(card.leverage or CARD_DEFAULT_LEVERAGE)
        src = card.source_label or "卡片"
        msg = (
            f"卡片入场 · {card.card_id} · {src} · {card.side} @ {price:.6g} "
            f"SL={card.sl:.6g}"
            + (f" TP={'/'.join(f'{x:.6g}' for x in tps)}" if tps else "")
        )
        meta = {
            "source": "card",
            "source_label": "卡片",
            "card_id": card.card_id,
            "card_tps": tps,
            "tp3": tp3,
            "entry_type": card.entry_type,
            "entry_low": card.entry_low,
            "entry_high": card.entry_high,
            "interval": CARD_INTERVAL,
            "ref_intervals": [CARD_EVAL_INTERVAL],
            "ref_intervals_label": CARD_EVAL_INTERVAL,
            "module": "card",
            "module_label": f"卡片 · {card.card_id}",
            "entry_reason": msg,
            "leverage": lev,
            "card_title": card.title,
            "card_source": src,
            "skip_sl_cap": True,
            "card_tp_done": 0,
        }
        return SandboxSignal(
            action="enter",
            side=card.side,
            logic="C",
            price=float(price),
            sl=float(card.sl),
            tp1=tp1,
            tp2=tp2,
            message=msg,
            meta=meta,
        )

    def _price_map_from_pool(
        self, pool_rows: list[dict[str, Any]] | None
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in pool_rows or []:
            sym = str(r.get("symbol") or "").upper()
            try:
                px = float(r.get("last_price") or 0)
            except (TypeError, ValueError):
                px = 0.0
            if sym and px > 0:
                out[sym] = px
        return out

    async def _scan_card_orders(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str,
        pool_rows: list[dict[str, Any]] | None,
        klines_15m: dict[str, list] | None,
        alerts: list[dict[str, Any]],
    ) -> None:
        """限价近场提醒/挂单；市价与触价入场；卡片仓 TP/SL 出场。"""
        prices = self._price_map_from_pool(pool_rows)
        eval_iv = CARD_EVAL_INTERVAL
        iv_sec = _INTERVAL_SEC.get(eval_iv, 900)

        # 补齐缺价币种：用 15m 最新收盘
        need = [
            o["symbol"]
            for o in self.tracker.list_active_card_orders()
            if o["symbol"] not in prices
        ]
        for p in self.tracker.list_positions():
            if p.logic == "C" and p.symbol not in prices:
                need.append(p.symbol)
        need = sorted(set(need))
        if need:
            km = klines_15m or {}
            missing = [s for s in need if s not in km]
            if missing:
                extra = await fetch_pattern_klines_batch(
                    session,
                    base_url=base_url,
                    symbols=missing,
                    interval=eval_iv,
                    limit=self._kline_limit(eval_iv),
                )
                km = {**km, **extra}
            for sym in need:
                kl = km.get(sym) or []
                if kl:
                    try:
                        prices[sym] = float(kl[-1][4])
                    except (TypeError, ValueError, IndexError):
                        pass

        # —— 未成交卡片：近场 / 入场 ——
        for order in self.tracker.list_active_card_orders():
            if order.get("status") == "filled":
                continue
            card = self._card_from_order(order)
            if not card:
                continue
            sym = card.symbol
            px = prices.get(sym)
            if not px:
                continue

            already = any(
                (json.loads(p.meta_json or "{}").get("card_id") == card.card_id)
                for p in self.tracker.list_positions_for_symbol(sym)
            )
            if already:
                order["status"] = "filled"
                self.tracker.upsert_card_order(order)
                continue

            # 市价：立刻入场
            if card.entry_type == "market":
                sig = self._build_card_enter_signal(card, px)
                if not sig:
                    continue
                alert = self._apply_signal(sym, sig, int(time.time()), pos=None, force=True)
                if alert:
                    alerts.append(alert)
                    order["status"] = "filled"
                    order["position_id"] = alert.get("id")
                    order["payload"] = {**card.to_dict(), "fill_price": px}
                    self.tracker.upsert_card_order(order)
                continue

            # 限价：近场阈值按主流/山寨（约 0.2% / 1%）→ 提醒 + 挂单；触价 → 入场
            near_pct = card_near_entry_pct(sym, card.leverage)
            dist = self._entry_zone_distance_pct(px, card.entry_low, card.entry_high)
            if dist is None:
                continue
            if dist <= near_pct and order.get("status") in (
                "watching",
                "near",
            ):
                if order.get("status") == "watching":
                    alerts.append(
                        {
                            "type": "card_near",
                            "symbol": sym,
                            "side": card.side,
                            "logic": "C",
                            "card_id": card.card_id,
                            "price": px,
                            "message": (
                                f"接近入场 · {card.card_id} · 现价 {px:.6g} "
                                f"距区间 {dist:.2f}%≤{near_pct:g}%"
                            ),
                            "status_label": f"卡片近场 · {card.card_id}",
                            "kline_close_time": int(time.time()),
                            "near_entry_pct": near_pct,
                        }
                    )
                    alerts.append(
                        {
                            "type": "card_order",
                            "symbol": sym,
                            "side": card.side,
                            "logic": "C",
                            "card_id": card.card_id,
                            "price": px,
                            "message": f"卡片挂单 · {card.card_id} · 等待触价入场",
                            "status_label": f"卡片挂单 · {card.card_id}",
                            "kline_close_time": int(time.time()),
                        }
                    )
                order["status"] = "ordered"
                order["payload"] = {
                    **card.to_dict(),
                    "last_price": px,
                    "near_pct": dist,
                }
                self.tracker.upsert_card_order(order)

            if self._price_in_entry_zone(px, card.entry_low, card.entry_high):
                fill_px = px
                if card.entry_low is not None:
                    hi = (
                        card.entry_high
                        if card.entry_high is not None
                        else card.entry_low
                    )
                    fill_px = (float(card.entry_low) + float(hi)) / 2.0
                sig = self._build_card_enter_signal(card, fill_px)
                if not sig:
                    continue
                alert = self._apply_signal(
                    sym, sig, int(time.time()), pos=None, force=True
                )
                if alert:
                    alerts.append(alert)
                    order["status"] = "filled"
                    order["position_id"] = alert.get("id")
                    order["payload"] = {**card.to_dict(), "fill_price": fill_px}
                    self.tracker.upsert_card_order(order)

        # —— 已开卡片仓：按评估周期 K 线 TP/SL ——
        card_positions = [p for p in self.tracker.list_positions() if p.logic == "C"]
        if not card_positions:
            return
        syms = sorted({p.symbol for p in card_positions})
        km = dict(klines_15m or {})
        missing = [s for s in syms if s not in km]
        if missing:
            extra = await fetch_pattern_klines_batch(
                session,
                base_url=base_url,
                symbols=missing,
                interval=eval_iv,
                limit=self._kline_limit(eval_iv),
            )
            km.update(extra)

        for pos in card_positions:
            klines = km.get(pos.symbol) or []
            if len(klines) < 3:
                continue
            try:
                df = enrich_sandbox_df(klines_to_df(klines))
            except Exception as exc:  # noqa: BLE001
                logger.warning("卡片仓指标失败 %s: %s", pos.symbol, exc)
                continue
            if len(df) < 3:
                continue
            closed = df.iloc[:-1].copy()
            t = bar_time_sec(closed)
            slot_pos = f"{self._slot_key(pos.symbol, CARD_INTERVAL)}|{pos.id}"
            if self._last_eval_bar.get(slot_pos) == t:
                continue
            try:
                pos_meta = json.loads(pos.meta_json or "{}")
            except json.JSONDecodeError:
                pos_meta = {}
            signals = evaluate_card_exit(
                closed,
                side=pos.side,
                entry_price=pos.entry_price,
                sl=pos.sl,
                tps=list(pos_meta.get("card_tps") or []),
                tp1=pos.tp1,
                tp2=pos.tp2,
                meta=pos_meta,
            )
            current = pos
            for sig in signals:
                alert = self._apply_signal(pos.symbol, sig, t, pos=current)
                if alert:
                    alerts.append(alert)
                    if sig.action == "exit":
                        # 同步卡片订单状态
                        cid = pos_meta.get("card_id")
                        if cid:
                            co = self.tracker.get_card_order(str(cid))
                            if co:
                                co["status"] = "closed"
                                self.tracker.upsert_card_order(co)
                        break
                    current = self.tracker.get_position_by_id(pos.id)
                    if current is None:
                        break
            self._last_eval_bar[slot_pos] = t

    async def manual_enter(
        self,
        session: aiohttp.ClientSession,
        *,
        symbol: str,
        logic: str,
        side: str,
        interval: str | None = None,
        base_url: str = FAPI_BASE_URL,
        market_price: float | None = None,
        pattern_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """手动选择逻辑 + 方向 + 周期，按最新价市价开仓。"""
        if not SANDBOX_ENABLED:
            return {"ok": False, "error": "沙盒未启用"}
        sym = symbol.strip().upper()
        logic_u = logic.strip().upper()
        side_u = side.strip().upper()
        iv = normalize_sandbox_interval(interval)
        allowed = set(sandbox_intervals()) | {SANDBOX_INTERVAL, "15m", "1h"}
        if iv not in allowed and iv not in _INTERVAL_SEC:
            return {"ok": False, "error": f"不支持的周期 {iv}"}
        if not sym:
            return {"ok": False, "error": "symbol required"}
        if logic_u not in ("S", "T"):
            return {"ok": False, "error": "logic 须为 S 或 T"}
        if side_u not in ("LONG", "SHORT"):
            return {"ok": False, "error": "side 须为 LONG 或 SHORT"}
        if len(self.tracker.list_positions()) >= SANDBOX_MAX_CONCURRENT:
            return {"ok": False, "error": f"已达最大并发 {SANDBOX_MAX_CONCURRENT}"}

        klines = await fetch_pattern_klines(
            session,
            base_url=base_url,
            symbol=sym,
            interval=iv,
            limit=self._kline_limit(iv),
        )
        if len(klines) < 30:
            return {"ok": False, "error": "K 线不足，无法开仓"}
        try:
            df = enrich_sandbox_df(klines_to_df(klines))
        except Exception as exc:  # noqa: BLE001
            logger.warning("手动开仓指标失败 %s %s: %s", sym, iv, exc)
            return {"ok": False, "error": f"指标计算失败: {exc}"}

        structure = {
            "hl": float((pattern_state or {}).get("hl") or 0),
            "lh_price": float((pattern_state or {}).get("lh_price") or 0),
            "lh": float((pattern_state or {}).get("lh_price") or 0),
            "symbol": sym,
        }
        # 非 15m 时形态页 LH/HL 口径不一定对齐，避免误用
        if iv != "15m":
            structure = {"hl": 0.0, "lh_price": 0.0, "lh": 0.0, "symbol": sym}
        sig = build_manual_entry_signal(
            df,
            symbol=sym,
            logic=logic_u,
            side=side_u,
            structure=structure,
            market_price=market_price,
            interval=iv,
        )
        if not sig or not sig.sl:
            return {"ok": False, "error": "无法构造入场信号"}

        # 手动开仓跳过冷却
        t = bar_time_sec(df)
        alert = self._apply_signal(sym, sig, t, pos=None, force=True)
        if not alert:
            return {"ok": False, "error": "开仓被拒绝（可能已满仓）"}
        # 确保日池可见（可选加入）
        day = date.today().isoformat()
        pool = self.tracker.get_daily_pool(day) or []
        if sym not in pool:
            pool = list(pool) + [sym]
            self.tracker.set_daily_pool(pool, day)

        self._last_alerts = [alert] + [
            a for a in self._last_alerts if a.get("symbol") != sym
        ][:19]
        self._last_scan_ts = time.time()
        logger.info("沙盒手动市价入场 %s %s %s %s @ %s", sym, side_u, logic_u, iv, sig.price)
        return {"ok": True, "alert": alert, **self.get_payload()}

    async def scan(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = FAPI_BASE_URL,
        scan_ts: float | None = None,
        pool_rows: list[dict[str, Any]] | None = None,
        fallback_symbols: list[str] | None = None,
        pattern_states: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not SANDBOX_ENABLED:
            self._last_alerts = []
            self._last_scan_ts = scan_ts or time.time()
            return []

        candidates: list[str] = []
        if pool_rows:
            for r in pool_rows:
                sym = str(r.get("symbol") or "")
                if sym and r.get("oi_tier") == TIER_HEAVY:
                    candidates.append(sym)
        if not candidates and fallback_symbols:
            candidates = list(fallback_symbols)
        if not candidates and pool_rows:
            candidates = [str(r.get("symbol")) for r in pool_rows if r.get("symbol")]

        pool = self.ensure_daily_pool(candidates)
        open_syms = [p.symbol for p in self.tracker.list_positions()]
        card_syms = self.card_symbols()
        symbols = sorted(set(pool) | set(open_syms) | set(card_syms))
        if not symbols:
            self._last_alerts = []
            self._last_scan_ts = scan_ts or time.time()
            return []

        state_by_sym = {
            str(s.get("symbol") or "").upper(): s for s in (pattern_states or [])
        }
        intervals = list(sandbox_intervals())

        # 各执行周期并行拉 K（15m / 1h 同等处理）
        klines_by_iv: dict[str, dict[str, list]] = {}
        fetched = await asyncio.gather(
            *[
                fetch_pattern_klines_batch(
                    session,
                    base_url=base_url,
                    symbols=symbols,
                    interval=iv,
                    limit=self._kline_limit(iv),
                )
                for iv in intervals
            ]
        )
        for iv, km in zip(intervals, fetched):
            klines_by_iv[iv] = km

        alerts: list[dict[str, Any]] = []
        for iv in intervals:
            iv_sec = _INTERVAL_SEC.get(iv, 900)
            klines_map = klines_by_iv.get(iv) or {}
            for sym in symbols:
                klines = klines_map.get(sym) or []
                if len(klines) < 60:
                    continue
                try:
                    df = enrich_sandbox_df(klines_to_df(klines))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("沙盒指标失败 %s %s: %s", sym, iv, exc)
                    continue
                # 用已收盘 K（去掉最后一根未完成）
                if len(df) < 61:
                    continue
                closed = df.iloc[:-1].copy()
                # 形态 LH/HL 目前按 15m 口径；其它周期不用，避免错位
                if iv == "15m":
                    structure = {**(state_by_sym.get(sym) or {}), "symbol": sym}
                else:
                    structure = {"symbol": sym, "hl": 0.0, "lh_price": 0.0, "lh": 0.0}
                t = bar_time_sec(closed)
                slot = self._slot_key(sym, iv)
                # 同一根已收盘 K 只跑一轮
                if self._last_eval_bar.get(slot) == t:
                    continue

                # 只管理本周期开的仓（卡片仓 logic=C 另走卡片 TP/SL）
                open_positions = [
                    p
                    for p in self.tracker.list_positions_for_symbol(sym)
                    if self._pos_interval(p) == iv and p.logic != "C"
                ]

                for pos in open_positions:
                    try:
                        pos_meta = json.loads(pos.meta_json or "{}")
                    except json.JSONDecodeError:
                        pos_meta = {}
                    signals = evaluate_exit_and_trail(
                        closed,
                        side=pos.side,
                        logic=pos.logic,
                        entry_price=pos.entry_price,
                        sl=pos.sl,
                        tp1=pos.tp1,
                        tp2=pos.tp2,
                        breakeven_armed=pos.breakeven_armed,
                        structure=structure,
                        entry_time=pos.entry_time,
                        bar_time=t,
                        interval_sec=iv_sec,
                        meta=pos_meta,
                    )
                    current = pos
                    for sig in signals:
                        alert = self._apply_signal(sym, sig, t, pos=current)
                        if alert:
                            alerts.append(alert)
                            if sig.action == "exit":
                                break
                            current = self.tracker.get_position_by_id(pos.id)
                            if current is None:
                                break

                # 自动：同币同周期无持仓才开；15m/1h 可并行各开一笔
                if (
                    not self._has_position_on_interval(sym, iv)
                    and sym in pool
                    and len(self.tracker.list_positions()) < SANDBOX_MAX_CONCURRENT
                    and self._can_reenter(sym, t, iv)
                ):
                    sig = evaluate_entry(
                        closed, symbol=sym, structure=structure, interval=iv
                    )
                    if sig:
                        alert = self._apply_signal(sym, sig, t, pos=None)
                        if alert:
                            alerts.append(alert)
                self._last_eval_bar[slot] = t

        # 卡片订单：近场提醒 / 挂单 / 入场 / 卡片止盈止损（不影响 S/T）
        await self._scan_card_orders(
            session,
            base_url=base_url,
            pool_rows=pool_rows,
            klines_15m=klines_by_iv.get(CARD_EVAL_INTERVAL)
            or klines_by_iv.get("15m"),
            alerts=alerts,
        )

        self._last_alerts = alerts
        self._last_scan_ts = scan_ts or time.time()
        return alerts

    def _append_event(self, meta: dict[str, Any], event: dict[str, Any]) -> None:
        events = list(meta.get("events") or [])
        events.append(event)
        meta["events"] = events[-40:]

    def _trade_context(self, pos: PaperPosition, meta: dict[str, Any]) -> dict[str, Any]:
        entry_reason = str(
            meta.get("entry_reason")
            or next(
                (
                    e.get("entry_reason") or e.get("message")
                    for e in (meta.get("events") or [])
                    if e.get("type") == "entry"
                ),
                "",
            )
            or ""
        )
        refs = meta.get("ref_intervals")
        if isinstance(refs, str):
            refs = [x.strip() for x in refs.split(",") if x.strip()]
        if not refs:
            refs = ref_intervals_for_logic(pos.logic)
        label = meta.get("ref_intervals_label") or " · ".join(str(x) for x in refs)
        source = resolve_entry_source(meta)
        return {
            "entry_reason": entry_reason,
            "source": source,
            "source_label": meta.get("source_label") or entry_source_label(source),
            "interval": str(meta.get("interval") or SANDBOX_INTERVAL),
            "ref_intervals": list(refs),
            "ref_intervals_label": label,
        }

    def _apply_signal(
        self,
        symbol: str,
        sig: SandboxSignal,
        bar_time: int,
        *,
        pos: PaperPosition | None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        sym = symbol.upper()
        if sig.action == "enter" and pos is None and sig.sl:
            if len(self.tracker.list_positions()) >= SANDBOX_MAX_CONCURRENT:
                return None
            meta_pre = dict(sig.meta or {})
            is_card = sig.logic == "C" or str(meta_pre.get("source") or "") == "card"
            iv = (
                CARD_INTERVAL
                if is_card
                else normalize_sandbox_interval(
                    str(meta_pre.get("interval") or SANDBOX_INTERVAL)
                )
            )
            if not force and not self._can_reenter(sym, bar_time, iv):
                return None
            if not is_card and not force and self._has_position_on_interval(sym, iv):
                return None
            if is_card:
                cid = str(meta_pre.get("card_id") or "")
                if cid and any(
                    json.loads(p.meta_json or "{}").get("card_id") == cid
                    for p in self.tracker.list_positions_for_symbol(sym)
                ):
                    return None
            else:
                sig = apply_entry_sl_cap(sym, sig)
            if is_card and meta_pre.get("leverage"):
                lev = float(meta_pre["leverage"])
            else:
                lev = sandbox_leverage(sym)
            notional = SANDBOX_NOTIONAL_USD * lev
            size = notional / max(sig.price, 1e-12)
            meta = dict(sig.meta or {})
            meta["leverage"] = lev
            meta["margin_usd"] = SANDBOX_NOTIONAL_USD
            meta["initial_size"] = size
            meta["remaining_frac"] = 1.0
            meta["highest_price"] = sig.price
            meta["lowest_price"] = sig.price
            meta["stage"] = int(meta.get("stage") or 0)
            meta.setdefault("entry_reason", sig.message)
            meta["interval"] = iv
            if not meta.get("ref_intervals"):
                meta["ref_intervals"] = (
                    [CARD_EVAL_INTERVAL]
                    if is_card
                    else ref_intervals_for_logic(sig.logic, iv)
                )
                meta["ref_intervals_label"] = " · ".join(meta["ref_intervals"])
            source = "card" if is_card else resolve_entry_source(meta, force_manual=force)
            meta["source"] = source
            meta["source_label"] = entry_source_label(source)
            meta["manual"] = source == "manual"
            meta["fee_pct"] = SANDBOX_FEE_PCT
            meta["events"] = [
                {
                    "type": "entry",
                    "time": bar_time,
                    "price": sig.price,
                    "sl": float(sig.sl),
                    "side": sig.side,
                    "logic": sig.logic,
                    "module": meta.get("module_label") or meta.get("module"),
                    "message": sig.message,
                    "entry_reason": meta.get("entry_reason") or sig.message,
                    "source": source,
                    "source_label": meta["source_label"],
                    "fee_pct": SANDBOX_FEE_PCT,
                    "interval": iv,
                    "ref_intervals": meta.get("ref_intervals"),
                    "card_id": meta.get("card_id"),
                }
            ]
            new_pos = PaperPosition(
                symbol=sym,
                side=sig.side,
                logic=sig.logic,
                size=size,
                entry_price=sig.price,
                entry_time=bar_time,
                sl=float(sig.sl),
                tp1=sig.tp1,
                tp2=sig.tp2,
                breakeven_armed=False,
                meta_json=json.dumps(meta, ensure_ascii=False),
            )
            new_pos = self.tracker.insert_position(new_pos)
            self._last_entry_bar[self._slot_key(sym, iv)] = bar_time
            if new_pos.id:
                self._last_trail_sl[new_pos.id] = float(sig.sl)
            logger.info(
                "沙盒入场 #%s %s %s %s %s @ %s SL=%s lev=%.0fx margin=%.2fU",
                new_pos.id,
                sym,
                sig.side,
                sig.logic,
                iv,
                sig.price,
                sig.sl,
                lev,
                SANDBOX_NOTIONAL_USD,
            )
            label = meta.get("module_label") or f"逻辑{sig.logic}"
            src_label = meta["source_label"]
            return {
                "type": "entry",
                "id": new_pos.id,
                "symbol": sym,
                "side": sig.side,
                "logic": sig.logic,
                "price": sig.price,
                "entry_price": sig.price,
                "entry_time": bar_time,
                "sl": sig.sl,
                "tp1": sig.tp1,
                "tp2": sig.tp2,
                "leverage": lev,
                "source": source,
                "source_label": src_label,
                "card_id": meta.get("card_id"),
                "message": sig.message,
                "interval": iv,
                "kline_close_time": bar_time,
                "status_label": f"沙盒入场 · {src_label} · {label} · {iv} · {lev:.0f}x",
            }

        if sig.action == "trail" and pos:
            try:
                meta = json.loads(pos.meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            sm = dict(sig.meta or {})
            silent = bool(sm.get("silent"))
            if sm.get("highest_price") is not None:
                meta["highest_price"] = float(sm["highest_price"])
            if sm.get("lowest_price") is not None:
                meta["lowest_price"] = float(sm["lowest_price"])
            if sm.get("stage") is not None:
                meta["stage"] = int(sm["stage"])
            if sm.get("partial_done"):
                meta["partial_done"] = True
            if sm.get("step_trail_level") is not None:
                meta["step_trail_level"] = int(sm["step_trail_level"])
            if sm.get("breakeven_armed"):
                pos.breakeven_armed = True
                meta["breakeven_armed"] = True

            if sig.sl is None:
                pos.meta_json = json.dumps(meta, ensure_ascii=False)
                self.tracker.upsert_position(pos)
                return None

            new_sl = float(sig.sl)
            old_sl = float(pos.sl)
            sl_changed = abs(new_sl - old_sl) / max(old_sl, 1e-12) >= 0.0005
            if not silent:
                if not sl_changed:
                    pos.meta_json = json.dumps(meta, ensure_ascii=False)
                    self.tracker.upsert_position(pos)
                    return None
                if pos.side == "LONG" and new_sl <= old_sl:
                    return None
                if pos.side == "SHORT" and new_sl >= old_sl:
                    return None
            elif not sl_changed:
                # 仅同步极值
                pos.meta_json = json.dumps(meta, ensure_ascii=False)
                self.tracker.upsert_position(pos)
                return None

            pos.sl = new_sl
            if sl_changed and not silent:
                self._append_event(
                    meta,
                    {
                        "type": "trail",
                        "time": bar_time,
                        "price": sig.price,
                        "sl": new_sl,
                        "stage": meta.get("stage"),
                        "reason": sm.get("reason") or sig.message,
                        "message": sig.message,
                    },
                )
            pos.meta_json = json.dumps(meta, ensure_ascii=False)
            self.tracker.upsert_position(pos)
            if pos.id:
                self._last_trail_sl[pos.id] = new_sl
            if silent:
                return None
            trail_iv = normalize_sandbox_interval(
                str(meta.get("interval") or SANDBOX_INTERVAL)
            )
            return {
                "type": "trail",
                "id": pos.id,
                "symbol": sym,
                "side": pos.side,
                "logic": pos.logic,
                "price": sig.price,
                "sl": pos.sl,
                "entry_price": pos.entry_price,
                "entry_time": pos.entry_time,
                "message": sig.message,
                "interval": trail_iv,
                "kline_close_time": bar_time,
                "status_label": f"沙盒移止损 · 逻辑{pos.logic} · {trail_iv}",
            }

        if sig.action == "partial" and pos:
            try:
                meta = json.loads(pos.meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            # 卡片可多级分批；S/T 仅一次 partial_done
            if meta.get("partial_done") and pos.logic != "C":
                return None
            frac = float((sig.meta or {}).get("partial_frac") or 0.3)
            frac = min(max(frac, 0.05), 0.9)
            exit_px = float(sig.price)
            if pos.side == "LONG":
                pnl_pct = (exit_px - pos.entry_price) / pos.entry_price * 100.0
            else:
                pnl_pct = (pos.entry_price - exit_px) / pos.entry_price * 100.0
            lev = float(meta.get("leverage") or sandbox_leverage(sym))
            margin = float(meta.get("margin_usd") or SANDBOX_NOTIONAL_USD)
            fee_pct = float(meta.get("fee_pct") or SANDBOX_FEE_PCT)
            gross_pnl_pct = pnl_pct
            pnl_pct, pnl_usd, fee_usd, fee_price_pct = apply_sandbox_fees(
                pnl_pct=gross_pnl_pct,
                margin_usd=margin,
                leverage=lev,
                frac=frac,
                fee_pct=fee_pct,
            )
            roe_pct = pnl_pct * lev
            bal = self.tracker.get_balance() + pnl_usd
            self.tracker.set_balance(bal)
            sm = dict(sig.meta or {})
            self._append_event(
                meta,
                {
                    "type": "partial",
                    "time": bar_time,
                    "price": exit_px,
                    "frac": frac,
                    "pnl_usd": pnl_usd,
                    "pnl_pct": pnl_pct,
                    "gross_pnl_pct": gross_pnl_pct,
                    "fee_usd": fee_usd,
                    "fee_pct": fee_pct,
                    "fee_price_pct": fee_price_pct,
                    "roe_pct": roe_pct,
                    "stage": 2,
                    "reason": "partial",
                    "exit_code": "partial",
                    "exit_label": exit_reason_label("partial"),
                    "message": sig.message,
                },
            )
            if pos.logic == "C":
                meta["card_tp_done"] = int(sm.get("card_tp_done") or meta.get("card_tp_done") or 0)
                meta["partial_done"] = False
            else:
                meta["partial_done"] = True
            meta["stage"] = 2
            meta["remaining_frac"] = float(meta.get("remaining_frac") or 1.0) * (1.0 - frac)
            meta["partial_pnl_usd"] = float(meta.get("partial_pnl_usd") or 0.0) + pnl_usd
            meta["partial_fee_usd"] = float(meta.get("partial_fee_usd") or 0.0) + fee_usd
            if sm.get("highest_price") is not None:
                meta["highest_price"] = float(sm["highest_price"])
            if sm.get("lowest_price") is not None:
                meta["lowest_price"] = float(sm["lowest_price"])
            pos.size = pos.size * (1.0 - frac)
            pos.breakeven_armed = True
            pos.meta_json = json.dumps(meta, ensure_ascii=False)
            self.tracker.upsert_position(pos)
            # 减仓不单独落库成第二笔；事件记入持仓，待全平合并为一条成交
            logger.info(
                "沙盒减仓 %s %s %.0f%% @ %s pnl=%.4fU fee=%.4fU",
                sym,
                pos.logic,
                frac * 100,
                exit_px,
                pnl_usd,
                fee_usd,
            )
            exit_code = str(sm.get("exit_code") or "partial")
            exit_label = str(sm.get("exit_label") or exit_reason_label(exit_code))
            return {
                "type": "partial",
                "symbol": sym,
                "side": pos.side,
                "logic": pos.logic,
                "price": exit_px,
                "entry_price": pos.entry_price,
                "exit_price": exit_px,
                "entry_time": pos.entry_time,
                "exit_time": bar_time,
                "leverage": lev,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "roe_pct": roe_pct,
                "fee_usd": fee_usd,
                "exit_code": exit_code,
                "exit_label": exit_label,
                "card_id": sm.get("card_id") or meta.get("card_id"),
                "message": sig.message,
                "interval": normalize_sandbox_interval(
                    str(meta.get("interval") or SANDBOX_INTERVAL)
                ),
                "kline_close_time": bar_time,
                "status_label": f"沙盒减仓 · 逻辑{pos.logic} · {pnl_usd:+.2f}U",
            }

        if sig.action == "exit" and pos:
            exit_px = float(sig.price)
            if pos.side == "LONG":
                pnl_pct = (exit_px - pos.entry_price) / pos.entry_price * 100.0
            else:
                pnl_pct = (pos.entry_price - exit_px) / pos.entry_price * 100.0
            try:
                meta = json.loads(pos.meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            lev = float(meta.get("leverage") or sandbox_leverage(sym))
            margin = float(meta.get("margin_usd") or SANDBOX_NOTIONAL_USD)
            rem = float(meta.get("remaining_frac") or 1.0)
            fee_pct = float(meta.get("fee_pct") or SANDBOX_FEE_PCT)
            gross_pnl_pct = pnl_pct
            pnl_pct, pnl_usd, fee_usd, fee_price_pct = apply_sandbox_fees(
                pnl_pct=gross_pnl_pct,
                margin_usd=margin,
                leverage=lev,
                frac=rem,
                fee_pct=fee_pct,
            )
            partial_pnl = float(meta.get("partial_pnl_usd") or 0.0)
            partial_fee = float(meta.get("partial_fee_usd") or 0.0)
            total_pnl = pnl_usd + partial_pnl
            total_fee = fee_usd + partial_fee
            roe_pct = pnl_pct * lev
            bal = self.tracker.get_balance() + pnl_usd
            self.tracker.set_balance(bal)
            sm = dict(sig.meta or {})
            exit_code = str(sm.get("exit_code") or sm.get("reason") or "exit")
            exit_label = str(sm.get("exit_label") or exit_reason_label(exit_code, sig.message))
            self._append_event(
                meta,
                {
                    "type": "exit",
                    "time": bar_time,
                    "price": exit_px,
                    "sl": pos.sl,
                    "reason": exit_code,
                    "exit_code": exit_code,
                    "exit_label": exit_label,
                    "held_bars": sm.get("held_bars"),
                    "pnl_usd": pnl_usd,
                    "pnl_pct": pnl_pct,
                    "gross_pnl_pct": gross_pnl_pct,
                    "fee_usd": fee_usd,
                    "fee_pct": fee_pct,
                    "fee_price_pct": fee_price_pct,
                    "roe_pct": roe_pct,
                    "message": sig.message,
                },
            )
            reason = f"{exit_code}|{exit_label}|{sig.message}"
            self.tracker.add_trade(
                {
                    "symbol": sym,
                    "side": pos.side,
                    "logic": pos.logic,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_px,
                    "entry_time": pos.entry_time,
                    "exit_time": bar_time,
                    "size": pos.size,
                    "leverage": lev,
                    "pnl_usd": total_pnl,
                    "pnl_pct": pnl_pct,
                    "roe_pct": roe_pct,
                    "fee_usd": total_fee,
                    "fee_pct": fee_pct,
                    "reason": reason,
                    "exit_code": exit_code,
                    "exit_label": exit_label,
                    "events_json": json.dumps(meta.get("events") or [], ensure_ascii=False),
                    "is_partial": 0,
                    **self._trade_context(pos, meta),
                }
            )
            if pos.id:
                self.tracker.delete_position_by_id(pos.id)
                self._last_trail_sl.pop(pos.id, None)
            else:
                self.tracker.delete_position(sym)
            exit_iv = normalize_sandbox_interval(
                str(meta.get("interval") or SANDBOX_INTERVAL)
            )
            self._last_exit_bar[self._slot_key(sym, exit_iv)] = bar_time
            logger.info(
                "沙盒平仓 #%s %s %s %s %s %s pnl=%.4fU fee=%.4fU 价变=%.2f%% ROE=%.1f%% (%gx) bal=%.2f",
                pos.id,
                sym,
                pos.side,
                pos.logic,
                exit_iv,
                exit_label,
                total_pnl,
                total_fee,
                pnl_pct,
                roe_pct,
                lev,
                bal,
            )
            return {
                "type": "exit",
                "id": pos.id,
                "symbol": sym,
                "side": pos.side,
                "logic": pos.logic,
                "price": exit_px,
                "entry_price": pos.entry_price,
                "exit_price": exit_px,
                "entry_time": pos.entry_time,
                "exit_time": bar_time,
                "leverage": lev,
                "pnl_usd": total_pnl,
                "pnl_pct": pnl_pct,
                "roe_pct": roe_pct,
                "fee_usd": total_fee,
                "exit_code": exit_code,
                "exit_label": exit_label,
                "events": meta.get("events") or [],
                "message": sig.message,
                "interval": exit_iv,
                "kline_close_time": bar_time,
                "status_label": f"沙盒平仓 · {exit_label} · {exit_iv} · {total_pnl:+.2f}U(含费)",
            }
        return None
