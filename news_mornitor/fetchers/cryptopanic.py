"""CryptoPanic — 全网新闻/社交投票聚合（需免费 developer auth_token）。"""
from __future__ import annotations

import logging
from typing import Any

from news_mornitor.config import (
    CRYPTOPANIC_API_URL,
    CRYPTOPANIC_AUTH_TOKEN,
    SQUARE_MIN_COMMENTS,
    SQUARE_MIN_LIKES,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.CryptoPanic")

_MOCK = samples_for(Platform.CRYPTOPANIC, n=8, offset=5)


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.CRYPTOPANIC)

class CryptoPanicFetcher(BaseFetcher):
    platform = Platform.CRYPTOPANIC
    name = "cryptopanic"

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if USE_MOCK_FETCHER:
            return build_mock_items(
                Platform.CRYPTOPANIC, _MOCK, limit=limit, url_builder=_mock_url
            )
        if not CRYPTOPANIC_AUTH_TOKEN:
            logger.warning(
                "[%s] 未配置 CRYPTO_PULSE_CRYPTOPANIC_TOKEN，本轮跳过。"
                "免费申请: https://cryptopanic.com/developers/api/",
                self.name,
            )
            return []

        data = await http_get_json(
            CRYPTOPANIC_API_URL,
            params={
                "auth_token": CRYPTOPANIC_AUTH_TOKEN,
                "public": "true",
                "filter": "hot",
                "kind": "news",
            },
            name=self.name,
        )
        rows: list[Any] = []
        if isinstance(data, dict):
            rows = data.get("results") or data.get("data") or []
        out: list[RawFetchItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            votes = row.get("votes") if isinstance(row.get("votes"), dict) else {}
            likes = int(
                votes.get("liked")
                or votes.get("positive")
                or votes.get("important")
                or 0
            )
            # CryptoPanic 无传统评论；用 negative+liked 近似互动，另取 comments 字段
            comments = int(row.get("comments") or votes.get("comments") or 0)
            # 若无 comments，用投票总量近似「互动」
            if comments <= 0:
                comments = int(votes.get("negative") or 0) + int(votes.get("liked") or 0)
            if likes < SQUARE_MIN_LIKES and (likes + comments) < SQUARE_MIN_LIKES:
                # 宽松：总投票达到门槛也算
                total = sum(int(votes.get(k) or 0) for k in ("liked", "positive", "important", "negative", "lol", "toxic"))
                if total < SQUARE_MIN_LIKES:
                    continue
                likes = max(likes, total)
            if comments < SQUARE_MIN_COMMENTS and likes < SQUARE_MIN_LIKES * 2:
                continue
            eid = str(row.get("id") or row.get("slug") or "").strip()
            title = str(row.get("title") or "").strip()
            if not eid or not title:
                continue
            url = str(row.get("url") or row.get("original_url") or f"https://cryptopanic.com/news/{eid}/")
            source = row.get("source") if isinstance(row.get("source"), dict) else {}
            author = str(source.get("title") or source.get("domain") or "CryptoPanic")
            out.append(
                RawFetchItem(
                    external_id=eid,
                    platform=Platform.CRYPTOPANIC,
                    author=author,
                    title=title[:200],
                    content=title,
                    like_count=likes,
                    comment_count=max(comments, SQUARE_MIN_COMMENTS if likes >= SQUARE_MIN_LIKES else comments),
                    share_count=int(votes.get("saved") or 0),
                    published_at=str(row.get("published_at") or row.get("created_at") or ""),
                    source_url=url,
                )
            )
            if len(out) >= limit:
                break
        if not out:
            logger.warning("[%s] API 无过门槛条目，本轮跳过", self.name)
            return []
        await self._sleep()
        return out
