"""TradingView Crypto Ideas — 解析公开 Ideas 页嵌入 JSON（likes + comments）。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from news_mornitor.config import (
    TRADINGVIEW_IDEAS_URL,
    USE_MOCK_FETCHER,
)
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_text
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.TradingView")

_MOCK = samples_for(Platform.TRADINGVIEW, n=16, offset=15)


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.TRADINGVIEW)


def _unescape_tv(s: str) -> str:
    try:
        return bytes(s, "utf-8").decode("unicode_escape")
    except Exception:
        return s


def _parse_ideas_from_html(html: str) -> list[dict[str, Any]]:
    """从 Ideas 页 HTML 抠 idea；当前页用 likes_count（已无 agree_count）。"""
    ideas: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1) 按 chart_url 定位卡片 JSON 窗口（最稳）
    for m in re.finditer(
        r'"chart_url"\s*:\s*"(https://www\.tradingview\.com/chart/[^"]+)"',
        html,
    ):
        window = html[max(0, m.start() - 2800) : m.start() + 1600]
        idm = re.search(r'"id"\s*:\s*(\d+)', window)
        namem = re.search(r'"name"\s*:\s*"((?:\\.|[^"\\])*)"', window)
        if not idm or not namem:
            continue
        eid = idm.group(1)
        if eid in seen:
            continue
        seen.add(eid)
        cm = re.search(r'"comments_count"\s*:\s*(\d+)', window)
        lm = re.search(r'"likes_count"\s*:\s*(\d+)', window)
        am = re.search(r'"agree_count"\s*:\s*(\d+)', window)
        bm = re.search(r'"boosts_count"\s*:\s*(\d+)', window)
        hot = re.search(r'"is_hot"\s*:\s*(true|false)', window)
        um = re.search(r'"username"\s*:\s*"((?:\\.|[^"\\])*)"', window)
        dm = re.search(r'"description"\s*:\s*"((?:\\.|[^"\\])*)"', window)
        ideas.append(
            {
                "id": int(eid),
                "name": _unescape_tv(namem.group(1)),
                "comments_count": int(cm.group(1)) if cm else 0,
                "likes_count": int(lm.group(1)) if lm else 0,
                "agree_count": int(am.group(1)) if am else 0,
                "boosts_count": int(bm.group(1)) if bm else 0,
                "is_hot": (hot.group(1) == "true") if hot else False,
                "chart_url": m.group(1),
                "user": {"username": _unescape_tv(um.group(1))} if um else {},
                "description": _unescape_tv(dm.group(1)) if dm else "",
            }
        )

    if ideas:
        return ideas

    # 2) 旧结构：ideas 数组
    for pat in (
        r'"ideas"\s*:\s*(\[[\s\S]*?\])\s*,\s*"total"',
        r'"list"\s*:\s*(\[\{"id":\d+[\s\S]*?\}\])\s*,\s*"',
    ):
        m = re.search(pat, html)
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
            if isinstance(arr, list):
                return [x for x in arr if isinstance(x, dict)]
        except json.JSONDecodeError:
            continue

    # 3) 宽松正则（兼容仍带 agree_count 的页）
    for m in re.finditer(
        r'"id"\s*:\s*(\d+)[\s\S]{0,1200}?"name"\s*:\s*"((?:\\.|[^"\\])*)"[\s\S]{0,2500}?'
        r'"comments_count"\s*:\s*(\d+)[\s\S]{0,800}?'
        r'(?:"likes_count"|"agree_count"|"boosts_count")\s*:\s*(\d+)',
        html,
    ):
        ideas.append(
            {
                "id": int(m.group(1)),
                "name": _unescape_tv(m.group(2)),
                "comments_count": int(m.group(3)),
                "likes_count": int(m.group(4)),
            }
        )
    return ideas


class TradingViewIdeasFetcher(BaseFetcher):
    platform = Platform.TRADINGVIEW
    name = "tradingview_ideas"

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if USE_MOCK_FETCHER:
            return build_mock_items(
                Platform.TRADINGVIEW, _MOCK, limit=limit, url_builder=_mock_url
            )

        html = await http_get_text(TRADINGVIEW_IDEAS_URL, name=self.name)
        if not html:
            # HTTP 失败 → CDP 打开 Ideas 页再解析
            try:
                from news_mornitor.fetchers.cdp_square import fetch_tradingview_ideas_cdp

                cdp_items = await fetch_tradingview_ideas_cdp(limit=limit)
                if cdp_items:
                    logger.info("[%s] CDP 回退命中 %d 条", self.name, len(cdp_items))
                    return cdp_items[:limit]
            except Exception as e:
                logger.warning("[%s] CDP 回退失败: %s", self.name, e)
            logger.warning("[%s] 页面拉取失败，本轮跳过", self.name)
            return []

        ideas = _parse_ideas_from_html(html)
        out: list[RawFetchItem] = []
        for idea in ideas:
            agrees = int(
                idea.get("agree_count")
                or idea.get("likes_count")
                or idea.get("boosts_count")
                or 0
            )
            comments = int(idea.get("comments_count") or 0)
            is_hot = bool(idea.get("is_hot"))
            if not is_hot and agrees <= 0 and comments <= 0:
                continue
            eid = str(idea.get("id") or idea.get("uuid") or "").strip()
            title = str(idea.get("name") or idea.get("title") or "").strip()
            if not eid or not title:
                continue
            author = ""
            user = idea.get("user") or idea.get("author") or {}
            if isinstance(user, dict):
                author = str(user.get("username") or user.get("name") or "")
            desc = str(idea.get("description") or idea.get("short_description") or title)
            chart = idea.get("chart_url") or idea.get("idea_url") or ""
            if isinstance(chart, str) and chart.startswith("/"):
                chart = f"https://www.tradingview.com{chart}"
            if not chart:
                chart = f"https://www.tradingview.com/chart/{eid}/"
            out.append(
                RawFetchItem(
                    external_id=eid,
                    platform=Platform.TRADINGVIEW,
                    author=author or "tradingview",
                    title=title[:200],
                    content=desc[:2000],
                    like_count=max(agrees, 1 if is_hot else agrees),
                    comment_count=comments,
                    share_count=int(idea.get("views_count") or 0),
                    source_url=str(chart),
                )
            )
            if len(out) >= limit * 2:
                break

        out.sort(key=lambda x: (x.like_count, x.comment_count), reverse=True)
        out = out[:limit]
        if not out:
            try:
                from news_mornitor.fetchers.cdp_square import fetch_tradingview_ideas_cdp

                cdp_items = await fetch_tradingview_ideas_cdp(limit=limit)
                if cdp_items:
                    logger.info("[%s] 解析空 → CDP 命中 %d 条", self.name, len(cdp_items))
                    return cdp_items[:limit]
            except Exception as e:
                logger.warning("[%s] CDP 回退失败: %s", self.name, e)
            logger.warning("[%s] 解析无观点，本轮跳过", self.name)
            return []
        logger.info("[%s] 解析 %d 条 Ideas", self.name, len(out))
        await self._sleep()
        return out
