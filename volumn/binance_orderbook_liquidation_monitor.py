#!/usr/bin/env python3
"""
币安 U 本位永续：本地订单簿 + 强平清算实时监控（asyncio + websockets + aiohttp）。

运行与测试说明见同目录 README.md。

快速命令：
  # 单币种（默认 ETHUSDT）
  python volumn/binance_orderbook_liquidation_monitor.py

  # 多币种（一条组合深度流 + 强平流按币种过滤）
  python volumn/binance_orderbook_liquidation_monitor.py --symbols ETHUSDT,BTCUSDT,SOLUSDT

  # 仅测 HTTP 快照（不连 WS）
  python volumn/binance_orderbook_liquidation_monitor.py --test-snapshot --symbols ETHUSDT,BTCUSDT

  # 短时测深度 WS 是否收包、能否完成首包同步（默认 20 秒）
  python volumn/binance_orderbook_liquidation_monitor.py --test-ws 20 --symbol ETHUSDT

  # 主力撤墙（需同时订阅 @trade + @depth，默认已开启）
  python volumn/binance_orderbook_liquidation_monitor.py --wall-threshold 1000 --obi-short-trigger -0.7
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import aiohttp
import websockets
from pathlib import Path

# 读取仓库根目录 .env（含 HTTPS_PROXY=http://127.0.0.1:7890）
_REPO_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    load_dotenv()
except ImportError:
    pass

FAPI_REST_BASE = "https://fapi.binance.com"
# 币安 2025+ 路由：depth 属 /public，aggTrade/强平 属 /market（旧 /ws/!forceOrder@arr 会 404）
FSTREAM_PUBLIC = "wss://fstream.binance.com/public"
FSTREAM_MARKET = "wss://fstream.binance.com/market"

DEFAULT_SYMBOL = "ETHUSDT"
SNAPSHOT_LIMIT = 100
LIQUIDATION_NOTIONAL_USD = 50_000.0
OBI_ALERT_THRESHOLD = 0.7
OBI_TOP_LEVELS = 5

# 主力撤墙：过去 N 毫秒内该价位真实成交量 vs 撤单量
WALL_VOLUME_THRESHOLD = float(os.getenv("WALL_VOLUME_THRESHOLD", "3000"))
OBI_TRIGGER_SHORT = float(os.getenv("OBI_TRIGGER_SHORT", "-0.7"))
TRADE_MATCH_WINDOW_MS = int(os.getenv("TRADE_MATCH_WINDOW_MS", "3000"))
WALL_EATEN_RATIO = float(os.getenv("WALL_EATEN_RATIO", "0.2"))  # 成交量 < 撤单量*该比例 → 视为主动撤单
RECENT_TRADES_MAXLEN = int(os.getenv("RECENT_TRADES_MAXLEN", "2000"))
_WALL_ALERT_COOLDOWN_SEC = float(os.getenv("WALL_ALERT_COOLDOWN_SEC", "3.0"))
ENABLE_SHORT_ON_SPOOF = os.getenv("ENABLE_SHORT_ON_SPOOF", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

RECONNECT_BASE_DELAY_SEC = 1.0
RECONNECT_MAX_DELAY_SEC = 60.0
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("QuantEngine")

# 兼容旧说明：单币种时仍可通过模块级变量名引用「当前唯一引擎」的簿（由引擎填充）
local_orderbook: Dict[str, Dict[float, float]] = {"bids": {}, "asks": {}}
orderbook_lock = asyncio.Lock()


class OrderBookSyncError(Exception):
    """订单簿序列不连续或同步状态非法。"""


@dataclass
class DepthSyncState:
    last_update_id: int = 0
    prev_event_u: Optional[int] = None
    synced: bool = False


def _symbol_lower(symbol: str) -> str:
    return symbol.strip().upper()


def _stream_symbol(symbol: str) -> str:
    return symbol.strip().lower()


def _proxy_url() -> Optional[str]:
    """优先 HTTPS_PROXY；与仓库根 .env 中配置一致。"""
    for key in (
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        v = (os.getenv(key) or "").strip()
        if v:
            return v
    return None


def _aiohttp_session() -> aiohttp.ClientSession:
    """REST 快照走代理：trust_env=True 会读取 HTTPS_PROXY 等环境变量。"""
    return aiohttp.ClientSession(trust_env=True)


def _websockets_connect_kwargs() -> Dict[str, Any]:
    kw: Dict[str, Any] = {
        "ping_interval": 20,
        "ping_timeout": 20,
        "close_timeout": 10,
        "max_size": 2 ** 24,
    }
    proxy = _proxy_url()
    if proxy:
        kw["proxy"] = proxy
    return kw


def parse_symbols(symbol: Optional[str], symbols: Optional[str]) -> List[str]:
    """--symbol 与 --symbols 二选一；--symbols 优先。"""
    if symbols and symbols.strip():
        parts = [_symbol_lower(s) for s in symbols.split(",") if s.strip()]
        if not parts:
            raise ValueError("--symbols 为空")
        return parts
    if symbol and symbol.strip():
        return [_symbol_lower(symbol)]
    return [DEFAULT_SYMBOL]


def _parse_levels(raw: List[List[str]]) -> Dict[float, float]:
    out: Dict[float, float] = {}
    for row in raw:
        if len(row) < 2:
            continue
        price = float(row[0])
        qty = float(row[1])
        if qty > 0:
            out[price] = qty
    return out


def compute_obi_from_book(
    bids: Dict[float, float],
    asks: Dict[float, float],
    top_n: int = OBI_TOP_LEVELS,
) -> Optional[float]:
    if not bids or not asks:
        return None
    bid_prices = sorted(bids.keys(), reverse=True)[:top_n]
    ask_prices = sorted(asks.keys())[:top_n]
    total_bid = sum(bids[p] for p in bid_prices)
    total_ask = sum(asks[p] for p in ask_prices)
    denom = total_bid + total_ask
    if denom <= 0:
        return None
    return (total_bid - total_ask) / denom


def top_n_total_volume(
    book: Dict[float, float],
    n: int = OBI_TOP_LEVELS,
    *,
    side: str = "bid",
) -> float:
    if not book:
        return 0.0
    prices = sorted(book.keys(), reverse=(side == "bid"))[:n]
    return sum(book[p] for p in prices)


def obi_human_label(obi: float) -> str:
    if obi >= 0.5:
        return "极度看多"
    if obi >= 0.2:
        return "偏多"
    if obi <= -0.5:
        return "极度看空"
    if obi <= -0.2:
        return "偏空"
    return "多空平衡"


class MarketStrategyEngine:
    """
    可读性日志：平稳时盘面汇总；未同步时限流告警；撤墙时 CRITICAL 框 + 行动建议。
    """

    def __init__(self, symbol: str, *, wall_threshold: float = WALL_VOLUME_THRESHOLD) -> None:
        self.symbol = _symbol_lower(symbol)
        self.wall_threshold = wall_threshold
        self._last_unsync_warn_ts: float = 0.0

    def log_unsync_throttled(self) -> None:
        now = time.monotonic()
        if now - self._last_unsync_warn_ts < 10.0:
            return
        self._last_unsync_warn_ts = now
        log.warning(
            "[❌数据不同步][%s] 正在等待本地订单簿与交易所 Sequence ID 完全对齐…",
            self.symbol,
        )

    def log_market_summary(
        self,
        *,
        best_bid: Optional[float],
        best_ask: Optional[float],
        bid5: float,
        ask5: float,
        obi: Optional[float],
        synced: bool,
    ) -> None:
        if not synced:
            self.log_unsync_throttled()
            return

        mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else (best_bid or best_ask or 0.0)
        obi_s = f"{obi:+.2f} ({obi_human_label(obi)})" if obi is not None else "n/a"
        status = "🟢数据已完全对齐" if synced else "🟡同步中"

        log.info(
            "[📊盘面汇总] %s | 现价: %.2f | 5档总买盘: %.2f | 5档总卖盘: %.2f | OBI: %s | 状态: %s",
            self.symbol,
            mid,
            bid5,
            ask5,
            obi_s,
            status,
        )

    def log_wall_spoof_critical(
        self,
        *,
        price: float,
        old_qty: float,
        new_qty: float,
        actual_vol: float,
        obi: float,
        window_ms: int,
        synced: bool,
    ) -> None:
        sync_txt = "synced=True (数据流 100% 真实可靠)" if synced else "synced=False (谨慎参考)"
        box = (
            "🔥🔥🔥 [🚨主力撤墙预警] 检测到非成交性断崖撤单！\n"
            "┌────────────────────────────────────────────────────────────────────────┐\n"
            f"│ 🔴 异常位置：Bids 关键支撑位 ${price:.2f}                                      \n"
            f"│ 📉 变动幅值：挂单量在 100ms 内从 {old_qty:.2f} ➡️ {new_qty:.2f} (瞬时归零)           \n"
            f"│ 🧐 链上核对：过去 {window_ms / 1000:.0f} 秒该点位真实成交仅 {actual_vol:.2f} "
            f"(判定为主动撤墙)        \n"
            f"│ 📊 动能共振：全局 OBI 瞬间 {obi:+.4f} ({obi_human_label(obi)})                      \n"
            f"│ ⚡ 状态跟踪：{sync_txt}                          \n"
            "└────────────────────────────────────────────────────────────────────────┘"
        )
        log.critical("%s", box)

    async def execute_hunting_plan(self, wall_price: float, obi: float) -> None:
        """拒绝市价追空；建议在撤墙下方挂限价多单（默认仅日志）。"""
        target_buy = wall_price * 0.98
        log.info(
            "[🚀行动][%s] 拒绝市价追空。建议在低位 $%.2f 挂限价多单（相对撤墙位 -2%%），"
            "捕捉踩踏插针 | OBI=%.4f",
            self.symbol,
            target_buy,
            obi,
        )
        if not ENABLE_SHORT_ON_SPOOF:
            return
        log.error(
            "[行动][%s] ENABLE_SHORT_ON_SPOOF=1 但尚未接入 place_limit_buy，请自行对接 fapi 下单",
            self.symbol,
        )


async def fetch_depth_snapshot(
    session: aiohttp.ClientSession,
    symbol: str,
    *,
    limit: int = SNAPSHOT_LIMIT,
) -> Tuple[int, Dict[float, float], Dict[float, float]]:
    url = f"{FAPI_REST_BASE}/fapi/v1/depth"
    params = {"symbol": _symbol_lower(symbol), "limit": limit}
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        data = await resp.json()
    last_id = int(data["lastUpdateId"])
    return last_id, _parse_levels(data.get("bids", [])), _parse_levels(data.get("asks", []))


def _validate_depth_event(evt: Dict[str, Any]) -> Tuple[int, int, List, List]:
    return int(evt["U"]), int(evt["u"]), evt.get("b") or [], evt.get("a") or []


def _apply_side_updates(book_side: Dict[float, float], updates: List[List[str]]) -> None:
    for row in updates:
        if len(row) < 2:
            continue
        price = float(row[0])
        qty = float(row[1])
        if qty > 0:
            book_side[price] = qty
        else:
            book_side.pop(price, None)


def _price_match(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-8, abs(a) * 1e-6)


@dataclass
class TradeTick:
    price: float
    quantity: float
    time_ms: int


class OrderBookEngine:
    """单交易对订单簿：独立 bids/asks/锁/同步状态。"""

    def __init__(self, symbol: str) -> None:
        self.symbol = _symbol_lower(symbol)
        self.stream_sym = _stream_symbol(symbol)
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.lock = asyncio.Lock()
        self.state = DepthSyncState()
        self._session: Optional[aiohttp.ClientSession] = None
        self._wall_alert_ts: Dict[float, float] = {}
        self.strategy = MarketStrategyEngine(self.symbol, wall_threshold=WALL_VOLUME_THRESHOLD)
        self.recent_trades: Deque[TradeTick] = deque(maxlen=RECENT_TRADES_MAXLEN)
        self.ws_events_seen: int = 0
        self.ws_events_applied: int = 0
        self.trades_seen: int = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = _aiohttp_session()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def full_reset(self) -> None:
        log.info("[订单簿][%s] 重新初始化快照", self.symbol)
        async with self.lock:
            self.bids.clear()
            self.asks.clear()
            self.recent_trades.clear()
        self.state = DepthSyncState()
        self._wall_alert_ts.clear()
        session = await self._get_session()
        last_id, bids, asks = await fetch_depth_snapshot(session, self.symbol)
        async with self.lock:
            self.bids = dict(bids)
            self.asks = dict(asks)
        self.state.last_update_id = last_id
        self.state.synced = False
        self.state.prev_event_u = None
        log.info(
            "[订单簿][%s] 快照就绪 lastUpdateId=%s bids=%s asks=%s",
            self.symbol,
            last_id,
            len(bids),
            len(asks),
        )

    def compute_obi(self) -> Optional[float]:
        return compute_obi_from_book(self.bids, self.asks)

    def _matched_volume_at_price(self, price: float, now_ms: int) -> float:
        cutoff = now_ms - TRADE_MATCH_WINDOW_MS
        total = 0.0
        for t in self.recent_trades:
            if t.time_ms >= cutoff and _price_match(t.price, price):
                total += t.quantity
        return total

    async def _check_bid_wall_pull(self, bids_delta: List[List[str]], now_ms: int) -> None:
        """
        买单墙（>= WALL_VOLUME_THRESHOLD）在增量中归零 → 核对近 TRADE_MATCH_WINDOW_MS 内该价位成交。
        若成交量 < 撤单量 * WALL_EATEN_RATIO 且 OBI <= OBI_TRIGGER_SHORT → 主力撤墙（多头陷阱）预警。
        """
        for row in bids_delta:
            if len(row) < 2:
                continue
            price = float(row[0])
            new_qty = float(row[1])
            old_qty = self.bids.get(price, 0.0)
            if old_qty < self.strategy.wall_threshold or new_qty != 0.0:
                continue

            actual_vol = self._matched_volume_at_price(price, now_ms)
            if actual_vol >= old_qty * WALL_EATEN_RATIO:
                continue

            obi = compute_obi_from_book(self.bids, self.asks)
            if obi is None or obi > OBI_TRIGGER_SHORT:
                continue

            last = self._wall_alert_ts.get(price, 0.0)
            if time.monotonic() - last < _WALL_ALERT_COOLDOWN_SEC:
                continue
            self._wall_alert_ts[price] = time.monotonic()

            self.strategy.log_wall_spoof_critical(
                price=price,
                old_qty=old_qty,
                new_qty=new_qty,
                actual_vol=actual_vol,
                obi=obi,
                window_ms=TRADE_MATCH_WINDOW_MS,
                synced=self.state.synced,
            )
            asyncio.create_task(self.strategy.execute_hunting_plan(price, obi))

    async def apply_depth_delta(self, bids_delta: List[List[str]], asks_delta: List[List[str]]) -> None:
        now_ms = int(time.time() * 1000)
        async with self.lock:
            if self.state.synced:
                await self._check_bid_wall_pull(bids_delta, now_ms)
            _apply_side_updates(self.bids, bids_delta)
            _apply_side_updates(self.asks, asks_delta)

    async def process_trade_event(self, evt: Dict[str, Any]) -> None:
        """aggTrade / trade：压入近 N 秒成交滑动窗口，供撤墙核对。"""
        if evt.get("e") not in ("trade", "aggTrade"):
            return
        if evt.get("s", "").upper() != self.symbol:
            return
        try:
            price = float(evt["p"])
            qty = float(evt["q"])
            trade_time = int(evt["T"])
        except (KeyError, TypeError, ValueError):
            return
        if qty <= 0:
            return
        self.trades_seen += 1
        tick = TradeTick(price=price, quantity=qty, time_ms=trade_time)
        async with self.lock:
            self.recent_trades.append(tick)

    async def snapshot_summary(self) -> Dict[str, Any]:
        async with self.lock:
            bids, asks = dict(self.bids), dict(self.asks)
        obi = compute_obi_from_book(bids, asks)
        best_bid = max(bids) if bids else None
        best_ask = min(asks) if asks else None
        return {
            "symbol": self.symbol,
            "bids": len(bids),
            "asks": len(asks),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "obi": obi,
            "synced": self.state.synced,
            "last_update_id": self.state.last_update_id,
        }

    async def _apply_event_and_obi(self, evt: Dict[str, Any]) -> None:
        _, u, b, a = _validate_depth_event(evt)
        await self.apply_depth_delta(b, a)
        self.state.prev_event_u = u
        self.ws_events_applied += 1

    async def process_depth_event(self, evt: Dict[str, Any]) -> None:
        if evt.get("e") not in (None, "depthUpdate"):
            return
        if evt.get("s", "").upper() != self.symbol:
            return

        self.ws_events_seen += 1
        U, u, _, _ = _validate_depth_event(evt)
        last_id = self.state.last_update_id

        if u < last_id:
            return

        if not self.state.synced:
            bridge = last_id + 1
            if not (U <= bridge and u >= bridge):
                return
            self.state.synced = True
            await self._apply_event_and_obi(evt)
            return

        if self.state.prev_event_u is None:
            raise OrderBookSyncError(f"[{self.symbol}] 已同步但缺少 prev_event_u")

        if U != self.state.prev_event_u + 1:
            raise OrderBookSyncError(
                f"[{self.symbol}] 序列断裂 U={U} 期望 {self.state.prev_event_u + 1}"
            )
        await self._apply_event_and_obi(evt)

def public_depth_stream_url(engines: List[OrderBookEngine]) -> str:
    """Partial depth @100ms → /public（高频订单簿）。"""
    streams = [f"{e.stream_sym}@depth@100ms" for e in engines]
    return f"{FSTREAM_PUBLIC}/stream?streams={'/'.join(streams)}"


def market_aggtrade_stream_url(engines: List[OrderBookEngine]) -> str:
    """Aggregate trades → /market（撤墙成交核对；勿与 depth 混在同一未路由连接）。"""
    streams = [f"{e.stream_sym}@aggTrade" for e in engines]
    return f"{FSTREAM_MARKET}/stream?streams={'/'.join(streams)}"


def liquidation_ws_url() -> str:
    return f"{FSTREAM_MARKET}/ws/!forceOrder@arr"


def _extract_stream_event(msg: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(msg, dict):
        return None
    if "data" in msg and isinstance(msg["data"], dict):
        return msg["data"]
    return msg


async def _ws_stream_loop(
    url: str,
    engines_by_symbol: Dict[str, OrderBookEngine],
    *,
    label: str,
    reset_snapshots: bool,
    depth_only: bool,
    trade_only: bool,
    stop_after: Optional[float] = None,
) -> None:
    t_end = (time.monotonic() + stop_after) if stop_after else None
    delay = RECONNECT_BASE_DELAY_SEC

    while True:
        if t_end and time.monotonic() >= t_end:
            return
        if reset_snapshots:
            for eng in engines_by_symbol.values():
                try:
                    await eng.full_reset()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.error(
                        "[订单簿][%s] 快照失败: %s（若在国内请配置 HTTPS_PROXY 或检查 fapi.binance.com）",
                        eng.symbol,
                        e,
                    )
                    raise

        log.info("[%s] 连接 %s", label, url)
        try:
            async with websockets.connect(url, **_websockets_connect_kwargs()) as ws:
                delay = RECONNECT_BASE_DELAY_SEC
                async for raw in ws:
                    if t_end and time.monotonic() >= t_end:
                        return
                    try:
                        msg = json.loads(raw)
                        evt = _extract_stream_event(msg)
                        if not evt:
                            continue
                        sym = (evt.get("s") or "").upper()
                        eng = engines_by_symbol.get(sym)
                        if not eng:
                            continue
                        ev = evt.get("e")
                        if trade_only and ev in ("trade", "aggTrade"):
                            await eng.process_trade_event(evt)
                        elif depth_only and ev in (None, "depthUpdate"):
                            await eng.process_depth_event(evt)
                    except OrderBookSyncError as e:
                        log.error("%s %s — 触发快照重建", label, e)
                        break
                    except (KeyError, TypeError, ValueError) as e:
                        log.error("[%s] 解析失败: %s", label, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if t_end and time.monotonic() >= t_end:
                return
            log.error("[%s] WebSocket 异常: %s — %ss 后重连", label, e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY_SEC)


async def _depth_public_loop(
    engines_by_symbol: Dict[str, OrderBookEngine],
    *,
    stop_after: Optional[float] = None,
) -> None:
    engines = list(engines_by_symbol.values())
    await _ws_stream_loop(
        public_depth_stream_url(engines),
        engines_by_symbol,
        label="深度/public",
        reset_snapshots=True,
        depth_only=True,
        trade_only=False,
        stop_after=stop_after,
    )


async def _aggtrade_market_loop(
    engines_by_symbol: Dict[str, OrderBookEngine],
    *,
    stop_after: Optional[float] = None,
) -> None:
    engines = list(engines_by_symbol.values())
    await _ws_stream_loop(
        market_aggtrade_stream_url(engines),
        engines_by_symbol,
        label="成交/market",
        reset_snapshots=False,
        depth_only=False,
        trade_only=True,
        stop_after=stop_after,
    )


async def run_market_loops(
    engines: List[OrderBookEngine],
    *,
    stop_after: Optional[float] = None,
) -> None:
    by_sym = {e.symbol: e for e in engines}
    await asyncio.gather(
        _depth_public_loop(by_sym, stop_after=stop_after),
        _aggtrade_market_loop(by_sym, stop_after=stop_after),
    )


def _parse_force_order_message(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        if raw.get("e") == "forceOrder" and "o" in raw:
            return [raw]
        data = raw.get("data")
        if isinstance(data, dict) and data.get("e") == "forceOrder":
            return [data]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


async def handle_liquidation_event(evt: Dict[str, Any], watch: Set[str]) -> None:
    order = evt.get("o") if isinstance(evt.get("o"), dict) else evt
    sym = (order.get("s") or "").upper()
    if sym not in watch:
        return

    side = (order.get("S") or "").upper()
    qty = float(order.get("q") or 0)
    price = float(order.get("p") or 0)
    if qty <= 0 or price <= 0:
        return

    notional = qty * price
    if notional <= LIQUIDATION_NOTIONAL_USD:
        return

    position_zh = "多头" if side == "SELL" else ("空头" if side == "BUY" else (side or "未知"))
    base = sym.replace("USDT", "").replace("USD", "") or sym
    log.warning(
        "[强平大单预警][%s] [%s] 强平 金额=%.2f USD qty=%s price=%s",
        sym,
        position_zh,
        notional,
        order.get("q"),
        order.get("p"),
    )


async def run_liquidation_loop(watch: Set[str]) -> None:
    url = liquidation_ws_url()
    delay = RECONNECT_BASE_DELAY_SEC
    log.info("[强平/market] 连接 %s | 监控币种: %s", url, ", ".join(sorted(watch)))

    while True:
        try:
            async with websockets.connect(url, **_websockets_connect_kwargs()) as ws:
                delay = RECONNECT_BASE_DELAY_SEC
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                        for evt in _parse_force_order_message(payload):
                            await handle_liquidation_event(evt, watch)
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        log.error("[强平] 解析失败: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[强平] 异常: %s — %ss 后重连", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY_SEC)


async def status_reporter(engines: List[OrderBookEngine], interval_sec: float) -> None:
    """平稳运行：每 N 秒一行盘面汇总；未同步时限流警告。"""
    while True:
        await asyncio.sleep(interval_sec)
        for eng in engines:
            async with eng.lock:
                bids = dict(eng.bids)
                asks = dict(eng.asks)
                synced = eng.state.synced
            obi = compute_obi_from_book(bids, asks)
            eng.strategy.log_market_summary(
                best_bid=max(bids) if bids else None,
                best_ask=min(asks) if asks else None,
                bid5=top_n_total_volume(bids, OBI_TOP_LEVELS, side="bid"),
                ask5=top_n_total_volume(asks, OBI_TOP_LEVELS, side="ask"),
                obi=obi,
                synced=synced,
            )


# ---------------------------------------------------------------------------
# 测试模式
# ---------------------------------------------------------------------------
async def run_test_snapshot(symbols: List[str]) -> int:
    """仅 HTTP 深度快照 + OBI，验证网络与 REST 是否正常。"""
    log.info("=== test-snapshot | 币种: %s ===", ", ".join(symbols))
    ok = True
    async with _aiohttp_session() as session:
        for sym in symbols:
            try:
                last_id, bids, asks = await fetch_depth_snapshot(session, sym)
                obi = compute_obi_from_book(bids, asks)
                spread = (min(asks.keys()) - max(bids.keys())) if bids and asks else None
                log.info(
                    "[OK][%s] lastUpdateId=%s bids=%s asks=%s best_bid=%s best_ask=%s spread=%s OBI=%s",
                    sym,
                    last_id,
                    len(bids),
                    len(asks),
                    max(bids) if bids else None,
                    min(asks) if asks else None,
                    f"{spread:.4f}" if spread is not None else "n/a",
                    f"{obi:.4f}" if obi is not None else "n/a",
                )
            except Exception as e:
                ok = False
                log.error("[FAIL][%s] %s", sym, e)
    return 0 if ok else 1


async def run_test_ws(symbols: List[str], seconds: float) -> int:
    """短时连接深度 WS，检查是否收包并完成至少一次 synced。"""
    log.info("=== test-ws %.0fs | 币种: %s ===", seconds, ", ".join(symbols))
    engines = [OrderBookEngine(s) for s in symbols]
    try:
        task = asyncio.create_task(run_market_loops(engines, stop_after=seconds))
        await asyncio.sleep(max(5.0, seconds))
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        ok = True
        for eng in engines:
            s = await eng.snapshot_summary()
            log.info(
                "[结果][%s] depth_seen=%s applied=%s trades_seen=%s synced=%s bids=%s asks=%s OBI=%s",
                s["symbol"],
                eng.ws_events_seen,
                eng.ws_events_applied,
                eng.trades_seen,
                s["synced"],
                s["bids"],
                s["asks"],
                f"{s['obi']:.4f}" if s["obi"] is not None else "n/a",
            )
            if eng.ws_events_seen == 0:
                log.error("[FAIL][%s] 未收到任何深度事件", s["symbol"])
                ok = False
            if not s["synced"]:
                log.warning(
                    "[WARN][%s] 未完成增量同步（可加长 --test-ws 秒数或检查网络）",
                    s["symbol"],
                )
        return 0 if ok else 1
    finally:
        await asyncio.gather(*(e.close() for e in engines), return_exceptions=True)


async def run_monitor(
    symbols: List[str],
    status_interval: float,
    *,
    skip_liquidation: bool = False,
) -> None:
    engines = [OrderBookEngine(s) for s in symbols]
    watch = frozenset(symbols)
    proxy = _proxy_url()
    log.info(
        "正式监控启动 | 币种=%s | public:depth@100ms + market:aggTrade | 撤墙阈值=%.0f OBI<=%.2f | 代理=%s",
        ", ".join(symbols),
        WALL_VOLUME_THRESHOLD,
        OBI_TRIGGER_SHORT,
        proxy or "(未设置，直连)",
    )
    if skip_liquidation:
        log.info("已跳过强平流（--skip-liquidation）")
    else:
        log.info("强平流: %s", liquidation_ws_url())

    tasks: List[asyncio.Task[Any]] = [
        asyncio.create_task(run_market_loops(engines), name="market"),
        asyncio.create_task(status_reporter(engines, status_interval), name="status"),
    ]
    if not skip_liquidation:
        tasks.append(asyncio.create_task(run_liquidation_loop(watch), name="liquidation"))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("收到退出信号，正在关闭…")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(e.close() for e in engines), return_exceptions=True)


def main() -> None:
    global WALL_VOLUME_THRESHOLD, OBI_TRIGGER_SHORT

    parser = argparse.ArgumentParser(
        description="币安 U 本位永续：订单簿 + 强平监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  单币种:  python %(prog)s
  多币种:  python %(prog)s --symbols ETHUSDT,BTCUSDT
  测快照:  python %(prog)s --test-snapshot --symbols ETHUSDT,BTCUSDT
  测 WS:   python %(prog)s --test-ws 25 --symbols ETHUSDT,BTCUSDT
        """.strip(),
    )
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="单币种（与 --symbols 二选一）")
    parser.add_argument(
        "--symbols",
        default="",
        help="多币种逗号分隔，如 ETHUSDT,BTCUSDT（优先于 --symbol）",
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=30.0,
        help="状态日志间隔秒（默认 30）",
    )
    parser.add_argument(
        "--test-snapshot",
        action="store_true",
        help="只拉 REST 深度快照并打印，不连 WebSocket",
    )
    parser.add_argument(
        "--test-ws",
        type=float,
        metavar="SECONDS",
        default=0,
        help="短时测试深度 WebSocket（秒），例如 --test-ws 20",
    )
    parser.add_argument(
        "--wall-threshold",
        type=float,
        default=None,
        help=f"买单墙撤单检测阈值（默认 {WALL_VOLUME_THRESHOLD:g}）",
    )
    parser.add_argument(
        "--obi-short-trigger",
        type=float,
        default=None,
        help=f"撤墙做空 OBI 上限（默认 {OBI_TRIGGER_SHORT}）",
    )
    parser.add_argument(
        "--skip-liquidation",
        action="store_true",
        help="不连接强平流（排查 404 或仅测订单簿时用）",
    )
    args = parser.parse_args()

    if args.wall_threshold is not None:
        WALL_VOLUME_THRESHOLD = args.wall_threshold
    if args.obi_short_trigger is not None:
        OBI_TRIGGER_SHORT = args.obi_short_trigger

    try:
        symbols = parse_symbols(args.symbol, args.symbols or None)
    except ValueError as e:
        log.error("%s", e)
        raise SystemExit(2) from e

    if args.test_snapshot:
        raise SystemExit(asyncio.run(run_test_snapshot(symbols)))

    if args.test_ws and args.test_ws > 0:
        raise SystemExit(asyncio.run(run_test_ws(symbols, args.test_ws)))

    try:
        asyncio.run(
            run_monitor(
                symbols,
                args.status_interval,
                skip_liquidation=args.skip_liquidation,
            )
        )
    except KeyboardInterrupt:
        log.info("已退出 (Ctrl+C)")


if __name__ == "__main__":
    main()
