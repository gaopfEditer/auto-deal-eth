"""各广场共用：mock 构造、通用 JSON 列表解析、HTTP GET。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from news_mornitor.config import HTTP_TIMEOUT_SEC, proxy_url
from news_mornitor.models import Platform, RawFetchItem, utc_now_iso

logger = logging.getLogger("CryptoPulse.FetcherUtil")


def build_mock_items(
    platform: Platform,
    samples: list[tuple],
    *,
    limit: int,
    url_builder,
) -> list[RawFetchItem]:
    """
    samples 元组：
      (external_id, author, title, content, likes, comments, shares)
    """
    now = utc_now_iso()
    out: list[RawFetchItem] = []
    for i, row in enumerate(samples[:limit]):
        eid, author, title, content, likes, comments, shares = row[:7]
        item = RawFetchItem(
            external_id=str(eid),
            platform=platform,
            author=str(author),
            author_avatar=None,
            title=str(title),
            content=str(content),
            like_count=int(likes),
            comment_count=int(comments),
            share_count=int(shares),
            published_at=now,
            source_url=url_builder(str(eid)),
            image_urls=[],
        )
        try:
            dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            dt = dt.replace(minute=(dt.minute + i * 3) % 60)
            item.published_at = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
        out.append(item)
    return out


def _dig_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "list", "voList", "contents", "result", "items", "records", "rows"):
        node = data.get(key)
        if isinstance(node, list):
            return node
        if isinstance(node, dict):
            for k2 in ("list", "voList", "contents", "data", "items", "records"):
                if isinstance(node.get(k2), list):
                    return node[k2]
    return []


def parse_generic_feed(
    data: Any,
    *,
    platform: Platform,
    url_builder,
) -> list[RawFetchItem]:
    """尽力兼容各所广场/社区 JSON。"""
    out: list[RawFetchItem] = []
    for raw in _dig_list(data):
        if not isinstance(raw, dict):
            continue
        body = raw.get("body") or raw.get("content") or raw.get("post") or raw.get("squareContent") or raw
        if not isinstance(body, dict):
            body = raw
        eid = str(
            body.get("id")
            or body.get("contentId")
            or body.get("postId")
            or body.get("articleId")
            or raw.get("id")
            or ""
        )
        if not eid:
            continue
        author_obj = body.get("author") or body.get("user") or body.get("creator") or raw.get("author") or {}
        if not isinstance(author_obj, dict):
            author_obj = {}
        text = (
            body.get("body")
            or body.get("content")
            or body.get("text")
            or body.get("summary")
            or body.get("title")
            or ""
        )
        if isinstance(text, dict):
            text = text.get("text") or text.get("content") or json.dumps(text, ensure_ascii=False)
        title = str(body.get("title") or body.get("subject") or "")[:200]
        likes = int(
            body.get("likeCount")
            or body.get("like_count")
            or body.get("likedCount")
            or body.get("praiseCount")
            or 0
        )
        comments = int(
            body.get("commentCount")
            or body.get("comment_count")
            or body.get("replyCount")
            or 0
        )
        shares = int(
            body.get("shareCount")
            or body.get("share_count")
            or body.get("forwardCount")
            or body.get("repostCount")
            or 0
        )
        pub = body.get("createTime") or body.get("publishedAt") or body.get("createDate") or body.get("ctime") or ""
        if isinstance(pub, (int, float)) and pub > 1e11:
            pub = datetime.fromtimestamp(pub / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(pub, (int, float)) and pub > 1e9:
            pub = datetime.fromtimestamp(pub, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            pub = str(pub) if pub else utc_now_iso()

        images: list[str] = []
        for img_key in ("imageList", "images", "imageUrls", "pics"):
            arr = body.get(img_key)
            if isinstance(arr, list):
                for x in arr:
                    if isinstance(x, str):
                        images.append(x)
                    elif isinstance(x, dict) and (x.get("url") or x.get("src")):
                        images.append(str(x.get("url") or x.get("src")))

        out.append(
            RawFetchItem(
                external_id=eid,
                platform=platform,
                author=str(
                    author_obj.get("nickname")
                    or author_obj.get("displayName")
                    or author_obj.get("name")
                    or author_obj.get("username")
                    or "unknown"
                ),
                author_avatar=author_obj.get("avatar") or author_obj.get("avatarUrl"),
                title=title,
                content=str(text),
                like_count=likes,
                comment_count=comments,
                share_count=shares,
                published_at=pub,
                source_url=url_builder(eid),
                image_urls=images[:6],
            )
        )
    return out


async def http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    name: str = "fetcher",
) -> Any | None:
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    try:
        async with aiohttp.ClientSession(headers=headers or {}, trust_env=True) as session:
            async with session.get(
                url,
                params=params,
                timeout=timeout,
                proxy=proxy_url(),
            ) as resp:
                if resp.status == 429:
                    logger.warning("[%s] 429 限流", name)
                    return None
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("[%s] HTTP %s: %s", name, resp.status, text[:200])
                    return None
                return await resp.json(content_type=None)
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as e:
        logger.warning("[%s] 请求失败: %s", name, e)
        return None


async def http_get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    name: str = "fetcher",
) -> str | None:
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }
    merged = {**default_headers, **(headers or {})}
    try:
        async with aiohttp.ClientSession(headers=merged, trust_env=True) as session:
            async with session.get(
                url,
                params=params,
                timeout=timeout,
                proxy=proxy_url(),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("[%s] HTTP %s: %s", name, resp.status, text[:200])
                    return None
                return await resp.text()
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        logger.warning("[%s] 请求失败: %s", name, e)
        return None
