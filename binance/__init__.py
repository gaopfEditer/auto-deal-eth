"""
币安 Square / 市场列表：抓取、状态、发帖。

命令行（在项目根目录，建议先 source venv/bin/activate）：
  python -m binance.market_lists_selenium
  python -m binance.square_publish --text "…"
"""
from __future__ import annotations

from binance.paths import (
    BINANCE_DIR,
    DEFAULT_MARKET_LISTS_FILE,
    DEFAULT_POSTS_STATE_FILE,
    MARKET_LISTS_PROMPT_FILE,
    REPO_ROOT,
)

__all__ = [
    "BINANCE_DIR",
    "REPO_ROOT",
    "DEFAULT_POSTS_STATE_FILE",
    "DEFAULT_MARKET_LISTS_FILE",
    "MARKET_LISTS_PROMPT_FILE",
    "POST_RETENTION_HOURS",
    "default_posts_state_path",
    "load_posts_state",
    "save_posts_state",
    "process_watchlist_posts",
    "publish_square_post",
    "PublishResult",
]


def __getattr__(name: str):
    if name in (
        "POST_RETENTION_HOURS",
        "default_posts_state_path",
        "load_posts_state",
        "save_posts_state",
        "process_watchlist_posts",
    ):
        from binance import posts_state as ps

        return getattr(ps, name)
    if name == "publish_square_post":
        from binance.square_publish import publish_square_post

        return publish_square_post
    if name == "PublishResult":
        from binance.square_publish import PublishResult

        return PublishResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
