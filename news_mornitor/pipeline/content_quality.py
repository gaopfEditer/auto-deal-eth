"""内容过滤：去掉明显媒体简报腔；其余只要热度过门槛即可（长短不限）。"""
from __future__ import annotations

import re

from news_mornitor.models import Post

# 硬过滤：用户点名讨厌的研报/快讯标题腔
_WIRE_PATTERNS = [
    re.compile(r"再创新高"),
    re.compile(r"费用探底|溢价回升|缩量回踩"),
    re.compile(r"风险资产共振|风险偏好(边际)?(改善|回暖)"),
    re.compile(r"美元走弱窗口|美债收益率"),
    re.compile(r"TVL\s*周增|日活稳定|Blob 利用率"),
    re.compile(r"宏观若降息|主导贝塔|山寨贝塔"),
    re.compile(r"资金轮动|叙事二次发酵|板块内龙头"),
    re.compile(r"ETF\s*净流入|合约资金费率转正"),
    re.compile(r"下一目标看|失效看回|关注是否放量"),
    re.compile(r"Aggregated headlines|community bullish votes", re.I),
]

_MEDIA_AUTHORS = re.compile(
    r"(日报|早报|快讯|研究院|宏观笔记|叙事雷达|DeFi 日报|活动助手|福利官|空投猎人)",
    re.I,
)


def is_generic_wire(title: str, content: str, author: str = "") -> bool:
    text = f"{title}\n{content}"
    if _MEDIA_AUTHORS.search(author or ""):
        return True
    hits = sum(1 for p in _WIRE_PATTERNS if p.search(text))
    return hits >= 2


def passes_content_filter(post: Post) -> bool:
    """
    展示过滤：
    - 媒体简报腔 → 否
    - 邀请码垃圾（is_spam）由外层处理
    - 其余长短不限，交给热度门槛
    """
    title = (post.title or "").strip()
    content = (post.content or "").strip()
    if not title and not content:
        return False
    if is_generic_wire(title, content, post.author or ""):
        return False
    return True


# 兼容旧名
def is_useful_personal_post(post: Post) -> bool:
    return passes_content_filter(post)
