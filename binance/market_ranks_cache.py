"""币安流动性/涨幅榜 JSON 缓存（默认 4 小时有效）。"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple

from config import BINANCE_MARKET_RANKS_CACHE_HOURS


def load_cache(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def cache_has_rankings(data: Dict[str, Any]) -> bool:
    """缓存里是否至少有一段榜单有条目。"""
    for key in ("liquidity", "gainers", "hot_rank"):
        sec = data.get(key)
        if not isinstance(sec, dict):
            continue
        items = sec.get("items")
        if isinstance(items, list) and len(items) > 0:
            return True
    return False


def cache_age_hours(data: Dict[str, Any], path: str) -> float:
    unix = data.get("cached_at_unix")
    if isinstance(unix, (int, float)) and unix > 0:
        return max(0.0, (time.time() - float(unix)) / 3600.0)
    try:
        return max(0.0, (time.time() - os.path.getmtime(path)) / 3600.0)
    except OSError:
        return float("inf")


def is_cache_fresh(
    data: Dict[str, Any],
    path: str,
    *,
    max_hours: float | None = None,
) -> bool:
    ttl = BINANCE_MARKET_RANKS_CACHE_HOURS if max_hours is None else max_hours
    if ttl <= 0:
        return False
    if not cache_has_rankings(data):
        return False
    return cache_age_hours(data, path) < ttl


def stamp_cache(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data)
    out["cached_at_unix"] = int(time.time())
    return out


def save_cache(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stamp_cache(data), f, ensure_ascii=False, indent=2)


def resolve_market_ranks(
    *,
    cache_path: str,
    force_refresh: bool,
    fetch_fn: Callable[[], Dict[str, Any]],
    max_hours: float | None = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    返回 (payload, from_cache)。
    缓存有效且有条目时跳过抓取；抓取失败时回退到过期缓存（若有数据）。
    """
    cached = load_cache(cache_path)
    ttl = BINANCE_MARKET_RANKS_CACHE_HOURS if max_hours is None else max_hours

    if not force_refresh and cached and is_cache_fresh(cached, cache_path, max_hours=max_hours):
        age = cache_age_hours(cached, cache_path)
        print(
            f"[cache] 榜单缓存仍有效（{age:.1f}h / {ttl:.0f}h），跳过抓取",
            flush=True,
        )
        return cached, True

    try:
        result = fetch_fn()
        if cache_has_rankings(result):
            save_cache(cache_path, result)
            return result, False
        print(
            "[cache][WARN] 本次抓取无榜单条目，不覆盖缓存",
            file=sys.stderr,
        )
        if cached and cache_has_rankings(cached):
            print(
                "[cache] 使用本地已有缓存（本次结果为空）",
                flush=True,
            )
            return cached, True
        save_cache(cache_path, result)
        return result, False
    except Exception as e:
        print(f"[cache][WARN] 抓取失败: {e}", file=sys.stderr)
        if cached and cache_has_rankings(cached):
            age = cache_age_hours(cached, cache_path)
            print(
                f"[cache] 使用过期缓存（{age:.1f}h 前，API/网络异常时兜底）",
                flush=True,
            )
            return cached, True
        raise RuntimeError(
            "无法抓取榜单且无可用本地缓存。"
            "请检查网络/代理（可设 BINANCE_API_TRUST_ENV=1），"
            "或去掉 --api-only 用 CDP 抓榜，或稍后重试。"
        ) from e
