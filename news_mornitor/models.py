"""核心数据模型（Pydantic）— 对应 SCHEMA.md，无数据库。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Platform(str, Enum):
    BINANCE = "BINANCE"
    BITGET = "BITGET"
    OKX = "OKX"
    TWITTER = "TWITTER"


def make_post_id(platform: Platform | str, external_id: str) -> str:
    raw = f"{platform}:{external_id}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Post(BaseModel):
    id: str
    external_id: str
    platform: Platform
    author: str = ""
    author_avatar: str | None = None
    title: str = ""
    content: str = ""
    summary: str | None = None
    mentioned_tickers: list[str] = Field(default_factory=list)
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    score: float = 0.0
    is_spam: bool = False
    published_at: str = ""
    fetched_at: str = ""
    source_url: str = ""
    image_urls: list[str] = Field(default_factory=list)

    @classmethod
    def from_raw(
        cls,
        *,
        platform: Platform,
        external_id: str,
        author: str = "",
        author_avatar: str | None = None,
        title: str = "",
        content: str = "",
        like_count: int = 0,
        comment_count: int = 0,
        share_count: int = 0,
        published_at: str = "",
        source_url: str = "",
        image_urls: list[str] | None = None,
        mentioned_tickers: list[str] | None = None,
    ) -> "Post":
        return cls(
            id=make_post_id(platform, external_id),
            external_id=str(external_id),
            platform=platform,
            author=author or "",
            author_avatar=author_avatar,
            title=title or "",
            content=content or "",
            mentioned_tickers=list(mentioned_tickers or []),
            like_count=int(like_count or 0),
            comment_count=int(comment_count or 0),
            share_count=int(share_count or 0),
            published_at=published_at or utc_now_iso(),
            fetched_at=utc_now_iso(),
            source_url=source_url or "",
            image_urls=list(image_urls or []),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Ticker(BaseModel):
    symbol: str
    mention_count_24h: int = 0
    post_ids: list[str] = Field(default_factory=list)
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class RawFetchItem(BaseModel):
    """Fetcher 产出的统一原始项。"""

    external_id: str
    platform: Platform
    author: str = ""
    author_avatar: str | None = None
    title: str = ""
    content: str = ""
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    published_at: str = ""
    source_url: str = ""
    image_urls: list[str] = Field(default_factory=list)


class MacroBias(str, Enum):
    """对加密风险资产的倾向（非投资建议）。"""

    BULLISH = "bullish"  # 利好
    BEARISH = "bearish"  # 利空
    NEUTRAL = "neutral"  # 中性


BIAS_LABELS: dict[str, str] = {
    MacroBias.BULLISH.value: "利好",
    MacroBias.BEARISH.value: "利空",
    MacroBias.NEUTRAL.value: "中性",
}


class MacroEvent(BaseModel):
    """金十风格宏观大事件（时间轴）。"""

    id: str
    title: str
    country: str = ""
    star: int = 3
    publish_at: str = ""
    previous: str | None = None
    consensus: str | None = None
    actual: str | None = None
    bias: MacroBias = MacroBias.NEUTRAL
    bias_label: str = "中性"
    bias_reason: str = ""
    source: str = "jinshi"
    source_url: str = "https://rili.jin10.com/"

    def to_public_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        d["bias_label"] = BIAS_LABELS.get(self.bias.value, self.bias_label or "中性")
        return d
