#!/usr/bin/env python3
"""
TradingView WSS → 仅 Telegram（不润色、不发广场）。

默认处理 15m / 1h / 4h 全部周期，原文 signal + 截图直推 Telegram。

用法:
  python -m tv_ws.pic_push_public_only_telegram
  python tv_ws_pic_push_public_only_telegram.py
  python tv_ws_pic_push_public_only_telegram.py --skip-screenshot
  python tv_ws_pic_push_public_only_telegram.py --dry-run --print-raw
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from tv_ws.paths import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from tv_ws.pic_push_public import DEFAULT_WS_URI, run_listener
from tv_ws.signal_handler import ONLY_TELEGRAM_PERIODS


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tv_ws_pic_push_public_only_telegram",
        description="TradingView WSS：15m/1h/4h 原文+截图直推 Telegram（不润色、不发广场）",
    )
    parser.add_argument("--url", default=DEFAULT_WS_URI, help="WSS 地址")
    parser.add_argument("--print-raw", action="store_true", help="打印原始 JSON 行")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印解析结果，不截图、不 Telegram",
    )
    parser.add_argument(
        "--skip-screenshot",
        action="store_true",
        help="仍推 Telegram 原文，但不截图",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_listener(
                args.url.strip(),
                print_raw=args.print_raw,
                execute=not args.dry_run,
                skip_screenshot=args.skip_screenshot,
                publish_public=False,
                only_telegram=True,
                allowed_periods=ONLY_TELEGRAM_PERIODS,
            )
        )
    except KeyboardInterrupt:
        print("\n[WS] 已退出")


if __name__ == "__main__":
    main()
