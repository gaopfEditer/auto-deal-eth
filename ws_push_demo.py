#!/usr/bin/env python3
"""
WebSocket 推送：监听 MAIN_WS_URL，对 tradingview 信号（仅 1h/4h）截图并派发 publish/signal。

用法:
  python ws_push_demo.py              # 仅打印
  python ws_push_demo.py --run        # 截图 + 格式化 + POST publish/signal
  python ws_push_demo.py --print-raw --run

环境变量:
  WS_ALLOWED_PERIODS=1h,4h
  SIGNAL_PUBLISH_URL=http://127.0.0.1:8000/api/publish/signal
  MAIN_WS_URL=wss://bz.a.gaopf.top/api/ws
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dealMsg.runner import disable_proxy_env, parse_ws_payload
from ws_signal_handler import is_allowed_ws_period, process_tradingview_ws_message

disable_proxy_env()
DEFAULT_WS_URI = os.getenv("MAIN_WS_URL", "wss://bz.a.gaopf.top/api/ws")


def _pong_payload() -> str:
    return json.dumps(
        {
            "type": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


def _print_message_received(data: dict) -> None:
    msg = data.get("message")
    if not isinstance(msg, dict):
        print("[message_received] 无 message 字段:", json.dumps(data, ensure_ascii=False)[:500])
        return

    mid = msg.get("id", "")
    source = msg.get("source", "")
    content = msg.get("content", "")
    print("-" * 56)
    print(f"id={mid}  source={source}")
    print(f"content={content!r}")

    meta = msg.get("metadata")
    if isinstance(meta, dict) and meta:
        print("metadata:", json.dumps(meta, ensure_ascii=False, indent=2))

    ticker, period = parse_ws_payload(data)
    if ticker:
        allowed = "允许" if is_allowed_ws_period(period or "") else "跳过（周期不在 WS_ALLOWED_PERIODS）"
        print(f"解析 -> ticker={ticker!r}  period={period!r}  [{allowed}]")
    print("-" * 56)


def _handle_payload(data: dict, *, execute: bool) -> None:
    msg = data.get("message")
    if not isinstance(msg, dict):
        return
    source = (msg.get("source") or "").strip().lower()
    if source != "tradingview":
        print(f"[跳过] source={source!r}")
        return

    if execute:
        ok, note = process_tradingview_ws_message(
            data,
            skip_telegram=os.getenv("WS_SKIP_TELEGRAM", "").strip().lower()
            in ("1", "true", "yes"),
        )
        print(f"[执行] ok={ok} {note}")
    else:
        _print_message_received(data)


async def run_listener(
    ws_uri: str,
    *,
    print_raw: bool,
    execute: bool,
) -> None:
    try:
        import websockets
    except ImportError:
        print("请先安装: pip install websockets", file=sys.stderr)
        sys.exit(1)

    disable_proxy_env()
    mode = "执行截图+派发" if execute else "仅打印"
    print(f"[WS] 连接 {ws_uri} …（直连，{mode}）")

    async with websockets.connect(ws_uri, proxy=None) as ws:
        print("[WS] 已连接，等待消息（Ctrl+C 退出）\n")

        async for raw in ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")

            if print_raw:
                print("[raw]", raw[:2000] + ("…" if len(raw) > 2000 else ""))

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print("[WARN] 非 JSON:", raw[:300])
                continue

            msg_type = data.get("type")

            if msg_type == "heartbeat":
                await ws.send(_pong_payload())
                print("[heartbeat] -> pong")
                continue

            if msg_type == "message_received" and data.get("message"):
                _handle_payload(data, execute=execute)
                continue

            print("[其它]", json.dumps(data, ensure_ascii=False, indent=2)[:4000])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WebSocket TradingView 信号：打印或截图+publish"
    )
    parser.add_argument("--url", default=DEFAULT_WS_URI, help="WSS 地址")
    parser.add_argument("--print-raw", action="store_true", help="打印原始 JSON 行")
    parser.add_argument(
        "--run",
        action="store_true",
        help="对 1h/4h 信号执行截图并 POST publish/signal（否则仅打印）",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_listener(
                args.url.strip(),
                print_raw=args.print_raw,
                execute=args.run,
            )
        )
    except KeyboardInterrupt:
        print("\n[WS] 已退出")


if __name__ == "__main__":
    main()
