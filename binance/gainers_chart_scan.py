"""榜单币种：依次截图 → 本地图分析 → Telegram。"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Sequence

from config import BINANCE_RANKS_CHART_PERIOD, BINANCE_RANKS_EXCLUDE_BASES
from dealMsg.runner import (
    capture_tradingview_chart,
    get_screenshot_dir,
    period_to_tradingview_interval,
    _tv_binance_symbol,
)
from image_llm_analyzer import analyze_chart_promat, extract_json_from_gemini_text
from notifier import send_telegram_message_with_photo

_QUOTE_SUFFIXES = ("USDT", "USDC", "USD1", "BUSD", "FDUSD", "TUSD")


@dataclass(frozen=True)
class ScanTarget:
    symbol: str
    section: str
    rank: int
    change: str = ""
    price: str = ""


def parse_exclude_bases(raw: str | None = None) -> FrozenSet[str]:
    text = (raw if raw is not None else BINANCE_RANKS_EXCLUDE_BASES) or ""
    parts = [p.strip().lower() for p in text.replace(";", ",").split(",") if p.strip()]
    return frozenset(parts)


def base_asset(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    for suffix in _QUOTE_SUFFIXES:
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


def collect_scan_targets(
    payload: Dict[str, Any],
    *,
    liquidity_top: int,
    gainers_top: int,
    exclude_bases: FrozenSet[str],
) -> List[ScanTarget]:
    """流动性 TOP → 涨幅 TOP，去重；排除指定 base。"""
    seen: set[str] = set()
    out: List[ScanTarget] = []

    def _add(section: str, top_n: int) -> None:
        if top_n <= 0:
            return
        sec = payload.get(section)
        if not isinstance(sec, dict):
            return
        items = sec.get("items") or []
        if not isinstance(items, list):
            return
        rank = 0
        for item in items:
            if rank >= top_n:
                break
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").strip().upper()
            if not sym or sym in seen:
                continue
            b = base_asset(sym).lower()
            if b in exclude_bases:
                continue
            seen.add(sym)
            rank += 1
            out.append(
                ScanTarget(
                    symbol=sym,
                    section=section,
                    rank=rank,
                    change=str(item.get("change") or "").strip(),
                    price=str(item.get("price") or "").strip(),
                )
            )

    _add("liquidity", liquidity_top)
    _add("gainers", gainers_top)
    return out


def _section_label(section: str) -> str:
    if section == "liquidity":
        return "24h流动性"
    if section == "gainers":
        return "涨幅榜"
    return section


def format_scan_telegram_caption(
    target: ScanTarget,
    *,
    period: str,
    analysis_raw: str,
    analysis_error: str = "",
) -> str:
    sec = _section_label(target.section)
    lines = [
        f"📊 {target.symbol} · {sec} #{target.rank}",
        f"周期: {period}",
    ]
    if target.change:
        lines.append(f"24h涨跌: {target.change}")
    if target.price:
        lines.append(f"现价: {target.price}")
    lines.append("")
    if analysis_error:
        lines.append(f"⚠️ AI 分析失败: {analysis_error}")
    elif analysis_raw:
        parsed = extract_json_from_gemini_text(analysis_raw)
        if isinstance(parsed, dict):
            trend = parsed.get("trend") or {}
            if isinstance(trend, dict):
                summary = (trend.get("summary") or "").strip()
                if summary:
                    lines.append(f"趋势: {summary}")
            rec = ""
            if isinstance(trend, dict):
                dec = trend.get("decision") or {}
                if isinstance(dec, dict):
                    rec = (dec.get("recommendation") or "").strip()
            if rec:
                lines.append(f"建议: {rec}")
            reasoning = (parsed.get("reasoning") or "").strip()
            if reasoning:
                lines.append(reasoning)
            if len(lines) <= 4:
                lines.append(json.dumps(parsed, ensure_ascii=False, indent=2)[:800])
        else:
            text = (analysis_raw or "").strip()
            if len(text) > 900:
                text = text[:899] + "…"
            lines.append(text)
    else:
        lines.append("（无分析结果）")
    return "\n".join(lines)


def _screenshot_path(symbol: str, period: str) -> str:
    sym = _tv_binance_symbol(symbol)
    interval = period_to_tradingview_interval(period)
    return os.path.join(get_screenshot_dir(), f"{sym}_{interval}.png")


def run_chart_scan(
    targets: Sequence[ScanTarget],
    *,
    period: str | None = None,
    chat_id: str,
    driver=None,
) -> tuple[int, int]:
    """
    依次：CDP 截图 → POST /ollama/chat (promat=tv_k_line_hot) → Telegram。
    返回 (成功数, 失败数)。
    """
    if not targets:
        print("[scan] 无待扫描币种", file=sys.stderr)
        return 0, 0

    tf = (period or BINANCE_RANKS_CHART_PERIOD or "15m").strip()
    ok_n = 0
    fail_n = 0
    own_driver = driver is None
    if own_driver:
        from browser_automation import init_browser

        print("[scan] 连接 Chrome（9222）用于逐币截图…", file=sys.stderr)
        driver = init_browser(use_remote_debugging=True)

    try:
        for i, target in enumerate(targets, 1):
            print(
                f"\n[scan] ({i}/{len(targets)}) {target.symbol} "
                f"({_section_label(target.section)} #{target.rank})",
                file=sys.stderr,
            )
            out_path = _screenshot_path(target.symbol, tf)
            try:
                capture_tradingview_chart(
                    ticker=target.symbol,
                    timeframe=tf,
                    out_path=out_path,
                    force_cdp=True,
                    driver=driver,
                    close_driver=False,
                )
                print(f"[scan] 截图完成: {out_path}", file=sys.stderr)
            except Exception as e:
                print(f"[scan] 截图失败: {e}", file=sys.stderr)
                fail_n += 1
                continue

            analysis = analyze_chart_promat(out_path, target.symbol)
            if analysis.get("status") != "success":
                err = str(analysis.get("error") or "unknown")
                caption = format_scan_telegram_caption(
                    target, period=tf, analysis_raw="", analysis_error=err
                )
                if send_telegram_message_with_photo(
                    caption,
                    out_path if os.path.isfile(out_path) else None,
                    use_markdown=False,
                    chat_id=chat_id,
                ):
                    ok_n += 1
                else:
                    fail_n += 1
                continue

            raw = str(analysis.get("analysis") or "")
            caption = format_scan_telegram_caption(
                target, period=tf, analysis_raw=raw
            )
            if send_telegram_message_with_photo(
                caption,
                out_path,
                use_markdown=False,
                chat_id=chat_id,
            ):
                print(f"[scan] Telegram 已发送: {target.symbol}", file=sys.stderr)
                ok_n += 1
            else:
                print(f"[scan] Telegram 失败: {target.symbol}", file=sys.stderr)
                fail_n += 1
    finally:
        if own_driver and driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    return ok_n, fail_n
