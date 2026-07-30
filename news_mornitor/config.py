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

# 宏观日历（金十风格）：仅保留星级 ≥ N、未来 window 小时内
MACRO_MIN_STAR = int(os.getenv("CRYPTO_PULSE_MACRO_MIN_STAR", "3"))
MACRO_AHEAD_HOURS = int(os.getenv("CRYPTO_PULSE_MACRO_AHEAD_HOURS", "24"))
MACRO_REFRESH_SEC = int(os.getenv("CRYPTO_PULSE_MACRO_REFRESH_SEC", "600"))
JINSHI_CALENDAR_URL = os.getenv(
    "CRYPTO_PULSE_JINSHI_URL",
    "https://rili.jin10.com/index.php",
)

# Fetcher
FETCH_INTERVAL_SEC = int(os.getenv("CRYPTO_PULSE_FETCH_INTERVAL_SEC", "300"))
REQUEST_DELAY_SEC = float(os.getenv("CRYPTO_PULSE_REQUEST_DELAY_SEC", "0.8"))
HTTP_TIMEOUT_SEC = float(os.getenv("CRYPTO_PULSE_HTTP_TIMEOUT_SEC", "25"))
BINANCE_SQUARE_TRENDING_URL = os.getenv(
    "CRYPTO_PULSE_BINANCE_SQUARE_URL",
    "https://www.binance.com/bapi/composite/v1/public/pgc/content/square/list",
)
BINANCE_SQUARE_HEADERS_JSON = os.getenv("CRYPTO_PULSE_BINANCE_HEADERS_JSON", "")
BITGET_SQUARE_URL = os.getenv(
    "CRYPTO_PULSE_BITGET_SQUARE_URL",
    "https://www.bitget.com/v1/spa/content/square/hot",
)
BITGET_SQUARE_HEADERS_JSON = os.getenv("CRYPTO_PULSE_BITGET_HEADERS_JSON", "")
OKX_SQUARE_URL = os.getenv(
    "CRYPTO_PULSE_OKX_SQUARE_URL",
    "https://www.okx.com/priapi/v5/eco/community/feed/hot",
)
OKX_SQUARE_HEADERS_JSON = os.getenv("CRYPTO_PULSE_OKX_HEADERS_JSON", "")
USE_MOCK_FETCHER = os.getenv("CRYPTO_PULSE_USE_MOCK", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

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
