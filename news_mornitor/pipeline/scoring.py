"""热度打分：Score = (Likes*1 + Comments*3 + Shares*5) / (HoursPassed + 2)^1.5"""
from __future__ import annotations

from datetime import datetime, timezone

from news_mornitor.config import SQUARE_MIN_COMMENTS, SQUARE_MIN_LIKES
from news_mornitor.models import Post


def hours_passed(published_at: str, *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return 24.0
    delta = (now - ts).total_seconds() / 3600.0
    return max(delta, 0.0)


def compute_score(
    *,
    like_count: int,
    comment_count: int,
    share_count: int,
    published_at: str,
    now: datetime | None = None,
) -> float:
    engagement = like_count * 1 + comment_count * 3 + share_count * 5
    hours = hours_passed(published_at, now=now)
    return engagement / ((hours + 2.0) ** 1.5)


def apply_score(post: Post) -> Post:
    post.score = round(
        compute_score(
            like_count=post.like_count,
            comment_count=post.comment_count,
            share_count=post.share_count,
            published_at=post.published_at,
        ),
        4,
    )
    return post


def is_influential(
    post: Post,
    *,
    min_likes: int | None = None,
    min_comments: int | None = None,
) -> bool:
    """是否达到广场影响力门槛（默认 赞≥200 或 评≥30；TV / Farcaster 有特例）。"""
    from news_mornitor.config import TV_MIN_AGREES, TV_MIN_COMMENTS
    from news_mornitor.models import Platform

    plat = post.platform.value if hasattr(post.platform, "value") else str(post.platform)
    likes = int(post.like_count or 0)
    comments = int(post.comment_count or 0)

    if plat == Platform.TRADINGVIEW.value:
        likes_need = TV_MIN_AGREES if min_likes is None else int(min_likes)
        comments_need = TV_MIN_COMMENTS if min_comments is None else int(min_comments)
        return likes >= likes_need or comments >= comments_need

    # Hub 常无反应计数：有正文+真链即允许上榜（时间窗另控）
    if plat == Platform.FARCASTER.value and likes == 0 and comments == 0:
        content = (post.content or post.title or "").strip()
        url = (post.source_url or "").strip()
        return len(content) >= 40 and url.startswith("http")

    likes_need = SQUARE_MIN_LIKES if min_likes is None else int(min_likes)
    comments_need = SQUARE_MIN_COMMENTS if min_comments is None else int(min_comments)
    return likes >= likes_need or comments >= comments_need
