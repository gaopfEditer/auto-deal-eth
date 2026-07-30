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
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.OkxSquare")

_MOCK_SAMPLES = [
    (
        "okx-eth-1",
        "OKX Insights",
        "ETH 质押占比再创新高，L2 费用探底",
        "质押 APR 小幅回落但锁仓仍增。Blob 利用率回升，$ETH 中期贝塔优于多数山寨。",
        880,
        134,
        46,
    ),
    (
        "okx-ordi-2",
        "铭文观察室",
        "BTC 生态：Runes 成交萎缩，$ORDI 缩量横盘",
        "铭文热度退潮后资金分化。若 BTC 突破，生态币或滞后跟涨；失效则继续阴跌。",
        390,
        67,
        18,
    ),
    (
        "okx-spam-3",
        "活动助手",
        "限时邀请码领空投",
        "点击链接用邀请码注册 OKX，免费领盲盒！躺赚！",
        11,
        1,
        28,
    ),
    (
        "okx-ai-4",
        "叙事追踪",
        "AI Agent 二次轮动：$FET 领涨后资金下沉",
        "龙头换手加快，小市值需严控仓位。关注是否带量突破前高，$TAO 联动。",
        620,
        95,
        29,
    ),
    (
        "okx-defi-5",
        "DeFi 早报",
        "链上稳定币供应周增，风险偏好回暖",
        "USDT/USDC 净铸造回升，CEX 净流出放缓。偏多但不追高，$BTC 主导。",
        510,
        74,
        21,
    ),
    (
        "okx-sui-6",
        "公链雷达",
        "SUI 生态 TVL 回升，注意解锁压力",
        "活跃地址与成交额同步改善。短线看能否站稳关键均线，$SUI 波动仍大。",
        450,
        82,
        24,
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


def _url(eid: str) -> str:
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
            return build_mock_items(Platform.OKX, _MOCK_SAMPLES, limit=limit, url_builder=_url)

        await self._sleep()
        data = await http_get_json(
            self.url,
            headers=_headers(),
            params={"page": 1, "size": min(limit, 50), "sort": "hot"},
            name=self.name,
        )
        if data is None:
            logger.warning("[%s] 请求失败，回退 mock", self.name)
            return build_mock_items(Platform.OKX, _MOCK_SAMPLES, limit=limit, url_builder=_url)

        parsed = parse_generic_feed(data, platform=Platform.OKX, url_builder=_url)
        if not parsed:
            logger.warning("[%s] 解析为空，回退 mock", self.name)
            return build_mock_items(Platform.OKX, _MOCK_SAMPLES, limit=limit, url_builder=_url)
        return parsed[:limit]
