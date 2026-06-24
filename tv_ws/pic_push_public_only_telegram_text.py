#!/usr/bin/env python3
"""
TradingView WSS → 仅 Telegram 文本（不润色、不截图、不发广场）。

默认处理 15m / 1h / 4h，原文 signal 直推 Telegram（无配图）。

用法:
  python -m tv_ws.pic_push_public_only_telegram_text
  python tv_ws_pic_push_public_only_telegram_text.py
  python tv_ws_pic_push_public.py --only-telegram --no-screenshot
"""
from __future__ import annotations

import argparse
import asyncio
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
        prog="tv_ws_pic_push_public_only_telegram_text",
        description="TradingView WSS：15m/1h/4h 原文仅文本推 Telegram（不润色、不截图）",
    )
    parser.add_argument("--url", default=DEFAULT_WS_URI, help="WSS 地址")
    parser.add_argument("--print-raw", action="store_true", help="打印原始 JSON 行")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印解析结果，不 Telegram",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_listener(
                args.url.strip(),
                print_raw=args.print_raw,
                execute=not args.dry_run,
                skip_screenshot=True,
                publish_public=False,
                only_telegram=True,
                allowed_periods=ONLY_TELEGRAM_PERIODS,
            )
        )
    except KeyboardInterrupt:
        print("\n[WS] 已退出")


if __name__ == "__main__":
    main()
