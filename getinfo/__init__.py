"""
资讯获取模块 getinfo

- 宏观经济日历：AkShare 金十 4/5 星（高重要度）数据
- 消息权重判定：传播维度、NLP（Gemini）、市场联动
"""
from getinfo.calendar_akshare import get_high_impact_calendar

__all__ = ["get_high_impact_calendar"]

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
