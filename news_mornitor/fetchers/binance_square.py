"""币安广场抓取：官方 bapi 多端点试探 + 仓库本地广场 JSON（真帖真链）回退。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from news_mornitor.config import (
    BINANCE_SQUARE_HEADERS_JSON,
    BINANCE_SQUARE_TRENDING_URL,
    HTTP_TIMEOUT_SEC,
    REQUEST_DELAY_SEC,
    SQUARE_MIN_COMMENTS,
    SQUARE_MIN_LIKES,
    USE_MOCK_FETCHER,
    proxy_url,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem, utc_now_iso

logger = logging.getLogger("CryptoPulse.BinanceSquare")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTENT_ID_RE = re.compile(r"/square/post/(\d+)", re.I)

# 旧配置里的 path 已 404；按常见 bapi 路径轮询
_LIST_CANDIDATES: list[tuple[str, dict[str, Any]]] = [
    (
        "https://www.binance.com/bapi/composite/v1/friendly/pgc/content/home/squareList",
        {"page": 1, "rows": 40},
    ),
    (
        "https://www.binance.com/bapi/composite/v1/public/pgc/content/home/squareList",
        {"page": 1, "rows": 40},
    ),
    (
        "https://www.binance.com/bapi/composite/v1/friendly/pgc/content/square/list",
        {"page": 1, "pageSize": 40, "contentType": "ALL"},
    ),
    (
        BINANCE_SQUARE_TRENDING_URL,
        {"page": 1, "pageSize": 40, "contentType": "ALL"},
    ),
]

_DETAIL_URLS = [
    "https://www.binance.com/bapi/composite/v1/friendly/pgc/content/getContent",
    "https://www.binance.com/bapi/composite/v1/public/pgc/content/getContent",
    "https://www.binance.com/bapi/content/v1/public/pgc/content/getContent",
]


def _default_headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "clienttype": "web",
        "lang": "zh-CN",
        "Referer": "https://www.binance.com/zh-CN/square",
        "Origin": "https://www.binance.com",
    }
    if BINANCE_SQUARE_HEADERS_JSON.strip():
        try:
            extra = json.loads(BINANCE_SQUARE_HEADERS_JSON)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        except json.JSONDecodeError as e:
            logger.warning("CRYPTO_PULSE_BINANCE_HEADERS_JSON 解析失败: %s", e)
    return headers


def _mock_items(limit: int = 20) -> list[RawFetchItem]:
    return build_mock_items(
        Platform.BINANCE,
        samples_for(Platform.BINANCE, n=max(limit, 16), offset=0),
        limit=limit,
        url_builder=lambda _eid: mock_home_url(Platform.BINANCE),
    )


def _parse_list_payload(data: Any) -> list[RawFetchItem]:
    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("data", "list", "voList", "contents", "result"):
            node = data.get(key)
            if isinstance(node, list):
                items = node
                break
            if isinstance(node, dict):
                for k2 in ("list", "voList", "contents", "data"):
                    if isinstance(node.get(k2), list):
                        items = node[k2]
                        break
            if items:
                break

    out: list[RawFetchItem] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        body = raw.get("body") or raw.get("content") or raw.get("squareContent") or raw
        if not isinstance(body, dict):
            body = raw
        eid = str(
            body.get("id")
            or body.get("contentId")
            or body.get("squareId")
            or raw.get("id")
            or ""
        )
        if not eid:
            continue
        author_obj = body.get("author") or body.get("user") or raw.get("author") or {}
        if not isinstance(author_obj, dict):
            author_obj = {}
        text = (
            body.get("body")
            or body.get("content")
            or body.get("text")
            or body.get("title")
            or ""
        )
        title = str(body.get("title") or "")[:200]
        likes = int(body.get("likeCount") or body.get("like_count") or body.get("likedCount") or 0)
        comments = int(
            body.get("commentCount") or body.get("comment_count") or body.get("replyCount") or 0
        )
        shares = int(body.get("shareCount") or body.get("share_count") or body.get("forwardCount") or 0)
        view = int(body.get("viewCount") or body.get("view_count") or body.get("readCount") or 0)
        if likes <= 0 and view > 0:
            likes = max(likes, view // 50)
        pub = body.get("createTime") or body.get("publishedAt") or body.get("createDate") or ""
        if isinstance(pub, (int, float)) and pub > 1e11:
            pub = datetime.fromtimestamp(pub / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(pub, (int, float)) and pub > 1e9:
            pub = datetime.fromtimestamp(pub, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            pub = str(pub) if pub else utc_now_iso()

        images: list[str] = []
        for img_key in ("imageList", "images", "imageUrls"):
            arr = body.get(img_key)
            if isinstance(arr, list):
                for x in arr:
                    if isinstance(x, str):
                        images.append(x)
                    elif isinstance(x, dict) and x.get("url"):
                        images.append(str(x["url"]))

        out.append(
            RawFetchItem(
                external_id=eid,
                platform=Platform.BINANCE,
                author=str(
                    author_obj.get("nickname")
                    or author_obj.get("displayName")
                    or author_obj.get("name")
                    or "unknown"
                ),
                author_avatar=author_obj.get("avatar") or author_obj.get("avatarUrl"),
                title=title or str(text)[:80],
                content=str(text),
                like_count=likes,
                comment_count=comments,
                share_count=shares,
                published_at=pub,
                source_url=f"https://www.binance.com/zh-CN/square/post/{eid}",
                image_urls=images[:6],
            )
        )
    return out


def _bj_time_to_iso(s: str) -> str:
    s = (s or "").strip().replace("北京时间", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            # 标注为北京时间墙钟 → 按 UTC+8 理解再转 UTC
            from zoneinfo import ZoneInfo

            dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return utc_now_iso()


def _load_local_square_posts(*, limit: int) -> list[RawFetchItem]:
    """从仓库已有 CDP/Selenium 广场结果读真帖（含真实 /square/post/ 链接）。"""
    paths = [
        _REPO_ROOT / "binance_market_lists.json",
        Path(__file__).resolve().parents[1] / "data" / "binance_market_lists.json",
    ]
    state_paths = [
        _REPO_ROOT / "binance_posts_state.json",
        Path(__file__).resolve().parents[1] / "data" / "binance_posts_state.json",
    ]

    rows: list[dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        wl = data.get("watchlist") if isinstance(data, dict) else None
        posts = (wl or {}).get("latest_posts") if isinstance(wl, dict) else None
        if isinstance(posts, list):
            rows.extend(x for x in posts if isinstance(x, dict))
            logger.info("[%s] 本地广场列表 %s → %d 条", "binance_square", p.name, len(posts))
            break

    for sp in state_paths:
        if not sp.exists():
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        posts = data.get("posts") if isinstance(data, dict) else None
        if not isinstance(posts, dict):
            continue
        n = 0
        for _slug, by_href in posts.items():
            if not isinstance(by_href, dict):
                continue
            for href, entry in by_href.items():
                if not isinstance(entry, dict):
                    continue
                e = dict(entry)
                e.setdefault("href", href)
                rows.append(e)
                n += 1
        if n:
            logger.info("[%s] 本地 posts_state %s → +%d 条", "binance_square", sp.name, n)
        break

    out: list[RawFetchItem] = []
    seen: set[str] = set()
    for row in rows:
        href = str(row.get("href") or "").strip()
        m = _CONTENT_ID_RE.search(href)
        eid = m.group(1) if m else ""
        if not eid or eid in seen:
            continue
        seen.add(eid)
        title = str(row.get("title") or row.get("raw") or "")[:200]
        content = str(row.get("raw") or row.get("title") or "")
        if not title and not content:
            continue
        pub = str(row.get("published_iso") or "").strip()
        if not pub:
            pub = _bj_time_to_iso(str(row.get("published_at") or ""))
        # 本地关注流暂无赞评字段：先按门槛占位，detail API 成功后覆盖为真互动
        star = int(row.get("signal_star") or 0)
        likes = max(SQUARE_MIN_LIKES, star * 80)
        comments = max(0, star * 12)
        images = row.get("image_urls") if isinstance(row.get("image_urls"), list) else []
        out.append(
            RawFetchItem(
                external_id=eid,
                platform=Platform.BINANCE,
                author=str(row.get("author") or row.get("author_slug") or "binance"),
                title=title,
                content=content[:4000],
                like_count=likes,
                comment_count=comments,
                share_count=0,
                published_at=pub,
                source_url=href or f"https://www.binance.com/zh-CN/square/post/{eid}",
                image_urls=[str(x) for x in images if isinstance(x, str)][:6],
            )
        )
        if len(out) >= limit:
            break
    return out


def _engagement_from_detail(data: Any) -> tuple[int, int, int]:
    if not isinstance(data, dict):
        return 0, 0, 0
    node = data.get("data") if isinstance(data.get("data"), dict) else data
    body = node.get("body") or node.get("content") or node if isinstance(node, dict) else {}
    if not isinstance(body, dict):
        return 0, 0, 0
    likes = int(body.get("likeCount") or body.get("likedCount") or body.get("like_count") or 0)
    comments = int(body.get("commentCount") or body.get("replyCount") or body.get("comment_count") or 0)
    shares = int(body.get("shareCount") or body.get("forwardCount") or 0)
    return likes, comments, shares


class BinanceSquareFetcher(BaseFetcher):
    platform = Platform.BINANCE
    name = "binance_square"

    def __init__(
        self,
        *,
        url: str = BINANCE_SQUARE_TRENDING_URL,
        request_delay: float = REQUEST_DELAY_SEC,
        use_mock: bool | None = None,
    ) -> None:
        super().__init__(request_delay=request_delay)
        self.url = url
        self.use_mock = USE_MOCK_FETCHER if use_mock is None else use_mock

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if self.use_mock:
            logger.info("[%s] USE_MOCK=1，返回演示数据", self.name)
            return _mock_items(limit)

        remote = await self._fetch_remote_list(limit=limit)
        if remote:
            return remote[:limit]

        # HTTP 失败 → CDP 9222 打开币安广场（页内 cookie fetch / DOM）
        try:
            from news_mornitor.fetchers.cdp_square import fetch_via_cdp

            cdp_items = await fetch_via_cdp(Platform.BINANCE, limit=limit)
            if cdp_items:
                logger.info("[%s] CDP 回退命中 %d 条", self.name, len(cdp_items))
                return cdp_items[:limit]
        except Exception as e:
            logger.warning("[%s] CDP 回退失败: %s", self.name, e)

        logger.warning(
            "[%s] 公开 bapi + CDP 均不可用，回退本地广场 JSON（真帖真链）",
            self.name,
        )
        local = _load_local_square_posts(limit=limit)
        if not local:
            logger.warning(
                "[%s] 本地亦无数据。请先: Chrome --remote-debugging-port=9222 "
                "或 python -m binance.market_lists_selenium",
                self.name,
            )
            return []
        await self._enrich_from_detail(local)
        return local[:limit]

    async def _fetch_remote_list(self, *, limit: int) -> list[RawFetchItem]:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
        headers = _default_headers()
        proxy = proxy_url()
        # 去重候选，保留配置 URL
        seen_url: set[str] = set()
        candidates: list[tuple[str, dict[str, Any]]] = []
        for url, params in _LIST_CANDIDATES:
            if url in seen_url:
                continue
            seen_url.add(url)
            candidates.append((url, params))

        try:
            async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
                for url, params in candidates:
                    await self._sleep()
                    try:
                        async with session.get(
                            url, params=params, timeout=timeout, proxy=proxy
                        ) as resp:
                            text = await resp.text()
                            if resp.status != 200:
                                logger.warning(
                                    "[%s] %s → HTTP %s",
                                    self.name,
                                    url.split("/bapi/", 1)[-1][:60],
                                    resp.status,
                                )
                                continue
                            try:
                                data = json.loads(text)
                            except json.JSONDecodeError:
                                continue
                            parsed = _parse_list_payload(data)
                            if parsed:
                                logger.info("[%s] 远程列表命中 %s → %d 条", self.name, url, len(parsed))
                                return parsed[:limit]
                    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                        logger.warning("[%s] 请求失败 %s: %s", self.name, url, e)
        except Exception as e:
            self._log_error(e, "Binance Square HTTP")
        return []

    async def _enrich_from_detail(self, items: list[RawFetchItem]) -> None:
        """尽量用 content detail 覆盖本地占位互动数。"""
        timeout = aiohttp.ClientTimeout(total=min(HTTP_TIMEOUT_SEC, 12))
        headers = _default_headers()
        proxy = proxy_url()
        try:
            async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
                for item in items[:20]:
                    for base in _DETAIL_URLS:
                        try:
                            async with session.get(
                                base,
                                params={"contentId": item.external_id},
                                timeout=timeout,
                                proxy=proxy,
                            ) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json(content_type=None)
                                likes, comments, shares = _engagement_from_detail(data)
                                if likes or comments:
                                    item.like_count = likes
                                    item.comment_count = comments
                                    item.share_count = shares
                                    break
                        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
                            continue
                    await asyncio.sleep(0.15)
        except Exception as e:
            logger.warning("[%s] detail 补互动失败: %s", self.name, e)
