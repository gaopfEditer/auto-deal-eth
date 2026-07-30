"""Binance Square Trending / Hot fetcher。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from news_mornitor.config import (
    BINANCE_SQUARE_HEADERS_JSON,
    BINANCE_SQUARE_TRENDING_URL,
    HTTP_TIMEOUT_SEC,
    REQUEST_DELAY_SEC,
    USE_MOCK_FETCHER,
    proxy_url,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.models import Platform, RawFetchItem, utc_now_iso

logger = logging.getLogger("CryptoPulse.BinanceSquare")


def _default_headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "clienttype": "web",
        "lang": "zh-CN",
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
    """无可用 API / 防爬失败时的演示数据，便于本地跑通全链路。"""
    samples = [
        (
            "mock-btc-1",
            "AlphaDesk",
            "BTC 突破后缩量回踩 97k，现货溢价回升",
            "现货持续吸筹，合约资金费率转正。若站稳中轨，下一目标看 102k；失效看回 94k 需求区。$BTC $ETH",
            1280,
            210,
            88,
            ["https://www.binance.com/zh-CN/square/post/mock-btc-1"],
        ),
        (
            "mock-sol-2",
            "链上观察员",
            "SOL 生态 TVL 周增 12%，meme 热度回流",
            "Jupiter 与 Raydium 成交额抬升，大户地址净流入。注意周末波动，$SOL 若失守关键支撑需降杠杆。",
            860,
            145,
            52,
            ["https://www.binance.com/zh-CN/square/post/mock-sol-2"],
        ),
        (
            "mock-spam-3",
            "空投猎人",
            "限时邀请码领 100U",
            "点击链接注册用我的邀请码，躺赚空投！无风险！快来！！",
            12,
            3,
            40,
            ["https://www.binance.com/zh-CN/square/post/mock-spam-3"],
        ),
        (
            "mock-eth-4",
            "DeFi 日报",
            "ETH L2 费用再创新低，Blob 利用率回升",
            "Base / Arbitrum 日活稳定，质押 APR 小幅回落。宏观若降息预期强化，$ETH 贝塔或放大。",
            640,
            98,
            31,
            ["https://www.binance.com/zh-CN/square/post/mock-eth-4"],
        ),
        (
            "mock-ai-5",
            "叙事雷达",
            "AI Agent 叙事二次发酵：$FET $TAO 资金轮动",
            "板块内龙头换手加快，小市值跟风需严控仓位。关注是否放量突破前高。",
            420,
            76,
            19,
            ["https://www.binance.com/zh-CN/square/post/mock-ai-5"],
        ),
        (
            "mock-macro-6",
            "宏观笔记",
            "美债收益率回落，风险偏好边际改善",
            "美元指数承压，黄金与加密同步走强。短线仍看非农与鲍威尔讲话，$BTC 主导贝塔。",
            510,
            64,
            22,
            ["https://www.binance.com/zh-CN/square/post/mock-macro-6"],
        ),
    ]
    now = utc_now_iso()
    out: list[RawFetchItem] = []
    for i, (eid, author, title, content, likes, comments, shares, urls) in enumerate(samples[:limit]):
        out.append(
            RawFetchItem(
                external_id=eid,
                platform=Platform.BINANCE,
                author=author,
                author_avatar=None,
                title=title,
                content=content,
                like_count=likes,
                comment_count=comments,
                share_count=shares,
                published_at=now,
                source_url=urls[0],
                image_urls=[],
            )
        )
        # 轻微时间错开
        try:
            dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            dt = dt.replace(minute=(dt.minute + i * 3) % 60)
            out[-1].published_at = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return out


def _parse_list_payload(data: Any) -> list[RawFetchItem]:
    """尽力兼容币安广场多种 JSON 结构。"""
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
                author=str(author_obj.get("nickname") or author_obj.get("displayName") or author_obj.get("name") or "unknown"),
                author_avatar=author_obj.get("avatar") or author_obj.get("avatarUrl"),
                title=title,
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

        await self._sleep()
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
        headers = _default_headers()
        params = {"page": 1, "pageSize": min(limit, 50), "contentType": "ALL"}
        proxy = proxy_url()

        try:
            async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
                async with session.get(
                    self.url,
                    params=params,
                    timeout=timeout,
                    proxy=proxy,
                ) as resp:
                    if resp.status == 429:
                        logger.warning("[%s] 429 限流，回退 mock", self.name)
                        return _mock_items(limit)
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(
                            "[%s] HTTP %s: %s，回退 mock",
                            self.name,
                            resp.status,
                            text[:200],
                        )
                        return _mock_items(limit)
                    data = await resp.json(content_type=None)
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as e:
            self._log_error(e, "Binance Square HTTP")
            return _mock_items(limit)

        parsed = _parse_list_payload(data)
        if not parsed:
            logger.warning("[%s] 解析为空，回退 mock（可配置 Headers/URL）", self.name)
            return _mock_items(limit)
        return parsed[:limit]
