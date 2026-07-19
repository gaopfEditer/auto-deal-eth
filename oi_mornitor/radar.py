"""
币安永续合约动态热钱雷达（免签 · asyncio + aiohttp）。

核心入口：
    from oi_mornitor.radar import get_hot_tickers
    hot = await get_hot_tickers()
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional

import aiohttp

from oi_mornitor.exchange_sources import fetch_fallback_feed
from oi_mornitor.config import (
    ALERT_COOLDOWN_SEC,
    BINANCE_BAN_COOLDOWN_SEC,
    FAPI_BASE_URL,
    HTTP_TIMEOUT_SEC,
    MAX_RETRIES,
    OI_5M_RECORD_INTERVAL_SEC,
    OI_CACHE_MAXLEN,
    OI_OI_BATCH_CONCURRENCY,
    OI_PCT_LIMIT,
    OI_TIER_HEAVY_MIN_USD,
    OI_TIER_MID_MIN_USD,
    OI_USD_LIMIT,
    OI_ZSCORE_HISTORY_LEN,
    OI_ZSCORE_MIN_SAMPLES,
    OI_ZSCORE_THRESHOLD,
    POLL_15M_SEC,
    POLL_5M_SEC,
    RATE_LIMIT_COOLDOWN_SEC,
    REQUEST_INTERVAL_SEC,
    RETRY_BACKOFF_SEC,
    SPOT_BASE_URL,
    TOP_N,
    proxy_url,
)
from oi_mornitor.capital_bias import (
    CAPITAL_BIAS_TF,
    build_capital_confluence,
    build_capital_intensity,
)
from oi_mornitor.market_matrix import MarketMatrixCache
from oi_mornitor.matrix_breakout import MatrixBreakoutEngine
from oi_mornitor.pattern_monitor import PatternMonitorEngine
from oi_mornitor.sandbox import SandboxEngine
from oi_mornitor.strategy.pullback_engine import PullbackStrategyEngine
from oi_mornitor.market_snapshot import (
    TIER_HEAVY,
    TIER_MID,
    classify_oi_tier,
    filter_usdt_perpetuals,
    oi_usd,
    pool_meta_from_counts,
    tier_label,
)
from oi_mornitor.rank_metrics import RankMetricsEngine, empty_rank_by_tf
from oi_mornitor.taker_flow import (
    empty_flow_by_tf,
    fetch_spot_taker_flow_batch,
    fetch_taker_flow_batch,
)

logger = logging.getLogger("OI_Radar")

# 前端 tf-btn 对应 OI 差分窗口（分钟）
OI_TF_WINDOWS: dict[str, int] = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "magenta": "\033[35m",
}


def _color(text: str, name: str) -> str:
    return f"{_C.get(name, '')}{text}{_C['reset']}"


def _fmt_compact(n: float, digits: int = 2, signed: bool = False) -> str:
    """金额紧凑格式：统一 M（百万美金），≥1B 用 B；变动量 signed=True 时带 +/-。"""
    abs_n = abs(n)
    prefix = "-" if n < 0 else ("+" if signed and n > 0 else "")
    if abs_n >= 1e9:
        return f"{prefix}{abs_n / 1e9:.{digits}f}B"
    return f"{prefix}{abs_n / 1e6:.{digits}f}M"


@dataclass
class TickerMeta:
    symbol: str
    quote_volume: float
    last_price: float
    price_change_pct_24h: float
    volume_rank: int
    oi_base: float = 0.0
    current_oi_usd: float = 0.0
    oi_tier: str = TIER_MID


@dataclass
class OISnapshot:
    ts: float
    oi_base: float
    price: float

    @property
    def oi_usd(self) -> float:
        return self.oi_base * self.price


class OIRadarCache:
    """每币种分钟级 OI 快照（默认保留 24h，支持多周期差分）。"""

    def __init__(self, maxlen: int = OI_CACHE_MAXLEN) -> None:
        self._maxlen = maxlen
        self._history: dict[str, Deque[OISnapshot]] = {}

    def update(self, symbol: str, oi_base: float, price: float) -> None:
        if symbol not in self._history:
            self._history[symbol] = deque(maxlen=self._maxlen)
        self._history[symbol].append(OISnapshot(time.time(), oi_base, price))

    def get_historical(self, symbol: str, minutes_ago: int) -> Optional[OISnapshot]:
        dq = self._history.get(symbol)
        if not dq:
            return None
        target_ts = time.time() - minutes_ago * 60
        for snap in reversed(dq):
            if snap.ts <= target_ts:
                return snap
        return dq[0]


class OI5mChangeHistory:
    """每币种缓存 24h（288 个 5 分钟周期）的 5m OI 变动（USD），用于 Z-Score。"""

    def __init__(
        self,
        maxlen: int = OI_ZSCORE_HISTORY_LEN,
        record_interval_sec: int = OI_5M_RECORD_INTERVAL_SEC,
    ) -> None:
        self._history: dict[str, Deque[float]] = {}
        self._last_record_ts: dict[str, float] = {}
        self._maxlen = maxlen
        self._interval = record_interval_sec

    def z_score_and_record(self, symbol: str, current_delta_usd: float) -> tuple[float, bool]:
        """用历史 5m 变动计算 Z-Score，再按 5 分钟节奏写入当前样本。"""
        hist = self._history.get(symbol)
        z = 0.0
        is_historic = False

        if hist and len(hist) >= OI_ZSCORE_MIN_SAMPLES:
            mean = statistics.mean(hist)
            std = statistics.pstdev(hist)
            if std > 1e-9:
                z = (current_delta_usd - mean) / std
                is_historic = z > OI_ZSCORE_THRESHOLD

        now = time.time()
        last = self._last_record_ts.get(symbol, 0.0)
        if symbol not in self._history:
            self._history[symbol] = deque(maxlen=self._maxlen)
        if now - last >= self._interval:
            self._history[symbol].append(current_delta_usd)
            self._last_record_ts[symbol] = now

        return z, is_historic


@dataclass
class AlertRecord:
    """已触发代币的冷却状态。"""

    ts: float
    window: str  # "5m" | "15m"
    direction: str  # "pump" | "dump"
    intensity: float  # abs(pct) 用于比较升级


@dataclass
class AlertCooldownStateMachine:
    """事件防抖：同币 15 分钟内抑制重复告警，除非升级或反转。"""

    cooldown_sec: int = ALERT_COOLDOWN_SEC
    active_alerts: dict[str, AlertRecord] = field(default_factory=dict)

    @staticmethod
    def _direction(delta_usd: float) -> str:
        return "pump" if delta_usd >= 0 else "dump"

    @staticmethod
    def _intensity(pct: float) -> float:
        return abs(pct)

    def _candidate(
        self,
        window: str,
        delta_usd: float,
        pct: float,
        triggered: bool,
    ) -> Optional[dict[str, Any]]:
        if not triggered:
            return None
        direction = self._direction(delta_usd)
        return {
            "window": window,
            "direction": direction,
            "intensity": self._intensity(pct),
            "delta_usd": delta_usd,
            "pct": pct,
        }

    def evaluate(
        self,
        symbol: str,
        raw_5m: Optional[dict[str, Any]],
        raw_15m: Optional[dict[str, Any]],
    ) -> tuple[list[str], bool, str]:
        """
        返回 (triggered_windows, should_emit, suppress_reason)。
        should_emit=False 时 suppress_reason 说明抑制原因。
        """
        candidates: list[dict[str, Any]] = []
        if raw_5m:
            candidates.append(raw_5m)
        if raw_15m:
            candidates.append(raw_15m)
        if not candidates:
            return [], False, ""

        windows = [c["window"] for c in candidates]
        # 优先用更强周期做主方向（15m > 5m）
        primary = max(candidates, key=lambda c: (0 if c["window"] == "5m" else 1, c["intensity"]))
        now = time.time()
        prev = self.active_alerts.get(symbol)

        if prev is None:
            self._commit(symbol, now, primary)
            return windows, True, "new"

        elapsed = now - prev.ts
        if elapsed >= self.cooldown_sec:
            self._commit(symbol, now, primary)
            return windows, True, "cooldown_expired"

        # 冷却期内
        cur_dir = primary["direction"]
        cur_int = primary["intensity"]
        cur_win = primary["window"]

        # 方向反转：5m 涨 → 跌（或相反）
        if cur_dir != prev.direction:
            self._commit(symbol, now, primary)
            return windows, True, "direction_reversal"

        # 15m 更剧烈同向异动（强度超过上次告警）
        if cur_win == "15m" and cur_dir == prev.direction and cur_int > prev.intensity:
            self._commit(symbol, now, primary)
            return windows, True, "15m_escalation"

        return windows, False, f"suppressed({elapsed:.0f}s/{self.cooldown_sec}s)"

    def _commit(self, symbol: str, ts: float, primary: dict[str, Any]) -> None:
        self.active_alerts[symbol] = AlertRecord(
            ts=ts,
            window=primary["window"],
            direction=primary["direction"],
            intensity=primary["intensity"],
        )

    def prune_expired(self) -> None:
        now = time.time()
        expired = [s for s, r in self.active_alerts.items() if now - r.ts >= self.cooldown_sec * 2]
        for s in expired:
            del self.active_alerts[s]


@dataclass
class GlobalTrendAuditor:
    """全场资金环境审计：基于 Top N 山寨币 5m OI 与价格联动态势。"""

    @staticmethod
    def _oi_pump(
        delta_5m_usd: float,
        pct_5m: float,
        usd_limit: float,
        pct_limit: float,
    ) -> bool:
        return delta_5m_usd > 0 and (
            abs(delta_5m_usd) >= usd_limit or abs(pct_5m) >= pct_limit
        )

    @staticmethod
    def _risk_regime(net_inflow: float, dominant: str) -> str:
        if net_inflow > 0 and dominant == "long":
            return "risk_on"
        if net_inflow < 0 and dominant == "short":
            return "risk_off"
        return "mixed"

    @classmethod
    def audit(
        cls,
        rows: list[dict[str, Any]],
        *,
        oi_usd_limit: float,
        oi_pct_limit: float,
        pool_size: int,
    ) -> dict[str, Any]:
        eligible = [r for r in rows if r.get("status") != "warming"]
        global_oi_net_inflow = sum(r.get("delta_5m_usd", 0.0) for r in eligible)

        long_build = 0
        short_suppress = 0
        for row in eligible:
            delta_5m_usd = row.get("delta_5m_usd", 0.0)
            pct_5m = row.get("pct_5m", 0.0)
            pct_price_5m = row.get("pct_price_5m", 0.0)
            if not cls._oi_pump(delta_5m_usd, pct_5m, oi_usd_limit, oi_pct_limit):
                continue
            if pct_price_5m > 0:
                long_build += 1
            elif pct_price_5m < 0:
                short_suppress += 1

        if long_build > short_suppress:
            dominant = "long"
            label = "多头主动建仓占优"
        elif short_suppress > long_build:
            dominant = "short"
            label = "空头主动压制占优"
        else:
            dominant = "neutral"
            label = "多空力量均衡"

        risk_regime = cls._risk_regime(global_oi_net_inflow, dominant)
        risk_labels = {
            "risk_on": "Risk-on",
            "risk_off": "Risk-off",
            "mixed": "Mixed",
        }

        capital_confluence = build_capital_confluence(rows, tf=CAPITAL_BIAS_TF)
        capital_intensity = build_capital_intensity(rows, tf=CAPITAL_BIAS_TF)

        return {
            "global_oi_net_inflow": round(global_oi_net_inflow, 2),
            "global_oi_net_inflow_fmt": _fmt_compact(global_oi_net_inflow, signed=True),
            "long_short_bias": {
                "long_build_count": long_build,
                "short_suppress_count": short_suppress,
                "dominant": dominant,
                "label": label,
            },
            "risk_regime": risk_regime,
            "risk_regime_label": risk_labels[risk_regime],
            "pool_monitored": len(eligible),
            "pool_size": pool_size,
            "capital_bias_tf": CAPITAL_BIAS_TF,
            "capital_confluence": capital_confluence,
            "capital_intensity": capital_intensity,
        }


@dataclass
class BinanceOIRadar:
    base_url: str = FAPI_BASE_URL
    top_n: int = TOP_N
    oi_usd_limit: float = OI_USD_LIMIT
    oi_pct_limit: float = OI_PCT_LIMIT
    request_interval: float = REQUEST_INTERVAL_SEC
    cache: OIRadarCache = field(default_factory=OIRadarCache)
    change_history: OI5mChangeHistory = field(default_factory=OI5mChangeHistory)
    cooldown: AlertCooldownStateMachine = field(default_factory=AlertCooldownStateMachine)
    rank_engine: RankMetricsEngine = field(default_factory=RankMetricsEngine)
    _ticker_meta: dict[str, TickerMeta] = field(default_factory=dict)
    _last_scan_ts: float = 0.0
    _last_eval_5m_ts: float = 0.0
    _last_eval_15m_ts: float = 0.0
    _last_hot: list[dict[str, Any]] = field(default_factory=list)
    _last_all: list[dict[str, Any]] = field(default_factory=list)
    _last_global_meta: dict[str, Any] = field(default_factory=dict)
    _last_pool_meta: dict[str, Any] = field(default_factory=dict)
    _consecutive_errors: int = 0
    _binance_ban_until: float = 0.0
    _data_source: str = "binance"
    # 代理连不上时临时直连（避免 HTTPS_PROXY 失效导致全站流向/K线全空）
    _proxy_disabled_until: float = 0.0
    _flow_cache: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    _spot_flow_cache: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    _taker_flow_status: str = "unavailable"  # live | cached | unavailable

    def _mark_binance_banned(self, reason: str = "418") -> None:
        self._binance_ban_until = time.time() + BINANCE_BAN_COOLDOWN_SEC
        logger.error(
            "币安暂时绕过 %.0fs（原因 %s）→ 将改用备选所并标注数据源",
            BINANCE_BAN_COOLDOWN_SEC,
            reason,
        )

    def _binance_banned(self) -> bool:
        return time.time() < self._binance_ban_until

    def proxy_disabled(self) -> bool:
        return time.time() < self._proxy_disabled_until

    def mark_proxy_down(self, reason: str = "connect_failed", cooldown_sec: float = 180.0) -> None:
        self._proxy_disabled_until = time.time() + cooldown_sec
        logger.warning(
            "代理不可用（%s），%.0fs 内改直连；请检查 HTTPS_PROXY / 本地代理是否启动",
            reason,
            cooldown_sec,
        )

    @staticmethod
    def _flow_has_volume(flow: dict[str, dict[str, float]] | None) -> bool:
        if not flow:
            return False
        return any(float(w.get("volume_usd") or 0) > 0 for w in flow.values())

    def _merge_flow_with_cache(
        self,
        symbols: list[str],
        fresh: dict[str, dict[str, dict[str, float]]],
        cache: dict[str, dict[str, dict[str, float]]],
    ) -> tuple[dict[str, dict[str, dict[str, float]]], int, int]:
        """写入有量数据到 cache；无量时回退 cache。返回 (merged, live_n, cached_n)。"""
        out: dict[str, dict[str, dict[str, float]]] = {}
        live_n = cached_n = 0
        for sym in symbols:
            cur = fresh.get(sym)
            if self._flow_has_volume(cur):
                cache[sym] = cur  # type: ignore[assignment]
                out[sym] = cur  # type: ignore[assignment]
                live_n += 1
                continue
            cached = cache.get(sym)
            if self._flow_has_volume(cached):
                out[sym] = cached
                cached_n += 1
            else:
                out[sym] = empty_flow_by_tf()
        return out, live_n, cached_n

    async def fetch_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> Any | None:
        """带重试、429 冷却与请求间隔的异步网关。"""
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await asyncio.sleep(self.request_interval)
                        self._consecutive_errors = 0
                        return data
                    if resp.status == 429:
                        logger.warning("触发限频 429，冷却 %.0fs …", RATE_LIMIT_COOLDOWN_SEC)
                        await asyncio.sleep(RATE_LIMIT_COOLDOWN_SEC)
                        continue
                    if resp.status == 418:
                        # 418 = 币安/WAF 封 IP，不是普通限频；多刷只会更糟
                        self._mark_binance_banned("418")
                        logger.error("IP 被币安硬封 418，停止重试本轮，改备选所")
                        return None
                    body = await resp.text()
                    logger.warning("HTTP %s %s — %s", resp.status, url, body[:200])
            except asyncio.TimeoutError:
                hint = ""
                if not proxy_url():
                    hint = "（未配置代理：请在 .env 设置 HTTPS_PROXY=http://127.0.0.1:7890）"
                logger.warning(
                    "请求超时 (%s/%s): %s%s",
                    attempt + 1,
                    MAX_RETRIES,
                    url,
                    hint,
                )
            except aiohttp.ClientError as exc:
                err = str(exc)
                logger.warning("网络异常 (%s/%s): %s — %s", attempt + 1, MAX_RETRIES, url, err)
                px = proxy_url()
                if px and ("7890" in err or "Connect call failed" in err or "Cannot connect to host 127.0.0.1" in err):
                    self.mark_proxy_down(reason="rest_proxy")
            except ValueError as exc:
                logger.error("JSON 解析失败: %s — %s", url, exc)
                return None
            await asyncio.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
        self._consecutive_errors += 1
        logger.error("请求失败，已放弃: %s", url)
        return None

    async def fetch_futures_ticker_24h_all(
        self,
        session: aiohttp.ClientSession,
    ) -> list[dict[str, Any]]:
        """单次请求：全市场 U 本位永续 24h ticker 聚合。"""
        url = f"{self.base_url}/fapi/v1/ticker/24hr"
        data = await self.fetch_json(session, url)
        if not isinstance(data, list):
            return []
        return filter_usdt_perpetuals(data)

    async def fetch_open_interest_batch(
        self,
        session: aiohttp.ClientSession,
        symbols: list[str],
    ) -> dict[str, float]:
        """并发拉取持仓量（用于量级分层；ticker/24hr 不含 openInterest）。"""
        if not symbols:
            return {}

        sem = asyncio.Semaphore(OI_OI_BATCH_CONCURRENCY)
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
        out: dict[str, float] = {}
        banned = False

        async def _one(sym: str) -> None:
            nonlocal banned
            if banned:
                return
            url = f"{self.base_url}/fapi/v1/openInterest?symbol={sym}"
            async with sem:
                if banned:
                    return
                try:
                    async with session.get(url, timeout=timeout) as resp:
                        if resp.status == 418:
                            banned = True
                            self._mark_binance_banned("418_oi_batch")
                            return
                        if resp.status != 200:
                            return
                        data = await resp.json()
                        if isinstance(data, dict) and "openInterest" in data:
                            out[sym] = float(data["openInterest"])
                except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError):
                    return

        await asyncio.gather(*[_one(s) for s in symbols])
        if banned:
            return {}
        return out

    def build_tier_pool(
        self,
        tickers: list[dict[str, Any]],
        oi_by_symbol: dict[str, float],
        *,
        data_source: str = "binance",
        data_source_label: str = "Binance",
        fallback_reason: str = "",
    ) -> list[TickerMeta]:
        """按总持仓 USD 分层，排除 < 1000 万。"""
        heavy = mid = excluded = 0
        eligible: list[tuple[TickerMeta, float]] = []

        for item in tickers:
            sym = str(item["symbol"])
            oi_base = oi_by_symbol.get(sym)
            if oi_base is None:
                continue
            price = float(item.get("lastPrice", 0))
            usd = oi_usd(oi_base, price)
            tier = classify_oi_tier(usd)
            if tier is None:
                excluded += 1
                continue
            if tier == TIER_HEAVY:
                heavy += 1
            else:
                mid += 1
            meta = TickerMeta(
                symbol=sym,
                quote_volume=float(item.get("quoteVolume", 0)),
                last_price=price,
                price_change_pct_24h=float(item.get("priceChangePercent", 0)),
                volume_rank=0,
                oi_base=oi_base,
                current_oi_usd=usd,
                oi_tier=tier,
            )
            eligible.append((meta, usd))

        eligible.sort(key=lambda x: x[1], reverse=True)
        pool: list[TickerMeta] = []
        for rank, (meta, _) in enumerate(eligible, start=1):
            meta.volume_rank = rank
            pool.append(meta)

        if TOP_N > 0:
            pool = pool[:TOP_N]

        self._data_source = data_source
        self._last_pool_meta = pool_meta_from_counts(
            ticker_count=len(tickers),
            heavy=heavy,
            mid=mid,
            excluded=excluded,
            eligible=len(pool),
            data_source=data_source,
            data_source_label=data_source_label,
            fallback_reason=fallback_reason,
        )
        self._ticker_meta = {m.symbol: m for m in pool}
        src_tag = f"[{data_source_label}]" if data_source != "binance" else "fapi"
        logger.info(
            "📋 %s 聚合池: ticker=%d · 大象=%d 中场=%d 排除<%s=%d · 监控=%d%s",
            src_tag,
            len(tickers),
            heavy,
            mid,
            _fmt_compact(OI_TIER_MID_MIN_USD),
            excluded,
            len(pool),
            f" · 原因={fallback_reason}" if fallback_reason else "",
        )
        return pool

    async def _pool_from_fallback(
        self,
        session: aiohttp.ClientSession,
        *,
        reason: str,
    ) -> list[TickerMeta]:
        feed = await fetch_fallback_feed(session, reason=reason)
        if not feed:
            logger.error("全部备选所失败，候选池为空")
            return []
        return self.build_tier_pool(
            feed.tickers,
            feed.oi_map,
            data_source=feed.source_id,
            data_source_label=feed.label,
            fallback_reason=reason,
        )

    async def get_active_market_pool(
        self,
        session: aiohttp.ClientSession,
    ) -> list[TickerMeta]:
        if self._binance_banned():
            remain = max(0, int(self._binance_ban_until - time.time()))
            logger.warning("币安冷却中（剩余 %ds），轮询备选所 Bybit→OKX→Bitget→Gate", remain)
            return await self._pool_from_fallback(session, reason="binance_ban_cooldown")

        tickers = await self.fetch_futures_ticker_24h_all(session)
        if not tickers:
            if self._binance_banned() or self._consecutive_errors > 0:
                return await self._pool_from_fallback(session, reason="binance_ticker_empty")
            return []
        symbols = [str(t["symbol"]) for t in tickers]
        oi_map = await self.fetch_open_interest_batch(session, symbols)
        if not oi_map:
            logger.warning("币安 OI 批量为空，轮询备选所")
            return await self._pool_from_fallback(session, reason="binance_oi_empty")
        return self.build_tier_pool(
            tickers,
            oi_map,
            data_source="binance",
            data_source_label="Binance",
        )

    def _row_from_meta(self, meta: TickerMeta) -> dict[str, Any]:
        return {
            "symbol": meta.symbol,
            "openInterest": meta.oi_base,
            "last_price": meta.last_price,
            "quote_volume": meta.quote_volume,
            "price_change_pct_24h": meta.price_change_pct_24h,
            "volume_rank": meta.volume_rank,
            "current_oi_usd": meta.current_oi_usd,
            "oi_tier": meta.oi_tier,
        }

    @staticmethod
    def _calc_delta(current: OISnapshot, past: Optional[OISnapshot]) -> tuple[float, float, float]:
        if past is None or past.oi_base <= 0:
            return 0.0, 0.0, 0.0
        delta_base = current.oi_base - past.oi_base
        pct = (delta_base / past.oi_base) * 100.0
        delta_usd = delta_base * current.price
        return delta_base, delta_usd, pct

    @staticmethod
    def _is_triggered(delta_usd: float, pct: float, usd_limit: float, pct_limit: float) -> bool:
        return abs(delta_usd) >= usd_limit or abs(pct) >= pct_limit

    @staticmethod
    def _calc_price_pct(current_price: float, past_price: float) -> float:
        if past_price <= 0:
            return 0.0
        return ((current_price - past_price) / past_price) * 100.0

    @staticmethod
    def _build_oi_by_tf(
        cache: OIRadarCache,
        symbol: str,
        current: OISnapshot,
    ) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for label, minutes in OI_TF_WINDOWS.items():
            past = cache.get_historical(symbol, minutes)
            if past is None:
                out[label] = {"delta_usd": 0.0, "pct": 0.0}
                continue
            _, delta_usd, pct = BinanceOIRadar._calc_delta(current, past)
            out[label] = {"delta_usd": round(delta_usd, 2), "pct": round(pct, 4)}
        return out

    @staticmethod
    def _build_price_by_tf(
        cache: OIRadarCache,
        symbol: str,
        current_price: float,
    ) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for label, minutes in OI_TF_WINDOWS.items():
            past = cache.get_historical(symbol, minutes)
            if past is None:
                out[label] = {"pct": 0.0}
                continue
            pct = BinanceOIRadar._calc_price_pct(current_price, past.price)
            out[label] = {"pct": round(pct, 4)}
        return out

    def _evaluate_symbol(
        self,
        row: dict[str, Any],
        *,
        eval_5m: bool,
        eval_15m: bool,
    ) -> Optional[dict[str, Any]]:
        symbol = row["symbol"]
        oi_base = row["openInterest"]
        price = row["last_price"]
        current = OISnapshot(time.time(), oi_base, price)

        past_5m = self.cache.get_historical(symbol, 5)
        past_15m = self.cache.get_historical(symbol, 15)

        self.cache.update(symbol, oi_base, price)

        if past_5m is None:
            row.update(
                {
                    "current_oi": oi_base,
                    "current_oi_usd": oi_base * price,
                    "delta_5m_usd": 0.0,
                    "pct_5m": 0.0,
                    "delta_15m_usd": 0.0,
                    "pct_15m": 0.0,
                    "pct_price_5m": 0.0,
                    "price_change_pct_24h": row.get("price_change_pct_24h", 0.0),
                    "status": "warming",
                    "triggered_windows": [],
                    "raw_triggered_windows": [],
                    "is_hot": False,
                    "is_alert": False,
                    "is_suppressed": False,
                    "alert_reason": "",
                    "type": "WARMING",
                    "individual_strength_score": None,
                    "is_historic_anomaly": False,
                    "global_intensity_rank": None,
                    "global_volume_rank": None,
                    "oi_tier": row.get("oi_tier", TIER_MID),
                    "oi_by_tf": {k: {"delta_usd": 0.0, "pct": 0.0} for k in OI_TF_WINDOWS},
                    "price_by_tf": {k: {"pct": 0.0} for k in OI_TF_WINDOWS},
                    "flow_by_tf": empty_flow_by_tf(),
                    "spot_flow_by_tf": empty_flow_by_tf(),
                    "rank_by_tf": empty_rank_by_tf(),
                }
            )
            return row

        _, delta_5m_usd, pct_5m = self._calc_delta(current, past_5m)
        _, delta_15m_usd, pct_15m = (
            self._calc_delta(current, past_15m) if past_15m else (0.0, 0.0, 0.0)
        )
        oi_by_tf = self._build_oi_by_tf(self.cache, symbol, current)
        price_by_tf = self._build_price_by_tf(self.cache, symbol, price)
        pct_price_5m = self._calc_price_pct(price, past_5m.price)

        z_score, is_historic = (0.0, False)
        if eval_5m:
            z_score, is_historic = self.change_history.z_score_and_record(symbol, delta_5m_usd)

        raw_5m = None
        raw_15m = None
        if eval_5m:
            t5 = self._is_triggered(delta_5m_usd, pct_5m, self.oi_usd_limit, self.oi_pct_limit)
            raw_5m = self.cooldown._candidate("5m", delta_5m_usd, pct_5m, t5)
        if eval_15m and past_15m is not None:
            t15 = self._is_triggered(
                delta_15m_usd, pct_15m, self.oi_usd_limit, self.oi_pct_limit
            )
            raw_15m = self.cooldown._candidate("15m", delta_15m_usd, pct_15m, t15)

        triggered_windows, should_emit, alert_reason = self.cooldown.evaluate(
            symbol, raw_5m, raw_15m
        )

        raw_windows: list[str] = []
        if raw_5m:
            raw_windows.append("5m")
        if raw_15m:
            raw_windows.append("15m")

        status = "normal"
        if triggered_windows:
            primary_delta = delta_15m_usd if "15m" in triggered_windows else delta_5m_usd
            status = "pump" if primary_delta > 0 else "dump"
        elif raw_windows:
            status = "suppressed"

        row.update(
            {
                "current_oi": oi_base,
                "current_oi_usd": oi_base * price,
                "delta_5m_usd": delta_5m_usd,
                "pct_5m": pct_5m,
                "delta_15m_usd": delta_15m_usd,
                "pct_15m": pct_15m,
                "pct_price_5m": round(pct_price_5m, 4),
                "price_change_pct_24h": row.get("price_change_pct_24h", 0.0),
                "status": status,
                "triggered_windows": triggered_windows,
                "raw_triggered_windows": raw_windows,
                "is_hot": bool(raw_windows),
                "is_alert": should_emit and bool(triggered_windows),
                "is_suppressed": bool(raw_windows) and not should_emit,
                "alert_reason": alert_reason,
                "type": (
                    "OI_PUMP"
                    if status == "pump"
                    else "OI_DUMP"
                    if status == "dump"
                    else "SUPPRESSED"
                    if status == "suppressed"
                    else "NORMAL"
                ),
                "individual_strength_score": round(z_score, 2) if eval_5m else None,
                "is_historic_anomaly": is_historic,
                "global_intensity_rank": None,
                "global_volume_rank": None,
                "oi_tier": row.get("oi_tier", TIER_MID),
                "oi_by_tf": oi_by_tf,
                "price_by_tf": price_by_tf,
                "flow_by_tf": empty_flow_by_tf(),
            }
        )
        return row

    @staticmethod
    def _apply_global_rankings(rows: list[dict[str, Any]]) -> None:
        """全场强度排名（|5m%| 降序）与全场量级排名（OI USD 降序）。"""
        eligible = [r for r in rows if r.get("status") != "warming"]
        if not eligible:
            return

        by_intensity = sorted(eligible, key=lambda r: abs(r.get("pct_5m", 0.0)), reverse=True)
        for rank, row in enumerate(by_intensity, start=1):
            row["global_intensity_rank"] = rank

        by_volume = sorted(eligible, key=lambda r: r.get("current_oi_usd", 0.0), reverse=True)
        for rank, row in enumerate(by_volume, start=1):
            row["global_volume_rank"] = rank

    def _print_scan_board(self, rows: list[dict[str, Any]], pool_size: int) -> None:
        ts = time.strftime("%H:%M:%S")
        print()
        print(_color(f"⚡ [{ts}] OI 动态雷达扫描 (候选池 {pool_size})", "bold"))
        print(_color("-" * 108, "dim"))
        hdr = (
            f"{'#':<4}{'币种':<12}{'量级':<6}{'持仓(OI)':<12}"
            f"{'5m Δ$':<11}{'5m %':<8}{'Z':<6}{'强度#':<6}{'量级#':<6}{'状态'}"
        )
        print(_color(hdr, "cyan"))
        print(_color("-" * 108, "dim"))

        for row in sorted(rows, key=lambda x: x.get("volume_rank", 999)):
            sym = row["symbol"]
            rank = row.get("volume_rank", "-")
            oi = row.get("current_oi_usd", 0)
            d5 = row.get("delta_5m_usd", 0.0)
            p5 = row.get("pct_5m", 0.0)
            z = row.get("individual_strength_score")
            gi = row.get("global_intensity_rank", "-")
            gv = row.get("global_volume_rank", "-")
            status = row.get("status", "normal")

            if status == "pump":
                tag = _color("🔥 热钱涌入", "red")
            elif status == "dump":
                tag = _color("🩸 热钱撤离", "green")
            elif status == "suppressed":
                tag = _color("🔇 已抑制", "dim")
            elif row.get("is_historic_anomaly"):
                tag = _color("💥 历史级异动", "yellow")
            elif row.get("triggered_windows"):
                tag = _color("⚠️ 异动", "yellow")
            else:
                tag = _color("⚪ 正常", "dim")

            z_txt = f"{z:.1f}" if z is not None else "-"
            tier = tier_label(row.get("oi_tier", ""))
            line = (
                f"{rank:<4}{sym:<12}{tier:<6}{_fmt_compact(oi):<12}"
                f"{_fmt_compact(d5, signed=True):<11}{p5:<+7.2f}%"
                f"{z_txt:<6}{str(gi):<6}{str(gv):<6}{tag}"
            )
            print(line)

        hot_count = sum(1 for r in rows if r.get("is_alert"))
        suppressed = sum(1 for r in rows if r.get("is_suppressed"))
        print(_color("-" * 108, "dim"))
        print(
            _color(
                f"扫描完成 · 告警 {hot_count} / 抑制 {suppressed} / 监控 {len(rows)}",
                "magenta",
            )
        )

    def _poll_flags(self) -> tuple[bool, bool]:
        """双周期门控：每 5m / 15m 各评估一次滚动窗口。"""
        now = time.time()
        eval_5m = now - self._last_eval_5m_ts >= POLL_5M_SEC
        eval_15m = now - self._last_eval_15m_ts >= POLL_15M_SEC
        if eval_5m:
            self._last_eval_5m_ts = now
        if eval_15m:
            self._last_eval_15m_ts = now
        return eval_5m, eval_15m

    async def scan(self, session: aiohttp.ClientSession) -> list[dict[str, Any]]:
        pool = await self.get_active_market_pool(session)
        if not pool:
            logger.error("候选池为空，跳过本轮扫描")
            return []

        eval_5m, eval_15m = self._poll_flags()
        if eval_5m:
            logger.info("⏱ 5m 周期评估启动")
        if eval_15m:
            logger.info("⏱ 15m 周期评估启动")

        symbols = [m.symbol for m in pool]
        # Taker 净流仅币安 K 线含 buy_quote；IP 硬封时跳过，避免连打 418。
        # 候选池来自备选所时仍尝试拉币安 flow；失败则回退内存缓存，避免榜单长期全空。
        if self._binance_banned():
            logger.warning("币安冷却中，本轮用缓存合约/现货 Taker 流向")
            flow_by_symbol, live_c, cached_c = self._merge_flow_with_cache(
                symbols, {}, self._flow_cache
            )
            spot_flow_by_symbol, live_s, cached_s = self._merge_flow_with_cache(
                symbols, {}, self._spot_flow_cache
            )
        else:
            (fresh_flow, flow_418), (fresh_spot, spot_418) = await asyncio.gather(
                fetch_taker_flow_batch(session, base_url=self.base_url, symbols=symbols),
                fetch_spot_taker_flow_batch(session, base_url=SPOT_BASE_URL, symbols=symbols),
            )
            if flow_418 or spot_418:
                self._mark_binance_banned("418_taker_flow")
            flow_by_symbol, live_c, cached_c = self._merge_flow_with_cache(
                symbols, fresh_flow, self._flow_cache
            )
            spot_flow_by_symbol, live_s, cached_s = self._merge_flow_with_cache(
                symbols, fresh_spot, self._spot_flow_cache
            )

        if live_c + live_s > 0:
            self._taker_flow_status = "live"
        elif cached_c + cached_s > 0:
            self._taker_flow_status = "cached"
        else:
            self._taker_flow_status = "unavailable"
            if proxy_url() and not self.proxy_disabled():
                # 全空且配置了代理：多半是代理挂了，下一轮直连重试
                self.mark_proxy_down(reason="taker_flow_empty")

        evaluated: list[dict[str, Any]] = []
        for meta in pool:
            row = self._evaluate_symbol(self._row_from_meta(meta), eval_5m=eval_5m, eval_15m=eval_15m)
            if row:
                row["flow_by_tf"] = flow_by_symbol.get(meta.symbol, empty_flow_by_tf())
                row["spot_flow_by_tf"] = spot_flow_by_symbol.get(meta.symbol, empty_flow_by_tf())
                evaluated.append(row)

        self.rank_engine.enrich(evaluated)
        self.cooldown.prune_expired()
        self._apply_global_rankings(evaluated)
        self._last_global_meta = GlobalTrendAuditor.audit(
            evaluated,
            oi_usd_limit=self.oi_usd_limit,
            oi_pct_limit=self.oi_pct_limit,
            pool_size=len(pool),
        )

        self._last_scan_ts = time.time()
        self._last_hot = [r for r in evaluated if r.get("is_alert")]
        self._last_all = evaluated
        self._print_scan_board(evaluated, len(pool))
        meta = self._last_global_meta
        logger.info(
            "🌐 全场资金: 5m 净流入 %s | %s | %s",
            meta.get("global_oi_net_inflow_fmt", "0"),
            meta.get("long_short_bias", {}).get("label", "-"),
            meta.get("risk_regime_label", "-"),
        )

        if self._last_hot:
            parts = []
            for r in self._last_hot:
                z = r.get("individual_strength_score")
                gi = r.get("global_intensity_rank")
                gv = r.get("global_volume_rank")
                hist = "💥" if r.get("is_historic_anomaly") else ""
                wins = "/".join(r.get("triggered_windows", []))
                parts.append(
                    f"{r['symbol']}[{wins}](Z={z},强度#{gi},量级#{gv}{hist})"
                )
            logger.info("🚨 新告警 %d: %s", len(self._last_hot), ", ".join(parts))

        suppressed_rows = [r for r in evaluated if r.get("is_suppressed")]
        if suppressed_rows:
            syms = ", ".join(
                f"{r['symbol']}({r.get('alert_reason')})" for r in suppressed_rows[:5]
            )
            logger.debug("🔇 冷却抑制 %d: %s", len(suppressed_rows), syms)

        return list(self._last_hot)

    @property
    def last_scan_ts(self) -> float:
        return self._last_scan_ts

    @property
    def last_hot_tickers(self) -> list[dict[str, Any]]:
        return list(self._last_hot)

    @property
    def last_all_rows(self) -> list[dict[str, Any]]:
        return list(self._last_all)

    @property
    def last_global_meta(self) -> dict[str, Any]:
        return dict(self._last_global_meta)

    @property
    def last_pool_meta(self) -> dict[str, Any]:
        meta = dict(self._last_pool_meta)
        meta["taker_flow_status"] = self._taker_flow_status
        meta["proxy_disabled"] = self.proxy_disabled()
        return meta

    @property
    def heavyweight_symbol_list(self) -> list[str]:
        """首轮扫描后即可用的大象级 symbol 列表（来自 ticker 分层，不依赖 warming）。"""
        return [m.symbol for m in self._ticker_meta.values() if m.oi_tier == TIER_HEAVY]


class RadarService:
    """常驻雷达服务，管理 ClientSession 生命周期与自动重连。"""

    def __init__(self) -> None:
        self.radar = BinanceOIRadar()
        self.matrix = MarketMatrixCache()
        self.breakout_engine = MatrixBreakoutEngine()
        self.pattern_engine = PatternMonitorEngine()
        self.pullback_engine = PullbackStrategyEngine(self.pattern_engine)
        self.sandbox_engine = SandboxEngine()
        self._session: aiohttp.ClientSession | None = None
        self._session_trust_env: bool | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        # 代理失效时关闭 trust_env，改为直连，否则所有请求都会卡在 127.0.0.1:7890
        want_trust = bool(proxy_url()) and not self.radar.proxy_disabled()
        if (
            self._session is None
            or self._session.closed
            or self._session_trust_env != want_trust
        ):
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "oi-mornitor/1.0"},
                trust_env=want_trust,
                connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300),
            )
            self._session_trust_env = want_trust
            logger.info("HTTP session trust_env=%s（代理%s）", want_trust, "开" if want_trust else "关/直连")
        return self._session

    async def scan_once(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        hot = await self.radar.scan(session)
        self.matrix.update_from_rows(self.radar.last_all_rows, scan_ts=self.radar.last_scan_ts)
        await self.breakout_engine.scan(
            session,
            self.radar.last_all_rows,
            base_url=self.radar.base_url,
            scan_ts=self.radar.last_scan_ts,
        )
        sandbox_open = {
            p.symbol.upper() for p in self.sandbox_engine.tracker.list_positions()
        }
        await self.pattern_engine.scan(
            session,
            base_url=self.radar.base_url,
            scan_ts=self.radar.last_scan_ts,
            pool_rows=self.radar.last_all_rows,
            fallback_symbols=self.radar.heavyweight_symbol_list,
            protect_symbols=sandbox_open,
        )
        for row in self.radar.last_all_rows:
            sym = str(row.get("symbol") or "")
            pct = row.get("pct_5m")
            if sym and pct is not None:
                try:
                    self.pullback_engine.set_oi_change_pct(sym, float(pct))
                except (TypeError, ValueError):
                    pass
        await self.pullback_engine.scan(
            session,
            base_url=self.radar.base_url,
            scan_ts=self.radar.last_scan_ts,
            pool_rows=self.radar.last_all_rows,
            fallback_symbols=self.radar.heavyweight_symbol_list,
        )
        await self.sandbox_engine.scan(
            session,
            base_url=self.radar.base_url,
            scan_ts=self.radar.last_scan_ts,
            pool_rows=self.radar.last_all_rows,
            fallback_symbols=self.radar.heavyweight_symbol_list,
            pattern_states=self.pattern_engine.last_states,
        )
        return hot

    async def _loop(self, interval_sec: int) -> None:
        while self._running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("雷达循环异常，5s 后重试: %s", exc)
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(interval_sec)

    async def start_background(self, interval_sec: int = 60) -> None:
        if self._running:
            return
        self._running = True
        await self._ensure_session()
        px = proxy_url()
        if px:
            logger.info("Binance REST 代理: %s", px)
        else:
            logger.warning(
                "未检测到 HTTPS_PROXY，直连 fapi.binance.com；"
                "若超时请在 .env 添加 HTTPS_PROXY=http://127.0.0.1:7890"
            )
        self._task = asyncio.create_task(self._loop(interval_sec), name="oi-radar-loop")
        logger.info("雷达后台循环已启动，间隔 %ds", interval_sec)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def get_snapshot(self) -> dict[str, Any]:
        return {
            "scan_ts": self.radar.last_scan_ts,
            "meta": self.radar.last_global_meta,
            "pool_meta": self.radar.last_pool_meta,
            "hot_tickers": self.radar.last_hot_tickers,
            "all_tickers": self.radar.last_all_rows,
            "market_matrix": self.matrix.last_matrix,
            "breakout_alerts": self.breakout_engine.last_alerts,
            "pattern": {
                **self.pattern_engine.get_payload(
                    pool_meta=self.radar.last_pool_meta,
                    fallback_symbols=self.radar.heavyweight_symbol_list,
                ),
                **self.pullback_engine.get_payload(),
                **self.sandbox_engine.get_payload(),
            },
            "pool_size": self.radar.last_pool_meta.get("eligible_count")
            or len(self.radar.last_all_rows),
            "thresholds": {
                "oi_usd_limit": self.radar.oi_usd_limit,
                "oi_pct_limit": self.radar.oi_pct_limit,
            },
        }

    async def get_market_matrix(self, *, force: bool = False) -> dict[str, Any]:
        rows = self.radar.last_all_rows
        if not rows:
            await self.scan_once()
            rows = self.radar.last_all_rows
        return await self.matrix.get(
            rows,
            scan_ts=self.radar.last_scan_ts,
            force=force,
        )


_service: RadarService | None = None


def get_service() -> RadarService:
    global _service
    if _service is None:
        _service = RadarService()
    return _service


async def get_hot_tickers() -> list[dict[str, Any]]:
    """供形态审计层调用的核心异步接口。"""
    return await get_service().scan_once()


async def get_market_matrix() -> dict[str, Any]:
    """四宫格热钱子榜单：每 60s 基于最新雷达快照刷新。"""
    return await get_service().get_market_matrix()


async def run_daemon(interval_sec: int = 60) -> None:
    """常驻守护进程入口。"""
    svc = get_service()
    await svc.start_background(interval_sec)
    try:
        if svc._task:
            await svc._task
    except asyncio.CancelledError:
        pass
    finally:
        await svc.stop()
