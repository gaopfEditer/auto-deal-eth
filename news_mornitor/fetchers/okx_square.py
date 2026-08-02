"""OKX 广场 / 社区热帖抓取。"""
from __future__ import annotations

import json
import logging

from news_mornitor.config import (
    OKX_SQUARE_HEADERS_JSON,
    OKX_SQUARE_URL,
    REQUEST_DELAY_SEC,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json, parse_generic_feed
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.OkxSquare")

_MOCK_SAMPLES = samples_for(Platform.OKX, n=16, offset=6)


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.okx.com/zh-hans/community",
        "Origin": "https://www.okx.com",
    }
    if OKX_SQUARE_HEADERS_JSON.strip():
        try:
            extra = json.loads(OKX_SQUARE_HEADERS_JSON)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        except json.JSONDecodeError as e:
            logger.warning("CRYPTO_PULSE_OKX_HEADERS_JSON 解析失败: %s", e)
    return headers


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.OKX)


def _real_url(eid: str) -> str:
    return f"https://www.okx.com/zh-hans/community/post/{eid}"


class OkxSquareFetcher(BaseFetcher):
    platform = Platform.OKX
    name = "okx_square"

    def __init__(
        self,
        *,
        url: str = OKX_SQUARE_URL,
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
                Platform.OKX, _MOCK_SAMPLES, limit=limit, url_builder=_mock_url
            )

        await self._sleep()
        data = await http_get_json(
            self.url,
            headers=_headers(),
            params={"page": 1, "size": min(limit, 50), "sort": "hot"},
            name=self.name,
        )
        if data is not None:
            parsed = parse_generic_feed(data, platform=Platform.OKX, url_builder=_real_url)
            if parsed:
                return parsed[:limit]
            logger.warning("[%s] HTTP 解析为空，尝试 CDP", self.name)
        else:
            logger.warning("[%s] HTTP 失败，尝试 CDP 9222", self.name)

        try:
            from news_mornitor.fetchers.cdp_square import fetch_via_cdp

            cdp_items = await fetch_via_cdp(Platform.OKX, limit=limit)
            if cdp_items:
                logger.info("[%s] CDP 回退命中 %d 条", self.name, len(cdp_items))
                return cdp_items[:limit]
        except Exception as e:
            logger.warning("[%s] CDP 回退失败: %s", self.name, e)
        return []
