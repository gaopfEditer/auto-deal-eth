"""Reddit r/CryptoCurrency — 优先近期热帖；PullPush 常返回陈年高赞，不足时 CDP 9222 抓 hot。"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from news_mornitor.config import (
    REDDIT_PULLPUSH_URL,
    REDDIT_SUBREDDIT,
    SQUARE_MIN_COMMENTS,
    SQUARE_MIN_LIKES,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.Reddit")

_MOCK = samples_for(Platform.REDDIT, n=16, offset=12)
# PullPush 归档偏旧：只收近 N 天；不够再走 CDP hot
_RECENT_DAYS = 14


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.REDDIT)


class RedditCryptoFetcher(BaseFetcher):
    platform = Platform.REDDIT
    name = "reddit_cryptocurrency"

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if USE_MOCK_FETCHER:
            return build_mock_items(
                Platform.REDDIT, _MOCK, limit=limit, url_builder=_mock_url
            )

        # 1) PullPush：按创建_utc 拉一批，再筛互动 + 近两周
        data = await http_get_json(
            REDDIT_PULLPUSH_URL,
            params={
                "subreddit": REDDIT_SUBREDDIT,
                "size": max(limit * 4, 80),
                "sort": "desc",
                "sort_type": "created_utc",
            },
            name=self.name,
            headers={"User-Agent": "CryptoPulse/1.0 (news_mornitor; +local)"},
        )
        if data is None:
            data = await asyncio.to_thread(self._pullpush_sync, limit)
        rows: list[Any] = []
        if isinstance(data, dict):
            rows = data.get("data") or []
        items = self._parse_rows(rows, limit=limit, recent_only=True)
        if items:
            logger.info("[%s] PullPush 近期 %d 条", self.name, len(items))
            await self._sleep()
            return items

        logger.warning(
            "[%s] PullPush 无近 %d 天过门槛帖（归档常滞后），尝试 CDP hot",
            self.name,
            _RECENT_DAYS,
        )
        try:
            from news_mornitor.fetchers.cdp_square import fetch_reddit_hot_cdp

            cdp_items = await fetch_reddit_hot_cdp(limit=limit)
            # CDP 结果再按门槛筛一遍
            kept = [
                x
                for x in cdp_items
                if x.like_count >= SQUARE_MIN_LIKES or x.comment_count >= SQUARE_MIN_COMMENTS
            ]
            if not kept:
                # hot 页近期帖可能赞未到 200：放宽为赞≥50 或 评≥15，避免整栏空白
                kept = [
                    x
                    for x in cdp_items
                    if x.like_count >= 50 or x.comment_count >= 15 or x.like_count >= 20
                ]
            if kept:
                logger.info("[%s] CDP hot 命中 %d 条", self.name, len(kept))
                return kept[:limit]
        except Exception as e:
            logger.warning("[%s] CDP 回退失败: %s", self.name, e)

        logger.warning("[%s] 无可用近期帖，本轮跳过", self.name)
        return []

    def _pullpush_sync(self, limit: int) -> dict[str, Any] | None:
        import json
        import urllib.parse
        import urllib.request

        qs = urllib.parse.urlencode(
            {
                "subreddit": REDDIT_SUBREDDIT,
                "size": max(limit * 4, 80),
                "sort": "desc",
                "sort_type": "created_utc",
            }
        )
        url = f"{REDDIT_PULLPUSH_URL}?{qs}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "CryptoPulse/1.0 (news_mornitor; +local)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("[%s] urllib 兜底失败: %s", self.name, e)
            return None

    def _parse_rows(
        self,
        rows: list[Any],
        *,
        limit: int,
        recent_only: bool = True,
    ) -> list[RawFetchItem]:
        out: list[RawFetchItem] = []
        cutoff = time.time() - _RECENT_DAYS * 86400
        for row in rows:
            if not isinstance(row, dict):
                continue
            likes = int(row.get("score") or 0)
            comments = int(row.get("num_comments") or 0)
            if likes < SQUARE_MIN_LIKES and comments < SQUARE_MIN_COMMENTS:
                continue
            created = row.get("created_utc")
            try:
                created_f = float(created)
            except (TypeError, ValueError):
                created_f = 0.0
            if recent_only and created_f and created_f < cutoff:
                continue
            eid = str(row.get("id") or row.get("fullname_id") or "").strip()
            if not eid:
                continue
            title = str(row.get("title") or "").strip()
            content = str(row.get("selftext") or title).strip()
            author = str(row.get("author") or "").strip() or "reddit"
            permalink = str(row.get("permalink") or "").strip()
            url = (
                f"https://www.reddit.com{permalink}"
                if permalink.startswith("/")
                else (
                    permalink
                    or f"https://www.reddit.com/r/{REDDIT_SUBREDDIT}/comments/{eid}/"
                )
            )
            try:
                pub = datetime.fromtimestamp(created_f, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except (TypeError, ValueError, OSError):
                pub = ""
            out.append(
                RawFetchItem(
                    external_id=eid,
                    platform=Platform.REDDIT,
                    author=author if author.startswith("u/") else f"u/{author}",
                    title=title[:200],
                    content=content[:2000],
                    like_count=likes,
                    comment_count=comments,
                    share_count=int(row.get("num_crossposts") or 0),
                    published_at=pub,
                    source_url=url,
                )
            )
            if len(out) >= limit:
                break
        return out
