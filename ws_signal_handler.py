"""
WebSocket TradingView 信号：周期过滤 -> 截图 -> 标准文案 -> publish/signal。

供 main.py、ws_push_demo.py --run 共用。
"""
from __future__ import annotations

import os
import sys
from typing import FrozenSet, Tuple

from dealMsg.runner import (
    capture_tradingview_chart,
    disable_proxy_env,
    get_screenshot_dir,
    parse_ws_payload,
    period_to_tradingview_interval,
    _tv_binance_symbol,
)
from notifier import format_tv_signal_plain, publish_signal_to_hub, send_telegram_message
from notifier import format_tv_message

# 仅处理这些周期（小写 canonical）；可用环境变量 WS_ALLOWED_PERIODS=1h,4h 覆盖
_PERIOD_ALIASES = {
    "60": "1h",
    "60m": "1h",
    "h1": "1h",
    "1hour": "1h",
    "240": "4h",
    "240m": "4h",
    "h4": "4h",
    "4hour": "4h",
}


def _allowed_periods() -> FrozenSet[str]:
    raw = os.getenv("WS_ALLOWED_PERIODS", "1h,4h").strip()
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return frozenset(parts or ("1h", "4h"))


def canonical_ws_period(period: str) -> str:
    """将 metadata.period 规范为 1h / 4h / 15m 等。"""
    p = (period or "").strip().lower()
    if not p:
        return ""
    return _PERIOD_ALIASES.get(p, p)


def is_allowed_ws_period(period: str) -> bool:
    canon = canonical_ws_period(period)
    return bool(canon) and canon in _allowed_periods()


def process_tradingview_ws_message(
    obj: dict,
    *,
    skip_screenshot: bool = False,
    skip_publish: bool = False,
    skip_telegram: bool = False,
    use_telegram_markdown: bool = True,
) -> Tuple[bool, str]:
    """
    处理 type=message_received 且 source=tradingview 的完整载荷。

    返回 (是否已执行截图/派发, 说明)。
    """
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return False, "无 message 字段"

    source = (msg.get("source") or "").strip().lower()
    if source != "tradingview":
        return False, f"非 tradingview: {source!r}"

    ticker, period = parse_ws_payload(obj)
    if not ticker:
        return False, "缺少 ticker"

    if not is_allowed_ws_period(period or ""):
        canon = canonical_ws_period(period or "")
        allowed = ", ".join(sorted(_allowed_periods()))
        return False, f"周期 {period!r}（{canon!r}）不在允许列表 [{allowed}]，已跳过"

    signal_text = format_tv_signal_plain(obj)
    print("\n" + "=" * 56)
    print(signal_text)
    print("=" * 56 + "\n")

    if not skip_telegram:
        tg = format_tv_message(obj) if use_telegram_markdown else signal_text
        send_telegram_message(tg)

    # 先派发 signal（与 curl 一致）；截图失败也不影响已发出的 publish
    if not skip_publish:
        disable_proxy_env()
        ok = publish_signal_to_hub(signal_text)
        if not ok:
            return False, "publish/signal 失败（请确认 127.0.0.1:8000 服务已启动）"

    out_path = ""
    shot_note = ""
    if not skip_screenshot:
        symbol_part = _tv_binance_symbol(ticker)
        interval_key = period_to_tradingview_interval(period or "1h")
        out_path = os.path.join(
            get_screenshot_dir(), f"{symbol_part}_{interval_key}.png"
        )
        print(
            f"[WS] 截图: ticker={ticker} period={period!r} -> {out_path}",
            file=sys.stderr,
        )
        try:
            capture_tradingview_chart(
                ticker=ticker, timeframe=period or "1h", out_path=out_path
            )
            print(f"[WS] 截图完成: {out_path}", file=sys.stderr)
        except Exception as e:
            print(f"[WS] 截图失败（publish 已先发）: {e}", file=sys.stderr)
            shot_note = f" 截图失败: {e}"

    note = f"已处理 {ticker} {period}，已 POST publish/signal"
    if out_path:
        note += f" 图={out_path}"
    if shot_note:
        note += shot_note
    return True, note
