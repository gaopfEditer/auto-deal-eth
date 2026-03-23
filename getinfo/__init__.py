"""
资讯获取模块 getinfo

- 宏观经济日历：AkShare 金十 4/5 星（高重要度）数据
- RSSHub 简报：从 RSSHub 拉取资讯，可选 Gemini 提纯，推送 Telegram
- 消息权重判定：传播维度、NLP（Gemini）、市场联动
"""
from getinfo.calendar_akshare import get_high_impact_calendar

__all__ = ["get_high_impact_calendar"]

try:
    from getinfo.rsshub_feed import (
        get_rss_feeds,
        fetch_feed_entries,
        generate_morning_report,
        filter_with_gemini,
    )
    __all__ += ["get_rss_feeds", "fetch_feed_entries", "generate_morning_report", "filter_with_gemini"]
except ImportError:
    pass

try:
    from getinfo.binance_square_cdp import (
        fetch_hot_and_process_new,
        call_gemini_chat,
        run_binance_square_once,
        log_snapshot_event,
        show_last_snapshot_from_cache,
    )
    __all__ += [
        "fetch_hot_and_process_new",
        "call_gemini_chat",
        "run_binance_square_once",
        "log_snapshot_event",
        "show_last_snapshot_from_cache",
    ]
except ImportError:
    pass

try:
    from getinfo.weight import (
        propagation_weight,
        nlp_weight_gemini,
        market_reflexivity_weight,
        score_news_weight,
        NewsItem,
        FollowUp,
    )
    __all__ += [
        "propagation_weight",
        "nlp_weight_gemini",
        "market_reflexivity_weight",
        "score_news_weight",
        "NewsItem",
        "FollowUp",
    ]
except ImportError:
    pass
