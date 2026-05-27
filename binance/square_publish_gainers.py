#!/usr/bin/env python3
"""
抓取 24h 流动性 TOP30 + 涨幅 TOP20 → 生成短文 → 推送到 Telegram 榜单群。

默认不发币安广场；加 --square 才走 square_publish/CDP。

用法:
  python -m binance.square_publish_gainers
  python -m binance.square_publish_gainers --liquidity-top 30 --gainers-top 20
  python -m binance.square_publish_gainers --square   # 可选：仍发广场
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from config import BINANCE_MARKET_RANKS_CACHE_HOURS, TELEGRAM_MARKET_RANKS_CHAT_ID
from binance.market_lists_selenium import (
    DEFAULT_URL,
    format_liquidity_gainers_square_brief,
    scrape_liquidity_gainers_snapshot,
)
from binance.market_ranks_cache import resolve_market_ranks
from binance.square_publish import DEFAULT_SQUARE_URL, publish_square_post
from notifier import send_telegram_message


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="流动性 TOP + 涨幅 TOP → Telegram 榜单群（默认）；--square 才发广场",
    )
    p.add_argument("--liquidity-top", type=int, default=30, help="流动性条数，默认 30")
    p.add_argument("--gainers-top", type=int, default=20, help="涨幅条数，默认 20")
    p.add_argument("--top", type=int, default=None, help="（兼容）等同 --gainers-top")
    p.add_argument("--markets-url", default=DEFAULT_URL, help="抓榜用的行情页")
    p.add_argument(
        "--square-url",
        default=DEFAULT_SQUARE_URL,
        help="--square 时打开的 Square 首页",
    )
    p.add_argument(
        "--api-only",
        action="store_true",
        help="抓榜时不连 CDP（仅 API）；--square 时发帖仍用 CDP",
    )
    p.add_argument(
        "--text-file",
        help="指定正文文件则跳过抓榜，直接推送该内容",
    )
    p.add_argument(
        "--skip-telegram",
        action="store_true",
        help="不推 Telegram",
    )
    p.add_argument(
        "--telegram-chat-id",
        default=TELEGRAM_MARKET_RANKS_CHAT_ID,
        help=f"Telegram 目标 chat_id（默认 {TELEGRAM_MARKET_RANKS_CHAT_ID}）",
    )
    p.add_argument(
        "--square",
        action="store_true",
        help="额外/改为发布到币安广场（默认仅 Telegram）",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help=f"忽略缓存，强制重新抓取（默认 {BINANCE_MARKET_RANKS_CACHE_HOURS:.0f}h 内用缓存）",
    )
    p.add_argument(
        "--cache-file",
        default="binance_market_ranks.json",
        help="榜单缓存 JSON（与 gainers_top20 共用）",
    )
    p.add_argument("--no-submit", action="store_true", help="同 --dry-run")
    p.add_argument("--json", action="store_true", help="JSON 输出结果")
    args = p.parse_args(argv)

    gainers_top = args.gainers_top if args.top is None else args.top
    cache_path = os.path.abspath(args.cache_file)
    from_cache = False

    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            text = f.read().strip()
        ranks_payload = None
    else:

        def _fetch() -> dict:
            return scrape_liquidity_gainers_snapshot(
                liquidity_top=max(0, args.liquidity_top),
                gainers_top=max(1, gainers_top),
                url=args.markets_url.strip(),
                use_cdp=not args.api_only,
            )

        ranks_payload, from_cache = resolve_market_ranks(
            cache_path=cache_path,
            force_refresh=args.refresh,
            fetch_fn=_fetch,
        )
        text = format_liquidity_gainers_square_brief(
            ranks_payload,
            liquidity_top=max(1, args.liquidity_top),
            gainers_top=max(1, gainers_top),
        )

    if not text:
        print("[ERROR] 正文为空", file=sys.stderr)
        return 1

    print("=" * 56)
    print("【榜单正文】")
    print("=" * 56)
    print(text)
    print("=" * 56)

    out: dict = {"text_length": len(text)}

    if not args.skip_telegram:
        if from_cache:
            print(
                "[Telegram] 缓存有效期内，跳过重复推送（加 --refresh 可强制更新并推送）",
                file=sys.stderr,
            )
        else:
            chat_id = (args.telegram_chat_id or TELEGRAM_MARKET_RANKS_CHAT_ID).strip()
            print(f"[Telegram] 推送到 chat_id={chat_id} …", file=sys.stderr)
            tg_ok = send_telegram_message(text, chat_id=chat_id)
            out["telegram_ok"] = tg_ok
            out["telegram_chat_id"] = chat_id
            if not tg_ok:
                print("[ERROR] Telegram 推送失败", file=sys.stderr)
                return 1
            print("[OK] Telegram 推送成功")

    if args.square:
        submit = not (args.dry_run or args.no_submit)
        result = publish_square_post(
            text,
            image_paths=[],
            square_url=args.square_url.strip(),
            submit=submit,
        )
        out["square"] = result.to_dict()
        if ranks_payload is not None:
            out["ranks_scraped_at"] = ranks_payload.get("scraped_at")
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        elif not result.ok:
            print(f"[ERROR] 广场发帖失败: {result.error or 'unknown'}", file=sys.stderr)
            return 1
        else:
            print("[OK] 广场发帖流程完成")
            if result.post_url:
                print(f"     帖子: {result.post_url}")
            if not result.submitted:
                print("     未提交（dry-run / no-submit）")
    elif args.json:
        if ranks_payload is not None:
            out["ranks_scraped_at"] = ranks_payload.get("scraped_at")
        print(json.dumps(out, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
