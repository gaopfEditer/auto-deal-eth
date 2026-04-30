"""
消息权重判定：三维判定法

A. 传播维度 (Propagation Weight)：首发/独家、30 分钟内 BBC 跟进等
B. 关键词与语义 (NLP Weight)：Gemini API 对标题做关键词/情绪打分，5 星/4 星特征词
C. 市场联动 (Market Reflexivity)：消息发布后 1～5 分钟 Oil/BTC 1 分钟线波动率 > 2σ 则标为高权重
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Any

# 5 星特征词（英文，用于 Gemini 或本地匹配）
STAR5_KEYWORDS = [
    "escalation", "direct strike", "nuclear", "sanction", "closed strait",
    "exclusive", "urgent", "breaking",
]
# 4 星特征词
STAR4_KEYWORDS = [
    "warning", "mobilization", "cyber attack", "emergency meeting",
    "live update", "developing",
]


@dataclass
class NewsItem:
    """单条快讯/新闻，用于权重计算。"""
    title: str
    source: str  # e.g. "Reuters", "BBC"
    published_at: Optional[datetime] = None
    is_exclusive: bool = False
    is_urgent: bool = False
    raw: Any = None


@dataclass
class FollowUp:
    """跟进报道（用于传播维度：如 BBC 在 30 分钟内跟进）。"""
    source: str
    published_at: datetime
    is_live_update: bool = False


def propagation_weight(
    item: NewsItem,
    follow_ups: Optional[List[FollowUp]] = None,
    bbc_follow_minutes: int = 30,
) -> int:
    """
    A. 传播维度权重 (1～5 星)。

    - 路透 EXCLUSIVE / URGENT -> 5 星
    - 路透首发后，BBC 在 bbc_follow_minutes 内跟进且为 Live Update -> 5 星
    - 否则可返回 3 星或由调用方自定义
    """
    stars = 3  # 默认
    if item.is_exclusive or item.is_urgent:
        return 5
    title_lower = (item.title or "").strip().lower()
    if "exclusive" in title_lower or "urgent" in title_lower:
        return 5

    if follow_ups and item.published_at:
        cutoff = item.published_at + timedelta(minutes=bbc_follow_minutes)
        for fu in follow_ups:
            if fu.source.upper() == "BBC" and fu.published_at <= cutoff:
                if fu.is_live_update:
                    return 5
                stars = max(stars, 4)
    return stars


def nlp_weight_gemini(
    title: str,
    api_key: Optional[str] = None,
    timeout: int = 30,
) -> int:
    """
    B. NLP 权重：用 Gemini 对标题做关键词/语义打分，返回 1～5 星。

    5 星特征词：Escalation, Direct Strike, Nuclear, Sanction, Closed Strait 等
    4 星特征词：Warning, Mobilization, Cyber Attack, Emergency Meeting 等
    """
    if not title or not title.strip():
        return 1
    # 本地快速规则：命中 5 星词 -> 5，命中 4 星词 -> 4
    t = title.strip().lower()
    for k in STAR5_KEYWORDS:
        if k in t:
            return 5
    for k in STAR4_KEYWORDS:
        if k in t:
            return 4

    # 可选：调用 Gemini 做语义打分
    key = api_key or _get_gemini_key()
    if key:
        try:
            return _gemini_score_title(title, key, timeout)
        except Exception:
            pass
    return 3


def _get_gemini_key() -> Optional[str]:
    try:
        from config import GEMINI_API_KEY
        k = (GEMINI_API_KEY or "").strip()
        return k if k else None
    except Exception:
        return None


def _gemini_score_title(title: str, api_key: str, timeout: int) -> int:
    """调用 Gemini 仅文本，要求返回 1～5 的整数星数。"""
    import requests
    prompt = f"""你是一个财经/地缘新闻权重评估助手。仅根据标题判断该条新闻对市场的影响权重。
规则：
- 5 星（最高）：涉及升级、直接打击、核、制裁、海峡关闭、独家/紧急快讯等。
- 4 星：涉及警告、动员、网络攻击、紧急会议、实时直播等。
- 3 星：一般重要新闻。
- 2 星：次要。
- 1 星：影响很小。

标题（英文或中文）：{title}

请只回复一个数字 1、2、3、4 或 5，不要其他文字。"""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    r = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 10},
        },
        timeout=timeout,
    )
    if r.status_code != 200:
        return 3
    text = (
        r.json()
        .get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    for c in text:
        if c in "12345":
            return min(5, max(1, int(c)))
    return 3


def market_reflexivity_weight(
    publish_time: Optional[datetime],
    symbol: str = "BTC",
    window_minutes: int = 5,
    sigma_multiple: float = 2.0,
) -> Optional[int]:
    """
    C. 市场联动权重：发布后 1～window_minutes 分钟内，1 分钟线波动率若 > sigma_multiple * σ，则标为高权重（5 星）。

    需要 1 分钟 K 线数据；若无法获取则返回 None（调用方视为未计算）。
    symbol: 'BTC' 或 'OIL'（布伦特原油等）
    """
    if not publish_time:
        return None
    try:
        vol, sigma = _minute_volatility_after(publish_time, symbol, window_minutes)
    except Exception:
        return None
    if sigma is None or sigma <= 0:
        return None
    if vol is not None and vol > sigma_multiple * sigma:
        return 5
    return 3


def _minute_volatility_after(
    from_time: datetime,
    symbol: str,
    window_minutes: int,
) -> tuple:
    """计算 from_time 起 window_minutes 内的 1 分钟波动率与历史 σ。返回 (波动率, 历史标准差) 或 (None, None)。"""
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        return None, None

    # 取稍长区间以估计历史 sigma（例如前 60 根 1 分钟）
    end_dt = from_time + timedelta(minutes=window_minutes)
    # akshare 加密货币 1 分钟：接口可能为 stock_zh_a_hist_min_em 或 crypto 相关
    # 这里用通用思路：若项目有 sector/fetcher 的行情接口可复用
    if symbol.upper() == "BTC":
        try:
            # 部分版本有 ak.crypto_btc_spot_hist_min() 等，此处用占位
            df = _fetch_crypto_minute(from_time, end_dt, "BTC")
        except Exception:
            df = None
    elif symbol.upper() in ("OIL", "BRENT", "WTI"):
        try:
            df = _fetch_oil_minute(from_time, end_dt)
        except Exception:
            df = None
    else:
        df = None

    if df is None or df.empty or "close" not in df.columns:
        return None, None

    # 窗口内收益率绝对值或波动
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 2:
        return None, None
    ret = close.pct_change().dropna()
    vol_window = ret.abs().mean()  # 或 std
    sigma_hist = ret.std()
    if pd.isna(sigma_hist) or sigma_hist <= 0:
        return float(vol_window) if not pd.isna(vol_window) else None, None
    return float(vol_window), float(sigma_hist)


def _fetch_crypto_minute(start: datetime, end: datetime, symbol: str):
    """占位：从 akshare 或其它源拉取 1 分钟 K 线。"""
    try:
        import akshare as ak
        # 部分 akshare 有 crypto 分钟；无则返回 None
        if hasattr(ak, "crypto_btc_spot_hist_min_em"):
            return getattr(ak, "crypto_btc_spot_hist_min_em")()
        if hasattr(ak, "crypto_hist"):
            return ak.crypto_hist(symbol=symbol, period="1min", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    except Exception:
        pass
    return None


def _fetch_oil_minute(start: datetime, end: datetime):
    """占位：布伦特/ WTI 1 分钟。akshare 期货分钟接口若有则用。"""
    return None


def score_news_weight(
    item: NewsItem,
    follow_ups: Optional[List[FollowUp]] = None,
    use_nlp: bool = True,
    use_market: bool = False,
    gemini_key: Optional[str] = None,
) -> dict:
    """
    综合三维权重，返回各维度星数及综合星数（取 max 或 平均，此处用 max 突出高影响）。

    Returns:
        {"propagation": 1-5, "nlp": 1-5, "market": 1-5 or None, "score": 1-5}
    """
    prop = propagation_weight(item, follow_ups)
    nlp = nlp_weight_gemini(item.title, gemini_key) if use_nlp else 3
    market = None
    if use_market and item.published_at:
        market = market_reflexivity_weight(item.published_at, symbol="BTC", window_minutes=5)
    parts = [prop, nlp]
    if market is not None:
        parts.append(market)
    return {
        "propagation": prop,
        "nlp": nlp,
        "market": market,
        "score": max(parts) if parts else 3,
    }
