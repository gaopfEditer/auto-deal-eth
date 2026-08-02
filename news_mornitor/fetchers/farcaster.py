"""Farcaster / Warpcast — 优先 Pinata Hub casts；失败回退高互动 mock。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from news_mornitor.config import (
    FARCASTER_CHANNEL,
    FARCASTER_HUB_URL,
    SQUARE_MIN_COMMENTS,
    SQUARE_MIN_LIKES,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.Farcaster")

# 若干加密向 FID（公开人物，用于 hub castsByFid 抽样）
_CRYPTO_FIDS = (3, 5650, 2, 239, 1214)

_MOCK = samples_for(Platform.FARCASTER, n=16, offset=18)


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.FARCASTER)


class FarcasterFetcher(BaseFetcher):
    platform = Platform.FARCASTER
    name = "farcaster"

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if USE_MOCK_FETCHER:
            return build_mock_items(
                Platform.FARCASTER, _MOCK, limit=limit, url_builder=_mock_url
            )

        out: list[RawFetchItem] = []
        for fid in _CRYPTO_FIDS:
            data = await http_get_json(
                f"{FARCASTER_HUB_URL}/v1/castsByFid",
                params={"fid": fid, "pageSize": 20, "reverse": "true"},
                name=self.name,
            )
            messages = []
            if isinstance(data, dict):
                messages = data.get("messages") or data.get("casts") or []
            for msg in messages:
                item = self._cast_to_item(msg)
                if item:
                    out.append(item)
            if len(out) >= limit:
                break

        # 去重 + 门槛
        uniq: dict[str, RawFetchItem] = {}
        for it in out:
            if it.like_count < SQUARE_MIN_LIKES and it.comment_count < SQUARE_MIN_COMMENTS:
                # hub 常无反应计数 → 保留文本较长的近期 cast 作候选，后续靠 mock 补
                if len(it.content or "") < 80:
                    continue
            uniq[it.external_id] = it
        items = list(uniq.values())[:limit]
        if not items:
            logger.warning(
                "[%s] Hub 无可用 cast（反应字段常缺失），本轮跳过；channel=%s",
                self.name,
                FARCASTER_CHANNEL,
            )
            return []
        await self._sleep()
        return items

    def _cast_to_item(self, msg: Any) -> RawFetchItem | None:
        if not isinstance(msg, dict):
            return None
        data = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        cast = data.get("castAddBody") if isinstance(data.get("castAddBody"), dict) else data
        text = str(cast.get("text") or msg.get("text") or "").strip()
        if not text:
            return None
        eid = str(
            msg.get("hash")
            or cast.get("hash")
            or data.get("hash")
            or abs(hash(text))
        )
        fid = data.get("fid") or msg.get("fid") or ""
        # Hub 消息通常不含 likes；用 0，靠 mock/Neynar 补强。若有 reactions 则解析。
        likes = int(msg.get("likesCount") or msg.get("reactionCount") or 0)
        comments = int(msg.get("repliesCount") or msg.get("recastsCount") or 0)
        ts = data.get("timestamp") or msg.get("timestamp")
        pub = ""
        try:
            # Farcaster epoch: seconds since 2021-01-01
            if ts is not None:
                unix = int(ts) + 1609459200
                pub = datetime.fromtimestamp(unix, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
        except (TypeError, ValueError, OSError):
            pub = ""
        return RawFetchItem(
            external_id=eid[:32],
            platform=Platform.FARCASTER,
            author=f"fid:{fid}" if fid else "farcaster",
            title=text[:120],
            content=text[:2000],
            like_count=likes,
            comment_count=comments,
            published_at=pub,
            source_url=f"https://warpcast.com/~/conversations/{eid}",
        )
