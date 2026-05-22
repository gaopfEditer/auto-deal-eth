#!/usr/bin/env python3
"""
tv_ws_pic_push_public 本地联调：不连 WebSocket，用一条模拟 tradingview 消息
走完整链路 → 格式化 signal → POST publish/signal → TradingView 截图。

默认样本为终端收到的 PAXGUSD 1h 倒锤子；与 tv_ws.pic_push_public 生产逻辑相同。

用法:
  python -m tv_ws.pic_push_public_test
  python -m tv_ws.pic_push_public_test --skip-screenshot
  python -m tv_ws.pic_push_public_test --ticker BTCUSD --period 4h
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from tv_ws.paths import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dealMsg.runner import disable_proxy_env, parse_ws_payload
from tv_ws.signal_handler import is_allowed_ws_period, process_tradingview_ws_message

disable_proxy_env()

DEFAULT_PUBLISH_URL = os.getenv(
    "SIGNAL_PUBLISH_URL", "http://127.0.0.1:8000/api/publish/signal"
)

# 与终端 id=11566 一致的模拟载荷
SAMPLE_PAXGUSD_1H: dict = {
    "type": "message_received",
    "message": {
        "id": 11566,
        "source": "tradingview",
        "source_id": "PAXGUSD_2026-05-18 23:00:00_倒锤子",
        "type": "倒锤子",
        "title": "PAXGUSD 倒锤子",
        "content": "触发信号",
        "metadata": {
            "low": 4529.25,
            "high": 4541.93,
            "time": "2026-05-18 23:00:00",
            "type": "倒锤子",
            "close": 4538.23,
            "period": "1h",
            "source": "tradingview",
            "ticker": "PAXGUSD",
            "original_message": (
                "PAXGUSD | 倒锤子 | 2026-05-18T15:00:00Z | 4538.23 | 4541.93 | "
                "4529.25 | 1h; 触发信号"
            ),
        },
        "sender": "TradingView",
        "sender_id": "tradingview_webhook",
        "created_at": "2026-05-18T16:00:06.000Z",
    },
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
}


def build_sample_payload(
    *,
    ticker: str,
    period: str,
    signal_type: str,
    close: float,
    high: float,
    low: float,
    bar_time: str,
    msg_id: int = 0,
) -> dict:
    title = f"{ticker} {signal_type}"
    return {
        "type": "message_received",
        "message": {
            "id": msg_id or int(datetime.now().timestamp()),
            "source": "tradingview",
            "source_id": f"{ticker}_{bar_time}_{signal_type}",
            "type": signal_type,
            "title": title,
            "content": "触发信号",
            "metadata": {
                "low": low,
                "high": high,
                "time": bar_time,
                "type": signal_type,
                "close": close,
                "period": period,
                "source": "tradingview",
                "ticker": ticker,
                "original_message": (
                    f"{ticker} | {signal_type} | {bar_time} | {close} | {high} | "
                    f"{low} | {period}; 触发信号"
                ),
            },
            "sender": "TradingView",
            "sender_id": "tradingview_webhook",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        },
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tv_ws_pic_push_public_test",
        description="模拟一条 tradingview WSS 消息：POST publish/signal + 截图",
    )
    parser.add_argument(
        "--ticker",
        default="",
        help="覆盖交易对，如 PAXGUSD、BTCUSD（默认用内置 PAXGUSD 样本）",
    )
    parser.add_argument("--period", default="1h", help="周期，默认 1h")
    parser.add_argument("--type", dest="signal_type", default="倒锤子", help="形态类型")
    parser.add_argument("--close", type=float, default=4538.23)
    parser.add_argument("--high", type=float, default=4541.93)
    parser.add_argument("--low", type=float, default=4529.25)
    parser.add_argument(
        "--time",
        default="2026-05-18 23:00:00",
        help="K 线时间展示串",
    )
    parser.add_argument(
        "--skip-screenshot",
        action="store_true",
        help="只 POST，不打开 TradingView（需 Chrome 9222 时去掉本参数）",
    )
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="只截图/打印，不 POST publish/signal",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="不推 Telegram",
    )
    args = parser.parse_args()

    if args.ticker.strip():
        payload = build_sample_payload(
            ticker=args.ticker.strip().upper(),
            period=args.period.strip(),
            signal_type=args.signal_type,
            close=args.close,
            high=args.high,
            low=args.low,
            bar_time=args.time,
        )
    else:
        payload = SAMPLE_PAXGUSD_1H

    ticker, period = parse_ws_payload(payload)
    print(f"[test] 派发地址: {DEFAULT_PUBLISH_URL}", file=sys.stderr)
    print(
        f"[test] ticker={ticker!r} period={period!r} "
        f"allowed={is_allowed_ws_period(period or '')}",
        file=sys.stderr,
    )

    if not is_allowed_ws_period(period or ""):
        print(
            f"[test] 周期 {period!r} 不在 WS_ALLOWED_PERIODS，"
            "请设置环境变量或改用 --period 1h/4h",
            file=sys.stderr,
        )
        return 2

    ok, note = process_tradingview_ws_message(
        payload,
        skip_screenshot=args.skip_screenshot,
        skip_publish=args.skip_publish,
        skip_telegram=args.skip_telegram,
    )
    print(f"[test] ok={ok} {note}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
