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

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from dealMsg.runner import disable_proxy_env, get_screenshot_dir, parse_ws_payload
from notifier import format_tv_signal_plain
from promat_publish import format_polished_for_terminal, is_high_confidence
from tv_ws.polish import polish_tv_signal
from tv_ws.signal_handler import (
    ONLY_TELEGRAM_PERIODS,
    is_allowed_ws_period,
    process_tradingview_ws_message,
)

# 仅 WSS 直连禁代理；不在模块级调用，避免影响 Telegram API
DEFAULT_WS_URI = os.getenv("MAIN_WS_URL", "wss://bz.a.gaopf.top/api/ws")
# 润色：本地 Ollama（config.PROMAT_ANALYSIS + prompts/promat），不再依赖 8000

# 连接后常见噪音，默认不打印；设 WS_VERBOSE=1 可恢复
_WS_QUIET_TYPES = frozenset({"echo", "welcome", "connected", "pong"})


def _ws_skip_telegram() -> bool:
    return os.getenv("WS_SKIP_TELEGRAM", "").strip().lower() in ("1", "true", "yes")


def _notify_telegram_started(*, mode: str, periods_label: str, ws_uri: str) -> None:
    """进程正式运行时发一条「已启动」到 Telegram（dry-run / 跳过 TG 时不发）。"""
    if _ws_skip_telegram():
        return
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        from notifier import send_telegram_message
    except Exception as e:
        print(f"[WS] 启动通知跳过（导入失败）: {e}", file=sys.stderr)
        return
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"✅ tv_ws 已启动\n"
        f"时间: {now}\n"
        f"模式: {mode}\n"
        f"周期: {periods_label}\n"
        f"WS: {ws_uri}"
    )
    ok = send_telegram_message(text)
    if ok:
        print("[WS] 已向 Telegram 发送「已启动」标识", file=sys.stderr)
    else:
        print("[WS] Telegram「已启动」发送失败", file=sys.stderr)


def _log_telegram_status() -> None:
    if _ws_skip_telegram():
        print("[WS] Telegram: 已关闭（WS_SKIP_TELEGRAM）", file=sys.stderr)
        return
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            print(
                "[WS] Telegram: 已配置；收到 tradingview 1h/4h 信号并完成润色+截图后推送图文",
                file=sys.stderr,
            )
        else:
            print(
                "[WS] Telegram: 未配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，不会推送",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"[WS] Telegram: 配置检查失败 ({e})", file=sys.stderr)


def _should_print_other_ws_message(data: dict) -> bool:
    msg_type = (data.get("type") or "").strip().lower()
    verbose = os.getenv("WS_VERBOSE", "").strip().lower() in ("1", "true", "yes")
    if msg_type in _WS_QUIET_TYPES:
        return verbose
    return True


def _pong_payload() -> str:
    return json.dumps(
        {
            "type": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


def _print_message_received(data: dict, *, allowed_periods=None) -> None:
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
        allowed = (
            "允许"
            if is_allowed_ws_period(period or "", allowed_periods=allowed_periods)
            else "跳过（周期不在允许列表）"
        )
        print(f"解析 -> ticker={ticker!r}  period={period!r}  [{allowed}]")
    print("-" * 56)


def _judge_signal_dry(data: dict, *, allowed_periods=None) -> None:
    """dry-run + --judge：对允许周期调用 Ollama，打印趋势/信心（不发担子）。"""
    ticker, period = parse_ws_payload(data)
    if not ticker:
        return
    if not is_allowed_ws_period(period or "", allowed_periods=allowed_periods):
        return
    signal_text = format_tv_signal_plain(data)
    print(f"[judge] 调用 Ollama 扫描 {ticker} {period} …", file=sys.stderr)
    ok, body = polish_tv_signal(signal_text)
    if not ok or not body:
        print("[judge] 模型判断失败", file=sys.stderr)
        return
    polished = body.get("polished") if isinstance(body, dict) else None
    if isinstance(polished, dict):
        print("[judge]\n" + format_polished_for_terminal(polished), file=sys.stderr)
        if is_high_confidence(polished):
            print(
                "[judge] → 高信心：正式发出时担子将带【高信心担子】标记",
                file=sys.stderr,
            )


def _handle_payload(
    data: dict,
    *,
    execute: bool,
    skip_screenshot: bool,
    publish_public: bool,
    only_telegram: bool = False,
    allowed_periods=None,
    judge: bool = False,
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
            # --only-telegram：只发信号原文到 TG，不截图、不润色、不发广场
            skip_screenshot=skip_screenshot or only_telegram,
            skip_publish=only_telegram,
            skip_polish=only_telegram,
            publish_to_square=publish_public and not only_telegram,
            skip_telegram=_ws_skip_telegram(),
            allowed_periods=allowed_periods,
        )
        print(f"[执行] ok={ok} {note}")
    else:
        _print_message_received(data, allowed_periods=allowed_periods)
        if judge:
            _judge_signal_dry(data, allowed_periods=allowed_periods)
        hint = (
            "去掉 --dry-run 后：仅 Telegram 原文（15m/1h/4h，不润色、不截图、不发广场）"
            if only_telegram
            else "去掉 --dry-run 后：Ollama 润色（趋势+信心）+ Telegram；"
            "高信心担子带【高信心担子】标；加 --public 再发广场"
        )
        if not judge and not only_telegram:
            hint += "\n       加 --judge 可在 dry-run 下对「允许」周期调用模型判断（不发送）"
        print(
            f"[提示] 当前为 --dry-run，不会截图、不会发广场\n       {hint}",
            file=sys.stderr,
        )


def _ws_connect_kwargs() -> dict:
    """长任务在子线程跑时仍需宽松 ping；可用环境变量覆盖。"""
    def _float(name: str, default: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return {
        "proxy": None,
        # 默认放宽：截图+Ollama+广场可能数分钟，期间仍需回 pong
        "ping_interval": _float("WS_PING_INTERVAL", 30.0),
        "ping_timeout": _float("WS_PING_TIMEOUT", 300.0),
        "close_timeout": _float("WS_CLOSE_TIMEOUT", 10.0),
    }


async def _safe_send_pong(ws) -> bool:
    try:
        await ws.send(_pong_payload())
        return True
    except Exception as e:
        print(f"[WS][WARN] 发送 pong 失败: {e}", file=sys.stderr)
        return False


async def _handle_payload_async(
    data: dict,
    *,
    execute: bool,
    skip_screenshot: bool,
    publish_public: bool,
    only_telegram: bool = False,
    allowed_periods=None,
    judge: bool = False,
) -> None:
    """同步链路（截图/润色/发帖）放到线程，避免阻塞 WebSocket 心跳。"""
    await asyncio.to_thread(
        _handle_payload,
        data,
        execute=execute,
        skip_screenshot=skip_screenshot,
        publish_public=publish_public,
        only_telegram=only_telegram,
        allowed_periods=allowed_periods,
        judge=judge,
    )


async def _listen_session(
    ws,
    *,
    print_raw: bool,
    execute: bool,
    skip_screenshot: bool,
    publish_public: bool,
    only_telegram: bool = False,
    allowed_periods=None,
    judge: bool = False,
) -> None:
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
            if await _safe_send_pong(ws):
                if os.getenv("WS_VERBOSE", "").strip().lower() in ("1", "true", "yes"):
                    print("[heartbeat] -> pong")
            continue

        if msg_type == "message_received" and data.get("message"):
            await _handle_payload_async(
                data,
                execute=execute,
                skip_screenshot=skip_screenshot,
                publish_public=publish_public,
                only_telegram=only_telegram,
                allowed_periods=allowed_periods,
                judge=judge,
            )
            continue

        if _should_print_other_ws_message(data):
            print("[其它]", json.dumps(data, ensure_ascii=False, indent=2)[:4000])


async def run_listener(
    ws_uri: str,
    *,
    print_raw: bool,
    execute: bool,
    skip_screenshot: bool,
    publish_public: bool,
    only_telegram: bool = False,
    allowed_periods=None,
    judge: bool = False,
) -> None:
    try:
        import websockets
        from websockets.exceptions import ConnectionClosed
    except ImportError:
        print("请先安装: pip install websockets", file=sys.stderr)
        sys.exit(1)

    disable_proxy_env()
    periods_label = ", ".join(sorted(allowed_periods or ONLY_TELEGRAM_PERIODS if only_telegram else ("1h", "4h")))
    # --only-telegram 强制不截图：只把信号原文推 Telegram
    if only_telegram:
        skip_screenshot = True
    if execute:
        if only_telegram:
            mode = f"仅 Telegram 原文（{periods_label}，不润色、不截图、不发广场）"
        else:
            mode = "润色 + Telegram 图文"
            if publish_public:
                mode += " + 广场(square_publish/CDP)"
            else:
                mode += "（默认不发布广场，加 --public 才发）"
            if not skip_screenshot:
                mode += " + 截图"
                try:
                    shot_dir = get_screenshot_dir()
                    os.makedirs(shot_dir, exist_ok=True)
                    print(f"[WS] 截图目录: {shot_dir}", file=sys.stderr)
                except OSError as e:
                    print(f"[WS][WARN] 截图目录不可用: {e}", file=sys.stderr)
            else:
                mode += "（跳过截图）"
        if not only_telegram:
            print(f"[WS] 润色: Ollama ({os.getenv('PROMAT_ANALYSIS_OLLAMA_BASE_URL', 'http://localhost:11434')})", file=sys.stderr)
        if publish_public and not only_telegram:
            print("[WS] 广场发布: binance.square_publish (CDP Chrome 9222)", file=sys.stderr)
        _log_telegram_status()
        _notify_telegram_started(mode=mode, periods_label=periods_label, ws_uri=ws_uri)
    else:
        mode = "仅打印（--dry-run）"
        if judge:
            mode += " + Ollama 判断（--judge，不发送）"
    print(f"[WS] 连接 {ws_uri} …（直连，{mode}）")
    connect_kw = _ws_connect_kwargs()
    print(
        f"[WS] keepalive ping_interval={connect_kw['ping_interval']}s "
        f"ping_timeout={connect_kw['ping_timeout']}s",
        file=sys.stderr,
    )

    backoff = float(os.getenv("WS_RECONNECT_SEC", "5") or "5")
    max_backoff = float(os.getenv("WS_RECONNECT_MAX_SEC", "120") or "120")

    while True:
        try:
            async with websockets.connect(ws_uri, **connect_kw) as ws:
                print("[WS] 已连接，等待消息（Ctrl+C 退出）\n")
                backoff = float(os.getenv("WS_RECONNECT_SEC", "5") or "5")
                await _listen_session(
                    ws,
                    print_raw=print_raw,
                    execute=execute,
                    skip_screenshot=skip_screenshot,
                    publish_public=publish_public,
                    only_telegram=only_telegram,
                    allowed_periods=allowed_periods,
                    judge=judge,
                )
        except KeyboardInterrupt:
            raise
        except ConnectionClosed as e:
            print(
                f"[WS] 连接断开 ({e})，{backoff:.0f}s 后自动重连 …",
                file=sys.stderr,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except Exception as e:
            err = str(e).lower()
            if "keepalive ping timeout" in err or "connection closed" in err:
                print(
                    f"[WS] 连接超时/断开 ({e})，{backoff:.0f}s 后自动重连 …",
                    file=sys.stderr,
                )
            else:
                print(f"[WS] 异常: {e}，{backoff:.0f}s 后重连 …", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tv_ws_pic_push_public",
        description="WebSocket TradingView：默认润色 + Telegram 图文；--public 才发布广场",
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
        "--no-screenshot",
        action="store_true",
        dest="skip_screenshot",
        help="仍推 Telegram，但不打开 TradingView 截图（--no-screenshot 同义）",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="发布到币安广场（binance.square_publish/CDP）；默认仅润色不发广场",
    )
    parser.add_argument(
        "--only-telegram",
        action="store_true",
        help="不润色、不截图、不发广场；15m/1h/4h 信号原文直推 Telegram",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="配合 --dry-run：对允许周期的信号调用 Ollama 输出趋势建议/信心指数（不发 Telegram/广场）",
    )
    args = parser.parse_args()

    if args.only_telegram and args.public:
        parser.error("--only-telegram 与 --public 不能同时使用")
    if args.judge and not args.dry_run:
        print(
            "[提示] --judge 主要用于 --dry-run；正式运行时润色本身已含趋势/信心",
            file=sys.stderr,
        )

    allowed_periods = ONLY_TELEGRAM_PERIODS if args.only_telegram else None

    try:
        asyncio.run(
            run_listener(
                args.url.strip(),
                print_raw=args.print_raw,
                execute=not args.dry_run,
                skip_screenshot=args.skip_screenshot,
                publish_public=args.public,
                only_telegram=args.only_telegram,
                allowed_periods=allowed_periods,
                judge=args.judge,
            )
        )
    except KeyboardInterrupt:
        print("\n[WS] 已退出")


if __name__ == "__main__":
    main()
