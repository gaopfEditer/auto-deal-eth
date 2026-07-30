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
from news_mornitor.pipeline.scoring import apply_score
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
        "7d": timedelta(days=7),
        "all": None,
    }
    delta = mapping.get(time_range.lower(), timedelta(hours=24))
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
    time_range: str = Query("24h", description="1h|6h|24h|7d|all"),
    include_spam: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    key = _cache_key(
        platform=platform or "",
        ticker=ticker or "",
        time_range=time_range,
        include_spam=include_spam,
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
        apply_score(p)
        items.append(p)

    items.sort(key=lambda x: x.score, reverse=True)
    page = items[offset : offset + limit]
    payload = {
        "ok": True,
        "total": len(items),
        "limit": limit,
        "offset": offset,
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
    ahead_hours: int = Query(None, ge=1, le=72, description="默认未来 24h"),
    refresh: bool = Query(False, description="强制重新拉取"),
) -> dict[str, Any]:
    """金十风格宏观大事件时间轴：≥N星、未来 window 内，带利好/利空。"""
    from news_mornitor.config import MACRO_AHEAD_HOURS, MACRO_MIN_STAR
    from news_mornitor.fetchers.macro_calendar import fetch_jinshi_calendar, filter_upcoming

    star = min_star if min_star is not None else MACRO_MIN_STAR
    hours = ahead_hours if ahead_hours is not None else MACRO_AHEAD_HOURS
    key = _cache_key(route="macro", star=star, hours=hours)

    if not refresh:
        cached = store.cache_get(key)
        if cached is not None:
            return cached

    events = store.load_macro_events()
    if refresh or not events:
        try:
            events = await fetch_jinshi_calendar(min_star=star, ahead_hours=hours)
            store.save_macro_events(events)
        except Exception as e:
            logger.exception("宏观日历刷新失败")
            return {"ok": False, "error": str(e), "items": []}

    events = filter_upcoming(events, min_star=star, ahead_hours=hours)
    payload = {
        "ok": True,
        "min_star": star,
        "ahead_hours": hours,
        "items": [e.to_public_dict() for e in events],
    }
    store.cache_set(key, payload)
    return payload


@app.get("/api/v1/boards")
def exchange_boards(
    limit: int = Query(12, ge=1, le=50),
    time_range: str = Query("24h"),
) -> dict[str, Any]:
    """右侧主体：按交易所拆分的热帖榜单。"""
    key = _cache_key(route="boards", limit=limit, time_range=time_range)
    cached = store.cache_get(key)
    if cached is not None:
        return cached

    cutoff = _parse_time_range(time_range)
    boards: dict[str, list[dict[str, Any]]] = {
        "BINANCE": [],
        "BITGET": [],
        "OKX": [],
        "TWITTER": [],
    }
    for p in store.load_posts().values():
        if p.is_spam:
            continue
        if cutoff is not None:
            try:
                ts = datetime.fromisoformat(p.published_at.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                continue
        apply_score(p)
        plat = p.platform.value if hasattr(p.platform, "value") else str(p.platform)
        if plat not in boards:
            boards[plat] = []
        boards[plat].append(p.to_public_dict())

    for plat, items in boards.items():
        items.sort(key=lambda x: x.get("score") or 0, reverse=True)
        boards[plat] = items[:limit]

    payload = {
        "ok": True,
        "boards": [
            {
                "platform": plat,
                "label": {
                    "BINANCE": "币安广场",
                    "BITGET": "Bitget Insights",
                    "OKX": "OKX 社区",
                    "TWITTER": "X",
                }.get(plat, plat),
                "items": items,
            }
            for plat, items in boards.items()
            if items or plat in ("BINANCE", "BITGET", "OKX")
        ],
    }
    store.cache_set(key, payload)
    return payload


@app.post("/api/v1/ingest")
async def trigger_ingest(limit: int = Query(40, ge=1, le=100)) -> dict[str, Any]:
    """手动触发一轮抓取（调试用）。"""
    from news_mornitor.pipeline.ingest import IngestPipeline

    try:
        result = await IngestPipeline(store=store).run_once(limit_per_source=limit)
        return {"ok": True, **result}
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
