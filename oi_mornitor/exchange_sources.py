"""
多交易所公共行情兜底：币安 418 / 失败时按优先级轮询。

统一输出币安兼容字段：
  symbol / lastPrice / quoteVolume / priceChangePercent / openInterest
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp

from oi_mornitor.config import (
    BITGET_BASE_URL,
    BYBIT_BASE_URL,
    FALLBACK_MIN_TICKERS,
    FALLBACK_SOURCE_ORDER,
    GATE_BASE_URL,
    HTTP_TIMEOUT_SEC,
    OKX_BASE_URL,
)

logger = logging.getLogger("OI_Radar")

FetchFn = Callable[[aiohttp.ClientSession], Awaitable["ExchangeFeed | None"]]


@dataclass
class ExchangeFeed:
    source_id: str
    label: str
    tickers: list[dict[str, Any]]

    @property
    def oi_map(self) -> dict[str, float]:
        return {
            str(t["symbol"]): float(t["openInterest"])
            for t in self.tickers
            if t.get("openInterest")
        }


def _is_usdt_perp_symbol(sym: str) -> bool:
    if not sym.endswith("USDT"):
        return False
    if "UPUSDT" in sym or "DOWNUSDT" in sym:
        return False
    return True


def _okx_inst_to_symbol(inst_id: str) -> str | None:
    # BTC-USDT-SWAP → BTCUSDT
    parts = inst_id.split("-")
    if len(parts) != 3 or parts[2] != "SWAP" or parts[1] != "USDT":
        return None
    return f"{parts[0]}USDT"


def _gate_contract_to_symbol(contract: str) -> str | None:
    # BTC_USDT → BTCUSDT
    if "_USDT" not in contract:
        return None
    base = contract.replace("_USDT", "")
    if not base:
        return None
    return f"{base}USDT"


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    source: str,
) -> Any | None:
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("%s HTTP %s — %s", source, resp.status, body[:200])
                return None
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("%s 请求失败: %s", source, exc)
        return None


async def fetch_bybit(session: aiohttp.ClientSession) -> ExchangeFeed | None:
    url = f"{BYBIT_BASE_URL}/v5/market/tickers?category=linear"
    payload = await _get_json(session, url, source="Bybit")
    if not isinstance(payload, dict):
        return None
    ret = payload.get("retCode")
    if ret is not None and int(ret) != 0:
        logger.warning("Bybit retCode=%s %s", ret, payload.get("retMsg"))
        return None

    out: list[dict[str, Any]] = []
    for item in (payload.get("result") or {}).get("list") or []:
        sym = str(item.get("symbol") or "")
        if not _is_usdt_perp_symbol(sym):
            continue
        try:
            last = float(item.get("lastPrice") or 0)
            oi = float(item.get("openInterest") or 0)
            pct = float(item.get("price24hPcnt") or 0) * 100.0
            quote = float(item.get("turnover24h") or 0)
        except (TypeError, ValueError):
            continue
        if last <= 0 or oi <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "lastPrice": last,
                "quoteVolume": quote,
                "priceChangePercent": pct,
                "openInterest": oi,
            }
        )
    if len(out) < FALLBACK_MIN_TICKERS:
        return None
    return ExchangeFeed("bybit", "Bybit", out)


async def fetch_okx(session: aiohttp.ClientSession) -> ExchangeFeed | None:
    """OKX SWAP ticker + open-interest 合并。"""
    tick_url = f"{OKX_BASE_URL}/api/v5/market/tickers?instType=SWAP"
    oi_url = f"{OKX_BASE_URL}/api/v5/public/open-interest?instType=SWAP"
    tick_payload, oi_payload = await asyncio.gather(
        _get_json(session, tick_url, source="OKX-ticker"),
        _get_json(session, oi_url, source="OKX-oi"),
    )
    if not isinstance(tick_payload, dict) or str(tick_payload.get("code", "0")) != "0":
        return None
    if not isinstance(oi_payload, dict) or str(oi_payload.get("code", "0")) != "0":
        return None

    oi_by_inst: dict[str, float] = {}
    for row in oi_payload.get("data") or []:
        inst = str(row.get("instId") or "")
        try:
            # oiCcy = 币单位持仓；与币安 openInterest 口径更接近
            oi = float(row.get("oiCcy") or row.get("oi") or 0)
        except (TypeError, ValueError):
            continue
        if oi > 0:
            oi_by_inst[inst] = oi

    out: list[dict[str, Any]] = []
    for item in tick_payload.get("data") or []:
        inst = str(item.get("instId") or "")
        sym = _okx_inst_to_symbol(inst)
        if not sym or not _is_usdt_perp_symbol(sym):
            continue
        oi = oi_by_inst.get(inst)
        if oi is None:
            continue
        try:
            last = float(item.get("last") or 0)
            open24 = float(item.get("open24h") or 0)
            quote = float(item.get("volCcy24h") or item.get("vol24h") or 0)
            pct = ((last - open24) / open24 * 100.0) if open24 > 0 else 0.0
        except (TypeError, ValueError):
            continue
        if last <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "lastPrice": last,
                "quoteVolume": quote,
                "priceChangePercent": pct,
                "openInterest": oi,
            }
        )
    if len(out) < FALLBACK_MIN_TICKERS:
        return None
    return ExchangeFeed("okx", "OKX", out)


async def fetch_bitget(session: aiohttp.ClientSession) -> ExchangeFeed | None:
    url = f"{BITGET_BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    payload = await _get_json(session, url, source="Bitget")
    if not isinstance(payload, dict) or str(payload.get("code", "00000")) not in ("00000", "0"):
        if isinstance(payload, dict):
            logger.warning("Bitget code=%s %s", payload.get("code"), payload.get("msg"))
        return None

    out: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        sym = str(item.get("symbol") or "")
        if not _is_usdt_perp_symbol(sym):
            continue
        try:
            last = float(item.get("lastPr") or item.get("last") or 0)
            # holdingAmount ≈ 持仓量（币）
            oi = float(item.get("holdingAmount") or item.get("openInterest") or 0)
            quote = float(item.get("quoteVolume") or item.get("usdtVolume") or 0)
            # change24h：比例（0.01=1%）；若已是百分比（如 -3.2）则直接用
            raw_chg = float(item.get("change24h") or 0)
            pct = raw_chg * 100.0 if abs(raw_chg) <= 1.5 else raw_chg
        except (TypeError, ValueError):
            continue
        if last <= 0 or oi <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "lastPrice": last,
                "quoteVolume": quote,
                "priceChangePercent": pct,
                "openInterest": oi,
            }
        )
    if len(out) < FALLBACK_MIN_TICKERS:
        return None
    return ExchangeFeed("bitget", "Bitget", out)


async def fetch_gate(session: aiohttp.ClientSession) -> ExchangeFeed | None:
    url = f"{GATE_BASE_URL}/api/v4/futures/usdt/tickers"
    payload = await _get_json(session, url, source="Gate")
    if not isinstance(payload, list):
        return None

    out: list[dict[str, Any]] = []
    for item in payload:
        contract = str(item.get("contract") or "")
        sym = _gate_contract_to_symbol(contract)
        if not sym or not _is_usdt_perp_symbol(sym):
            continue
        try:
            last = float(item.get("last") or 0)
            oi = float(item.get("total_size") or 0)
            pct = float(item.get("change_percentage") or 0)
            quote = float(item.get("volume_24h_quote") or item.get("volume_24h_settle") or 0)
        except (TypeError, ValueError):
            continue
        if last <= 0 or oi <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "lastPrice": last,
                "quoteVolume": quote,
                "priceChangePercent": pct,
                "openInterest": oi,
            }
        )
    if len(out) < FALLBACK_MIN_TICKERS:
        return None
    return ExchangeFeed("gate", "Gate", out)


_FETCHERS: dict[str, FetchFn] = {
    "bybit": fetch_bybit,
    "okx": fetch_okx,
    "bitget": fetch_bitget,
    "gate": fetch_gate,
}

SOURCE_LABELS = {
    "bybit": "Bybit",
    "okx": "OKX",
    "bitget": "Bitget",
    "gate": "Gate",
}


async def fetch_fallback_feed(
    session: aiohttp.ClientSession,
    *,
    reason: str = "",
    order: tuple[str, ...] | None = None,
) -> ExchangeFeed | None:
    """按配置顺序尝试备选所，返回第一个可用 feed。"""
    chain = order or FALLBACK_SOURCE_ORDER
    tried: list[str] = []
    for sid in chain:
        fn = _FETCHERS.get(sid)
        if not fn:
            logger.warning("未知备选源 %s，跳过", sid)
            continue
        tried.append(sid)
        feed = await fn(session)
        if feed and feed.tickers:
            label = f"{feed.label}（币安限流兜底）" if reason else feed.label
            feed.label = label
            logger.info(
                "✅ 备选源命中 %s · ticker=%d · 原因=%s · 尝试=%s",
                feed.source_id,
                len(feed.tickers),
                reason or "-",
                "→".join(tried),
            )
            return feed
        logger.warning("备选源 %s 无可用数据，继续…", sid)

    logger.error("全部备选源失败（%s）", "→".join(tried) or "空")
    return None


# ── K 线兜底（统一成币安 klines 数组格式）──────────────────────────

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

_BYBIT_INTERVAL = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}

_OKX_BAR = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}

_BITGET_GRAN = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}


def _binance_row(
    open_ms: int,
    o: float,
    h: float,
    l: float,
    c: float,
    vol: float,
    quote: float,
    interval: str,
) -> list[Any]:
    span = _INTERVAL_MS.get(interval, 900_000)
    close_ms = open_ms + span - 1
    return [open_ms, str(o), str(h), str(l), str(c), str(vol), close_ms, str(quote)]


def _symbol_to_okx_swap(symbol: str) -> str:
    base = symbol.upper().removesuffix("USDT")
    return f"{base}-USDT-SWAP"


def _symbol_to_gate_contract(symbol: str) -> str:
    base = symbol.upper().removesuffix("USDT")
    return f"{base}_USDT"


async def _fetch_binance_klines(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None,
) -> list[list[Any]]:
    url = (
        f"{base_url.rstrip('/')}/fapi/v1/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )
    if end_time is not None and end_time > 0:
        url += f"&endTime={int(end_time)}"
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 418:
                logger.warning("Binance klines 418（IP 硬封）%s", symbol)
                return []
            if resp.status != 200:
                body = await resp.text()
                logger.warning("Binance klines HTTP %s %s — %s", resp.status, symbol, body[:160])
                return []
            data = await resp.json()
            return data if isinstance(data, list) else []
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
        logger.warning("Binance klines 失败 %s: %s", symbol, exc)
        return []


async def _fetch_bybit_klines(
    session: aiohttp.ClientSession,
    *,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None,
) -> list[list[Any]]:
    iv = _BYBIT_INTERVAL.get(interval)
    if not iv:
        return []
    url = (
        f"{BYBIT_BASE_URL}/v5/market/kline"
        f"?category=linear&symbol={symbol}&interval={iv}&limit={limit}"
    )
    if end_time is not None and end_time > 0:
        url += f"&end={int(end_time)}"
    payload = await _get_json(session, url, source="Bybit-klines")
    if not isinstance(payload, dict) or int(payload.get("retCode") or -1) != 0:
        return []
    rows_raw = (payload.get("result") or {}).get("list") or []
    out: list[list[Any]] = []
    for row in rows_raw:
        try:
            open_ms = int(row[0])
            o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            vol, quote = float(row[5]), float(row[6])
        except (IndexError, TypeError, ValueError):
            continue
        out.append(_binance_row(open_ms, o, h, l, c, vol, quote, interval))
    out.sort(key=lambda r: int(r[0]))
    return out


async def _fetch_okx_klines(
    session: aiohttp.ClientSession,
    *,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None,
) -> list[list[Any]]:
    bar = _OKX_BAR.get(interval)
    if not bar:
        return []
    inst = _symbol_to_okx_swap(symbol)
    url = (
        f"{OKX_BASE_URL}/api/v5/market/candles"
        f"?instId={inst}&bar={bar}&limit={min(limit, 300)}"
    )
    if end_time is not None and end_time > 0:
        # OKX after = 请求此时间戳之前（更旧）的数据
        url += f"&after={int(end_time)}"
    payload = await _get_json(session, url, source="OKX-klines")
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        return []
    out: list[list[Any]] = []
    for row in payload.get("data") or []:
        try:
            open_ms = int(row[0])
            o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            vol = float(row[5])
            quote = float(row[7]) if len(row) > 7 else float(row[6])
        except (IndexError, TypeError, ValueError):
            continue
        out.append(_binance_row(open_ms, o, h, l, c, vol, quote, interval))
    out.sort(key=lambda r: int(r[0]))
    return out


async def _fetch_bitget_klines(
    session: aiohttp.ClientSession,
    *,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None,
) -> list[list[Any]]:
    gran = _BITGET_GRAN.get(interval)
    if not gran:
        return []
    url = (
        f"{BITGET_BASE_URL}/api/v2/mix/market/candles"
        f"?productType=USDT-FUTURES&symbol={symbol}&granularity={gran}&limit={min(limit, 200)}"
    )
    if end_time is not None and end_time > 0:
        url += f"&endTime={int(end_time)}"
    payload = await _get_json(session, url, source="Bitget-klines")
    if not isinstance(payload, dict) or str(payload.get("code")) not in ("00000", "0"):
        return []
    out: list[list[Any]] = []
    for row in payload.get("data") or []:
        try:
            open_ms = int(row[0])
            o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            vol = float(row[5])
            quote = float(row[6]) if len(row) > 6 else 0.0
        except (IndexError, TypeError, ValueError):
            continue
        out.append(_binance_row(open_ms, o, h, l, c, vol, quote, interval))
    out.sort(key=lambda r: int(r[0]))
    return out


async def _fetch_gate_klines(
    session: aiohttp.ClientSession,
    *,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None,
) -> list[list[Any]]:
    if interval not in _INTERVAL_MS:
        return []
    contract = _symbol_to_gate_contract(symbol)
    url = (
        f"{GATE_BASE_URL}/api/v4/futures/usdt/candlesticks"
        f"?contract={contract}&interval={interval}&limit={min(limit, 2000)}"
    )
    if end_time is not None and end_time > 0:
        url += f"&to={int(end_time) // 1000}"
    payload = await _get_json(session, url, source="Gate-klines")
    if not isinstance(payload, list):
        return []
    out: list[list[Any]] = []
    for row in payload:
        try:
            if isinstance(row, dict):
                open_ms = int(row["t"]) * 1000
                o, h, l, c = float(row["o"]), float(row["h"]), float(row["l"]), float(row["c"])
                vol = float(row.get("v") or 0)
                quote = float(row.get("sum") or 0)
            else:
                # 兼容数组格式 [t, v, c, h, l, o]
                open_ms = int(row[0]) * 1000
                o, h, l, c = float(row[5]), float(row[3]), float(row[4]), float(row[2])
                vol = float(row[1])
                quote = 0.0
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        out.append(_binance_row(open_ms, o, h, l, c, vol, quote, interval))
    out.sort(key=lambda r: int(r[0]))
    return out


_KLINE_FETCHERS: dict[str, Callable[..., Awaitable[list[list[Any]]]]] = {
    "bybit": _fetch_bybit_klines,
    "okx": _fetch_okx_klines,
    "bitget": _fetch_bitget_klines,
    "gate": _fetch_gate_klines,
}


async def fetch_klines_with_fallback(
    session: aiohttp.ClientSession,
    *,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None = None,
    binance_base_url: str | None = None,
    skip_binance: bool = False,
    order: tuple[str, ...] | None = None,
) -> tuple[list[list[Any]], str]:
    """
    拉单币种 K 线，币安失败/418 时按 FALLBACK_SOURCE_ORDER 轮询。
    返回 (klines, source_id)；source_id 为 binance / bybit / okx / …
    """
    sym = symbol.strip().upper()
    if not skip_binance and binance_base_url:
        rows = await _fetch_binance_klines(
            session,
            base_url=binance_base_url,
            symbol=sym,
            interval=interval,
            limit=limit,
            end_time=end_time,
        )
        if rows:
            return rows, "binance"

    chain = order or FALLBACK_SOURCE_ORDER
    for sid in chain:
        fn = _KLINE_FETCHERS.get(sid)
        if not fn:
            continue
        try:
            rows = await fn(
                session,
                symbol=sym,
                interval=interval,
                limit=limit,
                end_time=end_time,
            )
        except Exception as exc:  # noqa: BLE001 — 单源失败继续
            logger.warning("K线备选 %s 异常 %s: %s", sid, sym, exc)
            continue
        if rows:
            logger.info("K线备选命中 %s · %s · %s · n=%d", sid, sym, interval, len(rows))
            return rows, sid

    logger.warning("K线全部来源失败 %s %s", sym, interval)
    return [], ""
