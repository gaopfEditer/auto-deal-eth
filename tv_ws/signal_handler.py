"""
WebSocket TradingView 信号：周期过滤 ->（可选）截图 ->（可选）Ollama 润色 ->（可选）广场 -> Telegram。

- --only-telegram：15m/1h/4h 信号原文直推 Telegram（不润色、不截图、不发广场）。
- 默认模式：截图 + 润色 + Telegram；--public 才发广场。
- Telegram 与是否 --public 无关；润色/截图/广场失败不阻断 Telegram（除非 WS_SKIP_TELEGRAM）。
"""
from __future__ import annotations

import os
import sys
from typing import FrozenSet, Tuple

from dealMsg.runner import (
    capture_tradingview_chart,
    chrome_debug_port,
    get_screenshot_dir,
    parse_ws_payload,
    period_to_tradingview_interval,
    _tv_binance_symbol,
)
from promat_publish import is_high_confidence, telegram_caption_from_publish_body
from notifier import (
    format_tv_signal_plain,
    format_tv_message,
    send_telegram_message_with_photo,
)
from tv_ws.polish import polish_tv_signal

_PERIOD_ALIASES = {
    "15": "15m",
    "15m": "15m",
    "60": "1h",
    "60m": "1h",
    "h1": "1h",
    "1hour": "1h",
    "240": "4h",
    "240m": "4h",
    "h4": "4h",
    "4hour": "4h",
}

# --only-telegram 默认放行周期
ONLY_TELEGRAM_PERIODS = frozenset({"15m", "1h", "4h"})


def _allowed_periods(override: FrozenSet[str] | None = None) -> FrozenSet[str]:
    if override is not None:
        return override
    raw = os.getenv("WS_ALLOWED_PERIODS", "1h,4h").strip()
    parts = [canonical_ws_period(p) for p in raw.split(",") if p.strip()]
    parts = [p for p in parts if p]
    return frozenset(parts or ("1h", "4h"))


def canonical_ws_period(period: str) -> str:
    p = (period or "").strip().lower()
    if not p:
        return ""
    return _PERIOD_ALIASES.get(p, p)


def is_allowed_ws_period(
    period: str,
    *,
    allowed_periods: FrozenSet[str] | None = None,
) -> bool:
    canon = canonical_ws_period(period)
    return bool(canon) and canon in _allowed_periods(allowed_periods)


def _push_telegram(
    obj: dict,
    *,
    signal_text: str,
    publish_body: dict | None,
    photo_path: str,
    use_telegram_markdown: bool,
) -> bool:
    tg_from_publish = telegram_caption_from_publish_body(publish_body)
    if tg_from_publish:
        tg_text = tg_from_publish
        tg_markdown = False
    else:
        tg_text = format_tv_message(obj) if use_telegram_markdown else signal_text
        tg_markdown = use_telegram_markdown

    photo = photo_path if photo_path and os.path.isfile(photo_path) else None
    print(
        f"[Telegram] 推送（与 --public 无关）: 配文 len={len(tg_text)} "
        f"{'+ 截图 ' + photo if photo else '(仅文本)'}",
        file=sys.stderr,
    )
    ok = send_telegram_message_with_photo(
        tg_text,
        photo,
        use_markdown=tg_markdown,
    )
    if ok:
        print("[Telegram] 发送成功", file=sys.stderr)
    else:
        print("[Telegram] 发送失败（见上方日志）", file=sys.stderr)
    return ok


def _square_post_text(publish_body: dict | None, signal_text: str) -> str:
    """广场正文：原始 signal 置顶，润色内容接在下面。"""
    original = (signal_text or "").strip()
    polished = telegram_caption_from_publish_body(publish_body).strip()
    if not original:
        return polished
    if not polished or polished == original:
        return original
    return f"{original}\n\n{polished}"


def _publish_to_binance_square(
    text: str,
    image_paths: list[str] | None,
    *,
    driver=None,
) -> tuple[bool, str]:
    from binance.square_publish import publish_square_post

    paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    print(
        f"[WS][square] 发布广场: text_len={len(text)} images={len(paths)}",
        file=sys.stderr,
    )
    own_driver = driver is None
    result = publish_square_post(
        text,
        paths or None,
        submit=True,
        allow_alt_url=False,
        force_square_goto=True,
        driver=driver,
        close_driver=own_driver,
    )
    if result.ok:
        if result.post_url:
            return True, result.post_url
        return True, "已点击发布（未解析帖子 URL）"
    return False, result.error or "square_publish 失败"


def _skip_polish() -> bool:
    return os.getenv("WS_SKIP_POLISH", "").strip().lower() in ("1", "true", "yes")


def _polish_signal(signal_text: str) -> tuple[bool, dict | None]:
    if _skip_polish():
        print("[WS] 已跳过润色(WS_SKIP_POLISH)", file=sys.stderr)
        return False, None
    return polish_tv_signal(signal_text)


def _capture_signal_screenshot(
    *,
    ticker: str,
    period: str,
    driver=None,
) -> tuple[str, str]:
    """返回 (out_path, shot_note)。路径见 config.SCREENSHOT_DIR / get_screenshot_dir()。"""
    shot_dir = get_screenshot_dir()
    os.makedirs(shot_dir, exist_ok=True)
    symbol_part = _tv_binance_symbol(ticker)
    interval_key = period_to_tradingview_interval(period or "1h")
    out_path = os.path.join(shot_dir, f"{symbol_part}_{interval_key}.png")
    cdp_port = chrome_debug_port()
    print(
        f"[WS] 截图(CDP 127.0.0.1:{cdp_port}): ticker={ticker} period={period!r} -> {out_path}",
        file=sys.stderr,
    )
    try:
        capture_tradingview_chart(
            ticker=ticker,
            timeframe=period or "1h",
            out_path=out_path,
            force_cdp=True,
            driver=driver,
            close_driver=False,
        )
        print(f"[WS] 截图完成: {out_path}", file=sys.stderr)
        return out_path, ""
    except Exception as e:
        print(f"[WS] 截图失败: {e}", file=sys.stderr)
        return out_path, f" 截图失败: {e}"


def process_tradingview_ws_message(
    obj: dict,
    *,
    skip_screenshot: bool = False,
    skip_publish: bool = False,
    skip_polish: bool = False,
    publish_to_square: bool = False,
    skip_telegram: bool = False,
    use_telegram_markdown: bool = True,
    allowed_periods: FrozenSet[str] | None = None,
) -> Tuple[bool, str]:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return False, "无 message 字段"

    source = (msg.get("source") or "").strip().lower()
    if source != "tradingview":
        return False, f"非 tradingview: {source!r}"

    ticker, period = parse_ws_payload(obj)
    if not ticker:
        return False, "缺少 ticker"

    if not is_allowed_ws_period(period or "", allowed_periods=allowed_periods):
        canon = canonical_ws_period(period or "")
        allowed = ", ".join(sorted(_allowed_periods(allowed_periods)))
        return False, f"周期 {period!r}（{canon!r}）不在允许列表 [{allowed}]，已跳过"

    signal_text = format_tv_signal_plain(obj)
    print("\n" + "=" * 56)
    print(signal_text)
    print("=" * 56 + "\n")

    publish_ok = True
    publish_body: dict | None = None
    square_ok = True
    square_note = ""
    out_path = ""
    shot_note = ""
    cdp_driver = None

    try:
        if publish_to_square and not skip_publish:
            from browser_automation import init_browser

            print("[WS] 复用同一 Chrome 会话：截图 → 润色 → 广场", file=sys.stderr)
            cdp_driver = init_browser(use_remote_debugging=True)

        # 1) 截图
        if not skip_screenshot:
            out_path, shot_note = _capture_signal_screenshot(
                ticker=ticker,
                period=period or "1h",
                driver=cdp_driver,
            )

        # 2) 润色（本地 Ollama，不动浏览器）
        if not skip_publish and not skip_polish:
            publish_ok, publish_body = _polish_signal(signal_text)
            if not publish_ok:
                print(
                    "[WS][WARN] 润色失败，广场/Telegram 将使用原始 signal 文案",
                    file=sys.stderr,
                )
            elif isinstance(publish_body, dict) and is_high_confidence(
                publish_body.get("polished")
            ):
                print(
                    "[WS] 高信心担子：Telegram/广场配文将带【高信心担子】标记",
                    file=sys.stderr,
                )
        elif skip_polish:
            print("[WS] 已跳过润色（only-telegram / skip_polish）", file=sys.stderr)

        # 3) 广场发布（强制刷新 Square，避免上次残留图文）
        if publish_to_square and not skip_publish:
            post_text = _square_post_text(publish_body, signal_text)
            images = [out_path] if out_path and os.path.isfile(out_path) else None
            square_ok, sq_detail = _publish_to_binance_square(
                post_text,
                images,
                driver=cdp_driver,
            )
            if square_ok:
                square_note = f" 广场已发布 ({sq_detail})"
                print(f"[WS][square] 成功: {sq_detail}", file=sys.stderr)
            else:
                square_note = f" 广场发布失败: {sq_detail}"
                print(f"[WS][square] 失败: {sq_detail}", file=sys.stderr)
    finally:
        if cdp_driver is not None:
            try:
                cdp_driver.quit()
            except Exception:
                pass

    tg_ok = True
    if not skip_telegram:
        tg_ok = _push_telegram(
            obj,
            signal_text=signal_text,
            publish_body=publish_body,
            photo_path=out_path,
            use_telegram_markdown=use_telegram_markdown,
        )

    if skip_publish or skip_polish:
        note = f"已处理 {ticker} {period}"
        if skip_polish and not skip_publish:
            note += "，未润色"
    elif publish_to_square:
        if square_ok and publish_ok:
            note = f"已处理 {ticker} {period}，已润色 + 广场发布"
        elif square_ok:
            note = f"已处理 {ticker} {period}，广场已发布（润色失败，用原文）"
        elif publish_ok:
            note = f"已处理 {ticker} {period}，已润色，广场发布失败"
        else:
            note = f"已处理 {ticker} {period}，润色与广场均失败"
    elif publish_ok:
        note = f"已处理 {ticker} {period}，已润色（未发广场）"
    else:
        note = f"已处理 {ticker} {period}，润色失败"
    if square_note:
        note += square_note
    if out_path:
        note += f" 图={out_path}"
    if shot_note:
        note += shot_note
    if not skip_telegram:
        note += " 已推 Telegram" if tg_ok else " Telegram 失败"

    if publish_to_square and not skip_publish:
        overall_ok = square_ok and (skip_telegram or tg_ok)
    else:
        overall_ok = (skip_publish or publish_ok) and (skip_telegram or tg_ok)
    return overall_ok, note
