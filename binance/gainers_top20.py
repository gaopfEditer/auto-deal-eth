#!/usr/bin/env python3
"""
CDP 抓取币安现货：24h 流动性 TOP30 + 涨幅 TOP20（DOM 失败回退 24h API）。

流动性 = 24h USDT 成交额（quoteVolume），与行情页「热榜/成交额」一致。

默认推送到 Telegram 榜单群（config.TELEGRAM_MARKET_RANKS_CHAT_ID，默认 -5218901932），
不发币安广场。榜单默认 4 小时更新一次（BINANCE_MARKET_RANKS_CACHE_HOURS），
缓存有效期内不重复抓取、不重复推榜单摘要。

默认对缓存榜单内币种（流动性+涨幅，去重）依次：TradingView 截图 → POST /ollama/chat (tv_k_line_hot) → Telegram；
默认排除 eth/btc/usdt/usdc/usd1/sui/sol/bnb（可用 --exclude 覆盖）。

前置：Chrome 远程调试 9222（抓榜 DOM 与逐币截图均需）
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222

截图目录默认 /Volumes/RamDisk/app_screenshots（config.SCREENSHOT_DIR / .env 可改）

用法:
  python -m binance.gainers_top20
  python -m binance.gainers_top20 --api-only --print-text
  python -m binance.gainers_top20 --skip-scan-charts
  python -m binance.gainers_top20 --refresh
  python -m binance.gainers_top20 --chart-period 15m
  python -m binance.gainers_top20 --chart-period 1h
  python -m binance.gainers_top20 --exclude eth,btc,sol
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from config import (
    BINANCE_MARKET_RANKS_CACHE_HOURS,
    BINANCE_RANKS_CHART_PERIOD,
    BINANCE_RANKS_EXCLUDE_BASES,
    TELEGRAM_MARKET_RANKS_CHAT_ID,
)
from binance.gainers_chart_scan import (
    collect_scan_targets,
    parse_exclude_bases,
    run_chart_scan,
)
from binance.market_lists_selenium import (
    DEFAULT_URL,
    format_liquidity_gainers_square_brief,
    print_liquidity_gainers_stdout,
    scrape_liquidity_gainers_snapshot,
)
from binance.market_ranks_cache import resolve_market_ranks
from notifier import send_telegram_message


def _send_ranks_telegram(
    result: dict,
    *,
    liquidity_top: int,
    gainers_top: int,
    chat_id: str,
) -> bool:
    text = format_liquidity_gainers_square_brief(
        result,
        liquidity_top=max(1, liquidity_top),
        gainers_top=max(1, gainers_top),
    )
    if not text:
        print("[Telegram] 榜单正文为空，跳过推送", file=sys.stderr)
        return False
    print(f"[Telegram] 推送榜单到 chat_id={chat_id} …", file=sys.stderr)
    ok = send_telegram_message(text, chat_id=chat_id)
    if ok:
        print("[Telegram] 榜单推送成功", file=sys.stderr)
    else:
        print("[Telegram] 榜单推送失败", file=sys.stderr)
    return ok


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="币安 24h 流动性 TOP + 涨幅 TOP → 逐币截图/AI/Telegram",
    )
    p.add_argument(
        "--liquidity-top",
        type=int,
        default=30,
        help="24h 流动性（USDT 成交额）条数，默认 30",
    )
    p.add_argument(
        "--gainers-top",
        type=int,
        default=20,
        help="涨幅榜条数，默认 20",
    )
    p.add_argument(
        "--top",
        type=int,
        default=None,
        help="（兼容）等同 --gainers-top",
    )
    p.add_argument("--url", default=DEFAULT_URL, help="行情总览页")
    p.add_argument(
        "--out",
        default="binance_market_ranks.json",
        help="输出/缓存 JSON（默认 binance_market_ranks.json）",
    )
    p.add_argument(
        "--api-only",
        action="store_true",
        help="抓榜时不连 CDP（仅 API）；逐币截图仍用 CDP",
    )
    p.add_argument(
        "--print-text",
        action="store_true",
        help="额外打印榜单正文预览",
    )
    p.add_argument(
        "--print-json",
        action="store_true",
        help="终端输出完整 JSON",
    )
    p.add_argument(
        "--skip-telegram",
        action="store_true",
        help="不推 Telegram（含榜单摘要与逐币图文）",
    )
    p.add_argument(
        "--skip-scan-charts",
        action="store_true",
        help="不逐币截图/AI/Telegram（仅抓榜与可选榜单摘要）",
    )
    p.add_argument(
        "--chart-period",
        default=BINANCE_RANKS_CHART_PERIOD,
        help=f"逐币 K 线截图周期，默认 {BINANCE_RANKS_CHART_PERIOD}",
    )
    p.add_argument(
        "--exclude",
        default=BINANCE_RANKS_EXCLUDE_BASES,
        help="排除的 base 资产，逗号分隔（默认 eth,btc,usdt,usdc,usd1,sui,sol,bnb）",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help=f"忽略缓存，强制重新抓取（默认 {BINANCE_MARKET_RANKS_CACHE_HOURS:.0f}h 内用缓存）",
    )
    p.add_argument(
        "--telegram-chat-id",
        default=TELEGRAM_MARKET_RANKS_CHAT_ID,
        help=f"Telegram 目标 chat_id（默认 {TELEGRAM_MARKET_RANKS_CHAT_ID}）",
    )
    args = p.parse_args(argv)

    gainers_top = args.gainers_top if args.top is None else args.top
    out_path = os.path.abspath(args.out)
    chat_id = (args.telegram_chat_id or TELEGRAM_MARKET_RANKS_CHAT_ID).strip()
    exclude_bases = parse_exclude_bases(args.exclude)

    def _fetch() -> dict:
        return scrape_liquidity_gainers_snapshot(
            liquidity_top=max(0, args.liquidity_top),
            gainers_top=max(1, gainers_top),
            url=args.url.strip(),
            use_cdp=not args.api_only,
        )

    result, from_cache = resolve_market_ranks(
        cache_path=out_path,
        force_refresh=args.refresh,
        fetch_fn=_fetch,
    )

    print_liquidity_gainers_stdout(
        result,
        liquidity_top=max(1, args.liquidity_top),
        gainers_top=max(1, gainers_top),
    )
    if args.print_text:
        print("\n" + "=" * 56)
        print("【榜单正文预览】")
        print("=" * 56)
        print(
            format_liquidity_gainers_square_brief(
                result,
                liquidity_top=max(1, args.liquidity_top),
                gainers_top=max(1, gainers_top),
            )
        )
    if args.print_json:
        print("\n" + json.dumps(result, ensure_ascii=False, indent=2))

    if not args.skip_telegram:
        if from_cache:
            print(
                "[Telegram] 榜单摘要：缓存有效期内跳过重复推送（--refresh 可强制）",
                file=sys.stderr,
            )
        else:
            if not _send_ranks_telegram(
                result,
                liquidity_top=max(1, args.liquidity_top),
                gainers_top=max(1, gainers_top),
                chat_id=chat_id,
            ):
                return 1

    if not args.skip_scan_charts:
        targets = collect_scan_targets(
            result,
            liquidity_top=max(0, args.liquidity_top),
            gainers_top=max(1, gainers_top),
            exclude_bases=exclude_bases,
        )
        print(
            f"[scan] 待扫描 {len(targets)} 个币种（已排除: {', '.join(sorted(exclude_bases))}）",
            file=sys.stderr,
        )
        for t in targets:
            print(
                f"  · {t.symbol} ({t.section} #{t.rank})",
                file=sys.stderr,
            )
        if args.skip_telegram:
            print(
                "[scan] 已 --skip-telegram，跳过逐币截图/AI",
                file=sys.stderr,
            )
            ok_n, fail_n = 0, 0
        else:
            ok_n, fail_n = run_chart_scan(
                targets,
                period=args.chart_period.strip(),
                chat_id=chat_id,
            )
        print(
            f"[scan] 完成: 成功 {ok_n}，失败 {fail_n}",
            file=sys.stderr,
        )
        if fail_n and ok_n == 0 and targets:
            return 1

    print(f"\n[OK] 数据文件: {out_path}" + ("（缓存命中）" if from_cache else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
