"""Bitget Square / Insights 热帖抓取。"""
from __future__ import annotations

import json
import logging

from news_mornitor.config import (
    BITGET_SQUARE_HEADERS_JSON,
    BITGET_SQUARE_URL,
    REQUEST_DELAY_SEC,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json, parse_generic_feed
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.BitgetSquare")

_MOCK_SAMPLES = [
    (
        "bg-btc-1",
        "Bitget 研究院",
        "BTC 波动率压缩，突破前夜？",
        "合约持仓高位盘整，现货 ETF 净流入转正。关注 96k 得失，$BTC 若放量上行或带动山寨贝塔。",
        920,
        156,
        41,
    ),
    (
        "bg-copy-2",
        "跟单达人 Leo",
        "跟单策略周报：降低杠杆、等待非农",
        "本周胜率 58%，回撤控制在 4%。宏观窗口期建议仓位 ≤30%，$ETH 网格优于单边。",
        540,
        88,
        27,
    ),
    (
        "bg-spam-3",
        "福利官",
        "注册送盲盒 + 邀请码",
        "用我的邀请码注册 Bitget，躺赚手续费返佣！无风险！",
        8,
        2,
        35,
    ),
    (
        "bg-sol-4",
        "链上侦探",
        "SOL meme 退潮后资金去哪了",
        "部分回流蓝筹，部分进 AI agent。$SOL 链上活跃仍强，短线看 200 支撑是否守住。",
        710,
        102,
        33,
    ),
    (
        "bg-macro-5",
        "宏观快讯",
        "美元走弱窗口，风险资产共振",
        "DXY 跌破关键均线，黄金与加密同向。注意 FOMC 前缩仓，$BTC $ETH 联动。",
        480,
        71,
        19,
    ),
]


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.bitget.com/zh-CN/square",
        "Origin": "https://www.bitget.com",
    }
    if BITGET_SQUARE_HEADERS_JSON.strip():
        try:
            extra = json.loads(BITGET_SQUARE_HEADERS_JSON)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        except json.JSONDecodeError as e:
            logger.warning("CRYPTO_PULSE_BITGET_HEADERS_JSON 解析失败: %s", e)
    return headers


def _url(eid: str) -> str:
    return f"https://www.bitget.com/zh-CN/square/post/{eid}"


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
            return build_mock_items(Platform.BITGET, _MOCK_SAMPLES, limit=limit, url_builder=_url)

        await self._sleep()
        data = await http_get_json(
            self.url,
            headers=_headers(),
            params={"pageNo": 1, "pageSize": min(limit, 50), "type": "hot"},
            name=self.name,
        )
        if data is None:
            logger.warning("[%s] 请求失败，回退 mock", self.name)
            return build_mock_items(Platform.BITGET, _MOCK_SAMPLES, limit=limit, url_builder=_url)

        parsed = parse_generic_feed(data, platform=Platform.BITGET, url_builder=_url)
        if not parsed:
            logger.warning("[%s] 解析为空，回退 mock", self.name)
            return build_mock_items(Platform.BITGET, _MOCK_SAMPLES, limit=limit, url_builder=_url)
        return parsed[:limit]
