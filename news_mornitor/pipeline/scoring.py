"""热度打分：Score = (Likes*1 + Comments*3 + Shares*5) / (HoursPassed + 2)^1.5"""
from __future__ import annotations

from datetime import datetime, timezone

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
