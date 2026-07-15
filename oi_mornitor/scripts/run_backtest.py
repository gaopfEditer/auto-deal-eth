#!/usr/bin/env python3
"""回踩 / 射击之星策略历史回测（成本防守 + 推动止损）。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from oi_mornitor.backtest.engine import run_pullback_backtest
from oi_mornitor.backtest.strategies import RiskConfig
from oi_mornitor.config import FAPI_BASE_URL, HTTP_TIMEOUT_SEC, STRATEGY_KLINE_LIMIT


async def fetch_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    limit: int,
) -> list[list]:
    url = (
        f"{FAPI_BASE_URL}/fapi/v1/klines"
        f"?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    )
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data if isinstance(data, list) else []


async def _run(symbols: list[str], interval: str, limit: int, risk: RiskConfig) -> list[dict]:
    out: list[dict] = []
    async with aiohttp.ClientSession(trust_env=True) as session:
        for sym in symbols:
            klines = await fetch_klines(session, sym, interval, limit)
            result = run_pullback_backtest(
                klines,
                symbol=sym,
                interval=interval,
                risk=risk,
            )
            out.append(result.to_dict())
            print(
                f"{sym}: signals={result.signals} trades={len(result.trades)} "
                f"win={result.win_rate:.1f}% total_pnl={result.total_pnl_pct:.2f}% "
                f"max_dd={result.max_drawdown_pct:.2f}%",
                file=sys.stderr,
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="OI+形态回踩策略回测")
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT",
        help="逗号分隔交易对",
    )
    parser.add_argument("--interval", default="1h", help="K 线周期")
    parser.add_argument("--limit", type=int, default=STRATEGY_KLINE_LIMIT, help="K 线根数")
    parser.add_argument("--stop", type=float, default=2.0, help="初始止损 %")
    parser.add_argument("--breakeven", type=float, default=1.0, help="成本防守触发浮盈 %")
    parser.add_argument("--trail-start", type=float, default=2.5, help="推动止损启动浮盈 %")
    parser.add_argument("--trail", type=float, default=1.2, help="追踪止损幅度 %")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    risk = RiskConfig(
        initial_stop_pct=args.stop,
        breakeven_trigger_pct=args.breakeven,
        trail_start_pct=args.trail_start,
        trail_pct=args.trail,
    )
    results = asyncio.run(_run(symbols, args.interval, args.limit, risk))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
