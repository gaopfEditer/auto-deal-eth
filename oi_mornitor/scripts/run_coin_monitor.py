#!/usr/bin/env python3
"""本地 WebSocket 监控：形态页关注币 × 回踩/Vegas/射击之星 + 可选 Telegram。"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from oi_mornitor.config import STRATEGY_DEFAULT_SYMBOLS, STRATEGY_KLINE_INTERVAL
from oi_mornitor.pattern_state_tracker import PatternStateTracker
from oi_mornitor.strategy.ws_monitor import CoinWsMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("run_coin_monitor")


def _load_symbols(from_watchlist: bool) -> list[str]:
    if from_watchlist:
        items = PatternStateTracker().list_watchlist()
        if items:
            return [w.symbol for w in items]
        logger.warning("形态 watchlist 为空，回退到 OI_STRATEGY_SYMBOLS / 默认列表")
    return list(STRATEGY_DEFAULT_SYMBOLS)


def _make_alert_handler(use_telegram: bool):
    def _on_alert(alert: dict) -> None:
        sym = alert.get("symbol", "")
        msg = alert.get("message", "")
        sig = alert.get("signal_type", "")
        price = alert.get("last_price", "")
        text = f"🎯 {sym} [{sig}] {msg}\n💵 {price}"
        print(text, flush=True)
        if not use_telegram:
            return
        try:
            from notifier import send_telegram_message

            send_telegram_message(text)
        except Exception as exc:
            logger.warning("Telegram 推送失败: %s", exc)

    return _on_alert


async def _main_async(args: argparse.Namespace) -> int:
    symbols = _load_symbols(args.from_watchlist)
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        logger.error("无监控币种")
        return 1

    monitor = CoinWsMonitor(
        symbols,
        interval=args.interval,
        on_alert=_make_alert_handler(args.telegram),
    )
    try:
        await monitor.start()
    except KeyboardInterrupt:
        monitor.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="币安合约 WS 回踩/射击之星本地监控")
    parser.add_argument(
        "--symbols",
        default="",
        help="逗号分隔，如 BTCUSDT,ETHUSDT（默认 OI_STRATEGY_SYMBOLS 或形态 watchlist）",
    )
    parser.add_argument(
        "--from-watchlist",
        action="store_true",
        help="从形态页 pattern_state.db watchlist 读取币种",
    )
    parser.add_argument(
        "--interval",
        default=STRATEGY_KLINE_INTERVAL,
        help="K 线周期，默认 1h",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="扳机时调用项目根 notifier.send_telegram_message",
    )
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
