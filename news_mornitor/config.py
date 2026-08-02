"""CryptoPulse / news_mornitor 配置。"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


_PKG_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_ROOT.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_PKG_ROOT / ".env")
load_dotenv()

DATA_DIR = Path(os.getenv("CRYPTO_PULSE_DATA_DIR", str(_PKG_ROOT / "data")))
POSTS_FILE = DATA_DIR / "posts.json"
TICKERS_FILE = DATA_DIR / "tickers.json"
SEEN_IDS_FILE = DATA_DIR / "seen_ids.json"
MACRO_FILE = DATA_DIR / "macro_events.json"
CACHE_DIR = DATA_DIR / "cache"

# 宏观日历（金十风格）：≥N★，北京时间窗口：过去/未来各最多 3 天
MACRO_MIN_STAR = int(os.getenv("CRYPTO_PULSE_MACRO_MIN_STAR", "3"))
MACRO_AHEAD_HOURS = int(os.getenv("CRYPTO_PULSE_MACRO_AHEAD_HOURS", "72"))
MACRO_BEHIND_HOURS = int(os.getenv("CRYPTO_PULSE_MACRO_BEHIND_HOURS", "72"))
MACRO_REFRESH_SEC = int(os.getenv("CRYPTO_PULSE_MACRO_REFRESH_SEC", "600"))
MACRO_TZ = os.getenv("CRYPTO_PULSE_MACRO_TZ", "Asia/Shanghai").strip() or "Asia/Shanghai"
JINSHI_CALENDAR_URL = os.getenv(
    "CRYPTO_PULSE_JINSHI_URL",
    "https://cdn-rili.jin10.com/data.json",
)
JINSHI_CALENDAR_URL_FALLBACKS = [
    u.strip()
    for u in os.getenv(
        "CRYPTO_PULSE_JINSHI_URLS",
        "https://cdn-rili.jin10.com/data.json,https://rili.jin10.com/index.php",
    ).split(",")
    if u.strip()
]

# Fetcher
FETCH_INTERVAL_SEC = int(os.getenv("CRYPTO_PULSE_FETCH_INTERVAL_SEC", "1800"))  # 默认 30 分钟
REQUEST_DELAY_SEC = float(os.getenv("CRYPTO_PULSE_REQUEST_DELAY_SEC", "0.8"))
HTTP_TIMEOUT_SEC = float(os.getenv("CRYPTO_PULSE_HTTP_TIMEOUT_SEC", "25"))
# HTTP/bapi 失败时：Selenium 连本机 Chrome --remote-debugging-port（默认 9222）打开平台页抓取
CDP_FALLBACK = os.getenv("CRYPTO_PULSE_CDP_FALLBACK", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CHROME_DEBUG_PORT = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
CDP_WAIT_SEC = float(os.getenv("CRYPTO_PULSE_CDP_WAIT_SEC", "4"))
BINANCE_SQUARE_TRENDING_URL = os.getenv(
    "CRYPTO_PULSE_BINANCE_SQUARE_URL",
    "https://www.binance.com/bapi/composite/v1/public/pgc/content/square/list",
)
BINANCE_SQUARE_HEADERS_JSON = os.getenv("CRYPTO_PULSE_BINANCE_HEADERS_JSON", "")
BITGET_SQUARE_URL = os.getenv(
    "CRYPTO_PULSE_BITGET_SQUARE_URL",
    "https://www.bitget.com/v1/spa/content/square/hot",
)
BITGET_INSIGHTS_URL = os.getenv(
    "CRYPTO_PULSE_BITGET_INSIGHTS_URL",
    "https://www.bitget.com/zh-CN/insights",
).strip()
BITGET_SQUARE_HEADERS_JSON = os.getenv("CRYPTO_PULSE_BITGET_HEADERS_JSON", "")
OKX_SQUARE_URL = os.getenv(
    "CRYPTO_PULSE_OKX_SQUARE_URL",
    "https://www.okx.com/priapi/v5/eco/community/feed/hot",
)
OKX_SQUARE_HEADERS_JSON = os.getenv("CRYPTO_PULSE_OKX_HEADERS_JSON", "")
USE_MOCK_FETCHER = os.getenv("CRYPTO_PULSE_USE_MOCK", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
# 启用源（逗号分隔）。默认含已验证可免费拉取的社区源 + 交易所广场
_DEFAULT_SOURCES = (
    "binance,bitget,reddit,tradingview,farcaster"
)
ENABLED_SOURCES = {
    s.strip().lower()
    for s in os.getenv("CRYPTO_PULSE_SOURCES", _DEFAULT_SOURCES).split(",")
    if s.strip()
}
# Reddit（PullPush 免费归档 API）
REDDIT_SUBREDDIT = os.getenv("CRYPTO_PULSE_REDDIT_SUBREDDIT", "CryptoCurrency").strip()
REDDIT_PULLPUSH_URL = os.getenv(
    "CRYPTO_PULSE_REDDIT_PULLPUSH_URL",
    "https://api.pullpush.io/reddit/search/submission/",
).strip()
# TradingView Ideas
TRADINGVIEW_IDEAS_URL = os.getenv(
    "CRYPTO_PULSE_TV_IDEAS_URL",
    "https://www.tradingview.com/markets/cryptocurrencies/ideas/",
).strip()
# CryptoPanic（需免费 developer token：https://cryptopanic.com/developers/api/）
CRYPTOPANIC_AUTH_TOKEN = os.getenv("CRYPTO_PULSE_CRYPTOPANIC_TOKEN", "").strip()
CRYPTOPANIC_API_URL = os.getenv(
    "CRYPTO_PULSE_CRYPTOPANIC_URL",
    "https://cryptopanic.com/api/developer/v2/posts/",
).strip()
# Farcaster / Warpcast
FARCASTER_HUB_URL = os.getenv(
    "CRYPTO_PULSE_FARCASTER_HUB",
    "https://hub.pinata.cloud",
).strip().rstrip("/")
FARCASTER_CHANNEL = os.getenv("CRYPTO_PULSE_FARCASTER_CHANNEL", "bitcoin").strip()

# AI
LLM_API_KEY = os.getenv("CRYPTO_PULSE_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
LLM_BASE_URL = os.getenv(
    "CRYPTO_PULSE_LLM_BASE_URL",
    os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
LLM_MODEL = os.getenv("CRYPTO_PULSE_LLM_MODEL", "gpt-4o-mini")
AI_ENABLED = os.getenv("CRYPTO_PULSE_AI_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# API
WEB_HOST = os.getenv("CRYPTO_PULSE_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("CRYPTO_PULSE_PORT", "8770"))
API_CACHE_TTL_SEC = int(os.getenv("CRYPTO_PULSE_API_CACHE_TTL_SEC", "60"))
POSTS_MAX_KEEP = int(os.getenv("CRYPTO_PULSE_POSTS_MAX_KEEP", "2000"))

# 广场影响力门槛：点赞 / 评论（默认取「有影响力」帖）
SQUARE_MIN_LIKES = int(os.getenv("CRYPTO_PULSE_SQUARE_MIN_LIKES", "200"))
SQUARE_MIN_COMMENTS = int(os.getenv("CRYPTO_PULSE_SQUARE_MIN_COMMENTS", "30"))
# boards/posts 默认只展示过门槛的帖；0=关闭门槛
SQUARE_INFLUENTIAL_ONLY = os.getenv(
    "CRYPTO_PULSE_SQUARE_INFLUENTIAL_ONLY", "1"
).strip().lower() in ("1", "true", "yes")
# TradingView boost/agree 量级更小，单独门槛
TV_MIN_AGREES = int(os.getenv("CRYPTO_PULSE_TV_MIN_AGREES", "30"))
TV_MIN_COMMENTS = int(os.getenv("CRYPTO_PULSE_TV_MIN_COMMENTS", "10"))


# Proxy (与仓库其它模块一致)
def proxy_url() -> str | None:
    for key in (
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        v = (os.getenv(key) or "").strip()
        if v:
            return v
    return None
