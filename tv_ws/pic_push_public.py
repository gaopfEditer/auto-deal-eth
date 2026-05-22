#!/usr/bin/env python3
"""
tv_ws_pic_push_public — WebSocket 收 TradingView 信号 → 格式化 → POST 派发 → 可选截图。

详细说明见 tv_ws/USAGE.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

from tv_ws.paths import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dealMsg.runner import disable_proxy_env, parse_ws_payload
from tv_ws.signal_handler import is_allowed_ws_period, process_tradingview_ws_message

disable_proxy_env()
DEFAULT_WS_URI = os.getenv("MAIN_WS_URL", "wss://bz.a.gaopf.top/api/ws")
DEFAULT_PUBLISH_URL = os.getenv(
    "SIGNAL_PUBLISH_URL", "http://127.0.0.1:8000/api/publish/signal"
)


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


def _handle_payload(
    data: dict,
    *,
    execute: bool,
    skip_screenshot: bool,
) -> None:
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
            skip_screenshot=skip_screenshot,
            skip_telegram=os.getenv("WS_SKIP_TELEGRAM", "").strip().lower()
            in ("1", "true", "yes"),
        )
        print(f"[执行] ok={ok} {note}")
    else:
        _print_message_received(data)
        print(
            f"[提示] 当前为 --dry-run，不会 POST {DEFAULT_PUBLISH_URL}\n"
            "       去掉 --dry-run 后才会按 curl 方式派发 signal",
            file=sys.stderr,
        )


async def run_listener(
    ws_uri: str,
    *,
    print_raw: bool,
    execute: bool,
    skip_screenshot: bool,
) -> None:
    try:
        import websockets
    except ImportError:
        print("请先安装: pip install websockets", file=sys.stderr)
        sys.exit(1)

    disable_proxy_env()
    if execute:
        mode = "POST publish/signal"
        if not skip_screenshot:
            mode += " + 截图"
        else:
            mode += "（跳过截图）"
        print(f"[WS] 派发地址: {DEFAULT_PUBLISH_URL}", file=sys.stderr)
    else:
        mode = "仅打印（--dry-run）"
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
                _handle_payload(
                    data,
                    execute=execute,
                    skip_screenshot=skip_screenshot,
                )
                continue

            print("[其它]", json.dumps(data, ensure_ascii=False, indent=2)[:4000])


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tv_ws_pic_push_public",
        description="WebSocket TradingView：默认 POST publish/signal（与 curl 相同）",
    )
    parser.add_argument("--url", default=DEFAULT_WS_URI, help="WSS 地址")
    parser.add_argument("--print-raw", action="store_true", help="打印原始 JSON 行")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印解析结果，不 POST、不截图（旧默认行为）",
    )
    parser.add_argument(
        "--skip-screenshot",
        action="store_true",
        help="仍 POST publish/signal，但不打开 TradingView 截图",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_listener(
                args.url.strip(),
                print_raw=args.print_raw,
                execute=not args.dry_run,
                skip_screenshot=args.skip_screenshot,
            )
        )
    except KeyboardInterrupt:
        print("\n[WS] 已退出")


if __name__ == "__main__":
    main()
