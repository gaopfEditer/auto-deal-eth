"""FastAPI 只读 API + 静态前端。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from news_mornitor.models import Platform
from news_mornitor.pipeline.content_quality import is_useful_personal_post
from news_mornitor.pipeline.scoring import apply_score, is_influential
from news_mornitor.store import FileStore

logger = logging.getLogger("CryptoPulse.API")

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
STATIC_FALLBACK = Path(__file__).resolve().parent.parent / "frontend" / "public"

store = FileStore()
app = FastAPI(title="CryptoPulse", version="0.1.0", description="交易所广场热门动态聚合")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_time_range(time_range: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    mapping = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "3d": timedelta(days=3),
        "7d": timedelta(days=7),
        "all": None,
    }
    delta = mapping.get(time_range.lower(), timedelta(days=3))
    if delta is None:
        return None
    return now - delta


def _cache_key(**parts: Any) -> str:
    raw = "|".join(f"{k}={v}" for k, v in sorted(parts.items()))
    return "api_" + hashlib.md5(raw.encode()).hexdigest()


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    posts = store.load_posts()
    return {"ok": True, "posts": len(posts), "service": "CryptoPulse"}


@app.get("/api/v1/posts")
def list_posts(
    platform: str | None = Query(None, description="BINANCE|BITGET|OKX|TWITTER"),
    ticker: str | None = Query(None, description="如 BTC"),
    time_range: str = Query("3d", description="1h|6h|24h|3d|7d|all"),
    include_spam: bool = Query(False),
    influential_only: bool | None = Query(
        None, description="默认读配置：赞≥门槛 或 评≥门槛"
    ),
    min_likes: int | None = Query(None, ge=0, description="覆盖默认点赞门槛"),
    min_comments: int | None = Query(None, ge=0, description="覆盖默认评论门槛"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    from news_mornitor.config import (
        SQUARE_INFLUENTIAL_ONLY,
        SQUARE_MIN_COMMENTS,
        SQUARE_MIN_LIKES,
    )

    only = SQUARE_INFLUENTIAL_ONLY if influential_only is None else influential_only
    likes_need = SQUARE_MIN_LIKES if min_likes is None else min_likes
    comments_need = SQUARE_MIN_COMMENTS if min_comments is None else min_comments

    key = _cache_key(
        platform=platform or "",
        ticker=ticker or "",
        time_range=time_range,
        include_spam=include_spam,
        only=only,
        likes=likes_need,
        comments=comments_need,
        limit=limit,
        offset=offset,
    )
    cached = store.cache_get(key)
    if cached is not None:
        return cached

    cutoff = _parse_time_range(time_range)
    plat = None
    if platform:
        try:
            plat = Platform(platform.upper())
        except ValueError:
            return {"ok": False, "error": f"unknown platform: {platform}", "items": []}

    ticker_u = (ticker or "").strip().upper().lstrip("$") or None
    items = []
    for p in store.load_posts().values():
        if p.is_spam and not include_spam:
            continue
        if plat and p.platform != plat:
            continue
        if ticker_u and ticker_u not in [t.upper() for t in p.mentioned_tickers]:
            continue
        if cutoff is not None:
            try:
                ts = datetime.fromisoformat(p.published_at.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                continue
        if only and not is_influential(
            p, min_likes=min_likes, min_comments=min_comments
        ):
            continue
        if not is_useful_personal_post(p):
            continue
        apply_score(p)
        items.append(p)

    items.sort(key=lambda x: x.score, reverse=True)
    page = items[offset : offset + limit]
    payload = {
        "ok": True,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "influential_only": only,
        "match": "or",
        "min_likes": likes_need,
        "min_comments": comments_need,
        "items": [p.to_public_dict() for p in page],
    }
    store.cache_set(key, payload)
    return payload


@app.get("/api/v1/tickers/trending")
def trending_tickers(
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    key = _cache_key(route="tickers", limit=limit)
    cached = store.cache_get(key)
    if cached is not None:
        return cached

    tickers = store.rebuild_tickers_24h()
    payload = {
        "ok": True,
        "items": [t.to_public_dict() for t in tickers[:limit]],
    }
    store.cache_set(key, payload)
    return payload


@app.get("/api/v1/macro/timeline")
async def macro_timeline(
    min_star: int = Query(None, ge=1, le=5, description="默认读配置 ≥3"),
    ahead_hours: int = Query(None, ge=1, le=72, description="默认未来 72h（最多 3 天）"),
    behind_hours: int = Query(None, ge=0, le=72, description="默认过去 72h（最多 3 天）"),
    refresh: bool = Query(False, description="强制重新拉取"),
) -> dict[str, Any]:
    """宏观时间轴：≥N星、北京时间过去/未来各最多 3 天，带利好/利空。"""
    from news_mornitor.config import (
        MACRO_AHEAD_HOURS,
        MACRO_BEHIND_HOURS,
        MACRO_MIN_STAR,
        MACRO_TZ,
    )
    from news_mornitor.fetchers.macro_calendar import fetch_jinshi_calendar, filter_upcoming

    star = min_star if min_star is not None else MACRO_MIN_STAR
    hours_ahead = ahead_hours if ahead_hours is not None else MACRO_AHEAD_HOURS
    hours_behind = behind_hours if behind_hours is not None else MACRO_BEHIND_HOURS
    key = _cache_key(
        route="macro", star=star, ahead=hours_ahead, behind=hours_behind
    )

    if not refresh:
        cached = store.cache_get(key)
        if cached is not None:
            return cached

    events = store.load_macro_events()
    if refresh or not events:
        try:
            events = await fetch_jinshi_calendar(
                min_star=star,
                ahead_hours=hours_ahead,
                behind_hours=hours_behind,
            )
            store.save_macro_events(events)
        except Exception as e:
            logger.exception("宏观日历刷新失败")
            return {"ok": False, "error": str(e), "items": []}

    events = filter_upcoming(
        events,
        min_star=star,
        ahead_hours=hours_ahead,
        behind_hours=hours_behind,
    )
    payload = {
        "ok": True,
        "min_star": star,
        "ahead_hours": hours_ahead,
        "behind_hours": hours_behind,
        "timezone": MACRO_TZ,
        "items": [e.to_public_dict() for e in events],
    }
    store.cache_set(key, payload)
    return payload


@app.get("/api/v1/boards")
def exchange_boards(
    limit: int = Query(20, ge=1, le=50),
    time_range: str = Query("3d", description="1h|6h|24h|3d|7d|all"),
    influential_only: bool | None = Query(
        None, description="默认只展示有影响力帖（赞/评过门槛）"
    ),
    min_likes: int | None = Query(None, ge=0),
    min_comments: int | None = Query(None, ge=0),
) -> dict[str, Any]:
    """右侧主体：各平台高热帖（默认 赞≥200 或 评≥30，再按 score 排序）。"""
    from news_mornitor.config import (
        SQUARE_INFLUENTIAL_ONLY,
        SQUARE_MIN_COMMENTS,
        SQUARE_MIN_LIKES,
        USE_MOCK_FETCHER,
    )

    only = SQUARE_INFLUENTIAL_ONLY if influential_only is None else influential_only
    likes_need = SQUARE_MIN_LIKES if min_likes is None else min_likes
    comments_need = SQUARE_MIN_COMMENTS if min_comments is None else min_comments

    key = _cache_key(
        route="boards",
        limit=limit,
        time_range=time_range,
        only=only,
        likes=likes_need,
        comments=comments_need,
    )
    cached = store.cache_get(key)
    if cached is not None:
        return cached

    cutoff = _parse_time_range(time_range)
    boards: dict[str, list[dict[str, Any]]] = {
        "BINANCE": [],
        "BITGET": [],
        "OKX": [],
        "BYBIT": [],
        "REDDIT": [],
        "TRADINGVIEW": [],
        "CRYPTOPANIC": [],
        "FARCASTER": [],
        "TWITTER": [],
    }
    for p in store.load_posts().values():
        if p.is_spam:
            continue
        if cutoff is not None:
            # Farcaster Hub 帖发布时间可能偏旧：用 fetched_at 作为窗口兜底，避免整栏空白
            plat0 = p.platform.value if hasattr(p.platform, "value") else str(p.platform)
            ts_ok = False
            for field in ("published_at", "fetched_at") if plat0 == "FARCASTER" else ("published_at",):
                raw = getattr(p, field, None) or ""
                try:
                    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    if ts >= cutoff:
                        ts_ok = True
                        break
                except ValueError:
                    continue
            if not ts_ok:
                continue
        if only and not is_influential(
            p, min_likes=min_likes, min_comments=min_comments
        ):
            continue
        if not is_useful_personal_post(p):
            continue
        apply_score(p)
        plat = p.platform.value if hasattr(p.platform, "value") else str(p.platform)
        if plat not in boards:
            boards[plat] = []
        boards[plat].append(p.to_public_dict())

    for plat, items in boards.items():
        items.sort(key=lambda x: x.get("score") or 0, reverse=True)
        boards[plat] = items[:limit]

    labels = {
        "BINANCE": "币安广场",
        "BITGET": "Bitget Insights",
        "OKX": "OKX 社区",
        "BYBIT": "Bybit Feed",
        "REDDIT": "Reddit r/CryptoCurrency",
        "TRADINGVIEW": "TradingView Ideas",
        "CRYPTOPANIC": "CryptoPanic",
        "FARCASTER": "Warpcast / Farcaster",
        "TWITTER": "X",
    }
    # 有内容的板优先，其余按固定顺序垫底
    always = ("BINANCE", "BITGET", "OKX", "BYBIT", "REDDIT", "TRADINGVIEW", "FARCASTER")
    ordered_plats = [p for p in always if boards.get(p)]
    ordered_plats += [p for p in always if p not in ordered_plats]
    for p in boards:
        if p not in ordered_plats and boards[p]:
            ordered_plats.append(p)

    payload = {
        "ok": True,
        "influential_only": only,
        "match": "or",
        "use_mock": USE_MOCK_FETCHER,
        "min_likes": likes_need,
        "min_comments": comments_need,
        "time_range": time_range,
        "boards": [
            {
                "platform": plat,
                "label": labels.get(plat, plat),
                "items": boards.get(plat) or [],
            }
            for plat in ordered_plats
        ],
    }
    store.cache_set(key, payload)
    return payload


@app.get("/api/v1/fetch/status")
def fetch_status() -> dict[str, Any]:
    from news_mornitor.pipeline.fetch_control import get_fetch_status

    return get_fetch_status()


@app.post("/api/v1/fetch/stop")
def fetch_stop() -> dict[str, Any]:
    """停止定时抓取（不影响已写入的历史数据）。"""
    from news_mornitor.pipeline.fetch_control import set_fetch_enabled

    return set_fetch_enabled(False)


@app.post("/api/v1/fetch/start")
def fetch_start() -> dict[str, Any]:
    """恢复定时抓取。"""
    from news_mornitor.pipeline.fetch_control import set_fetch_enabled

    return set_fetch_enabled(True)


@app.post("/api/v1/fetch/now")
async def fetch_now(limit: int = Query(40, ge=1, le=100)) -> dict[str, Any]:
    """立即抓取一轮（忽略定时开关与间隔）。"""
    from news_mornitor.pipeline.fetch_control import fetch_now as do_fetch_now

    try:
        return await do_fetch_now(limit_per_source=limit)
    except Exception as e:
        logger.exception("fetch now failed")
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/ingest")
async def trigger_ingest(
    limit: int = Query(40, ge=1, le=100),
    force: bool = Query(False, description="True=忽略间隔限流"),
) -> dict[str, Any]:
    """兼容旧接口；推荐用 /api/v1/fetch/now|start|stop。"""
    from news_mornitor.pipeline.ingest_gate import run_ingest_gated

    try:
        return await run_ingest_gated(force=force, limit_per_source=limit)
    except Exception as e:
        logger.exception("ingest failed")
        return {"ok": False, "error": str(e)}


def _index_file() -> Path | None:
    for base in (STATIC_DIR, STATIC_FALLBACK):
        idx = base / "index.html"
        if idx.exists():
            return idx
    return None


@app.get("/")
def index():
    from fastapi.responses import HTMLResponse

    idx = _index_file()
    if not idx:
        return HTMLResponse(
            "<h1>CryptoPulse</h1><p>frontend missing — open /api/v1/posts</p>",
            status_code=200,
        )
    return FileResponse(idx)


# 静态资源：优先 dist，否则 public
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
if STATIC_FALLBACK.exists():
    app.mount("/static", StaticFiles(directory=STATIC_FALLBACK), name="static")
