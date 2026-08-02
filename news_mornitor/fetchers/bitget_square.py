"""Bitget Insights 热帖抓取（旧 square API 已 404，主路径 CDP 打开 Insights）。"""
from __future__ import annotations

import json
import logging

from news_mornitor.config import (
    BITGET_INSIGHTS_URL,
    BITGET_SQUARE_HEADERS_JSON,
    BITGET_SQUARE_URL,
    REQUEST_DELAY_SEC,
    SQUARE_MIN_COMMENTS,
    SQUARE_MIN_LIKES,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json, parse_generic_feed
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.BitgetSquare")

_MOCK_SAMPLES = samples_for(Platform.BITGET, n=16, offset=3)


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": BITGET_INSIGHTS_URL or "https://www.bitget.com/zh-CN/insights",
        "Origin": "https://www.bitget.com",
        "locale": "zh_CN",
    }
    if BITGET_SQUARE_HEADERS_JSON.strip():
        try:
            extra = json.loads(BITGET_SQUARE_HEADERS_JSON)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        except json.JSONDecodeError as e:
            logger.warning("CRYPTO_PULSE_BITGET_HEADERS_JSON 解析失败: %s", e)
    return headers


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.BITGET)


def _real_url(eid: str) -> str:
    return f"https://www.bitget.com/zh-CN/insights/posts/{eid}"


class BitgetSquareFetcher(BaseFetcher):
    platform = Platform.BITGET
    name = "bitget_square"

    def __init__(
        self,
        *,
        url: str = BITGET_SQUARE_URL,
        request_delay: float = REQUEST_DELAY_SEC,
        use_mock: bool | None = None,
    ) -> None:
        super().__init__(request_delay=request_delay)
        self.url = url
        self.use_mock = USE_MOCK_FETCHER if use_mock is None else use_mock

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if self.use_mock:
            logger.info("[%s] USE_MOCK=1，返回演示数据", self.name)
            return build_mock_items(
                Platform.BITGET, _MOCK_SAMPLES, limit=limit, url_builder=_mock_url
            )

        # 1) 旧公开 API（多数已 404，保留作快路径）
        await self._sleep()
        data = await http_get_json(
            self.url,
            headers=_headers(),
            params={"pageNo": 1, "pageSize": min(limit, 50), "type": "hot"},
            name=self.name,
        )
        if data is not None:
            parsed = parse_generic_feed(data, platform=Platform.BITGET, url_builder=_real_url)
            if parsed:
                return parsed[:limit]

        # 2) CDP：打开 Insights 页扫 /insights/posts/ 真链
        logger.warning("[%s] HTTP 不可用，CDP 打开 Insights", self.name)
        try:
            from news_mornitor.fetchers.cdp_square import fetch_bitget_insights_cdp

            cdp_items = await fetch_bitget_insights_cdp(limit=max(limit, 30))
            kept = [
                x
                for x in cdp_items
                if x.like_count >= SQUARE_MIN_LIKES or x.comment_count >= SQUARE_MIN_COMMENTS
            ]
            if not kept:
                # 热流里中等热度也先收，避免整栏空白
                kept = [
                    x
                    for x in cdp_items
                    if x.like_count >= 30 or x.comment_count >= 10 or len(x.content or "") >= 80
                ]
            if kept:
                logger.info("[%s] Insights CDP 命中 %d 条", self.name, len(kept))
                return kept[:limit]
        except Exception as e:
            logger.warning("[%s] CDP 回退失败: %s", self.name, e)
        return []
