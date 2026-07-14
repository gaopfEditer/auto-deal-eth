"""OI Monitor 配置项。"""
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

# 币安 U 本位永续 REST
FAPI_BASE_URL = os.getenv("OI_FAPI_BASE_URL", "https://fapi.binance.com").rstrip("/")
# 币安现货 REST（主力现货流向）
SPOT_BASE_URL = os.getenv("OI_SPOT_BASE_URL", "https://api.binance.com").rstrip("/")

# 候选池：fapi 全市场 ticker/24hr 聚合 + OI 量级分层
OI_TIER_MID_MIN_USD = float(os.getenv("OI_TIER_MID_MIN_USD", "10000000"))
OI_TIER_HEAVY_MIN_USD = float(os.getenv("OI_TIER_HEAVY_MIN_USD", "50000000"))
OI_OI_BATCH_CONCURRENCY = int(os.getenv("OI_OI_BATCH_CONCURRENCY", "40"))
# 兼容旧配置：0 表示不限制，监控所有符合量级条件的合约
TOP_N = int(os.getenv("OI_TOP_N", "0"))

# 异动阈值
OI_USD_LIMIT = float(os.getenv("OI_USD_LIMIT", "1500000"))
OI_PCT_LIMIT = float(os.getenv("OI_PCT_LIMIT", "5.0"))

# 网络限频：每次请求后休眠秒数
REQUEST_INTERVAL_SEC = float(os.getenv("OI_REQUEST_INTERVAL_SEC", "0.1"))

# HTTP 超时（ticker/24hr 体量大，国内走代理时建议 ≥30）
HTTP_TIMEOUT_SEC = float(os.getenv("OI_HTTP_TIMEOUT_SEC", "30"))

# 扫描周期（秒）
SCAN_INTERVAL_SEC = int(os.getenv("OI_SCAN_INTERVAL_SEC", "60"))

# HTTP 重试
MAX_RETRIES = int(os.getenv("OI_MAX_RETRIES", "3"))
RETRY_BACKOFF_SEC = float(os.getenv("OI_RETRY_BACKOFF_SEC", "1.0"))
RATE_LIMIT_COOLDOWN_SEC = float(os.getenv("OI_RATE_LIMIT_COOLDOWN_SEC", "10.0"))

# Web 服务
WEB_HOST = os.getenv("OI_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("OI_WEB_PORT", "8765"))

# 双周期轮询（秒）
POLL_5M_SEC = int(os.getenv("OI_POLL_5M_SEC", "300"))
POLL_15M_SEC = int(os.getenv("OI_POLL_15M_SEC", "900"))
ALERT_COOLDOWN_SEC = int(os.getenv("OI_ALERT_COOLDOWN_SEC", "900"))

# OI 分钟级快照缓存长度（支持 1d 窗口差分）
OI_CACHE_MAXLEN = int(os.getenv("OI_CACHE_MAXLEN", "1440"))
MATRIX_TOP_N = int(os.getenv("OI_MATRIX_TOP_N", "7"))
MATRIX_REFRESH_SEC = int(os.getenv("OI_MATRIX_REFRESH_SEC", "60"))
OI_ZSCORE_HISTORY_LEN = int(os.getenv("OI_ZSCORE_HISTORY_LEN", "288"))
OI_ZSCORE_THRESHOLD = float(os.getenv("OI_ZSCORE_THRESHOLD", "3.0"))
OI_ZSCORE_MIN_SAMPLES = int(os.getenv("OI_ZSCORE_MIN_SAMPLES", "5"))
OI_5M_RECORD_INTERVAL_SEC = int(os.getenv("OI_5M_RECORD_INTERVAL_SEC", "300"))

# 榜单突破检测（5m K 线）
BREAKOUT_LOOKBACK = int(os.getenv("OI_BREAKOUT_LOOKBACK", "50"))
BREAKOUT_KLINE_LIMIT = BREAKOUT_LOOKBACK + 2
BREAKOUT_VOL_MULT = float(os.getenv("OI_BREAKOUT_VOL_MULT", "2.5"))
BREAKOUT_BODY_RATIO = float(os.getenv("OI_BREAKOUT_BODY_RATIO", "0.65"))
PULLBACK_VOL_SHRINK_RATIO = float(os.getenv("OI_PULLBACK_VOL_SHRINK", "0.6"))
PULLBACK_TOUCH_TOLERANCE = float(os.getenv("OI_PULLBACK_TOUCH_TOL", "0.003"))
BREAKOUT_WATCH_MAX_SEC = int(os.getenv("OI_BREAKOUT_WATCH_MAX_SEC", "7200"))
BREAKOUT_MATRIX_TF = os.getenv("OI_BREAKOUT_MATRIX_TF", "15m")
BREAKOUT_STATE_DB = _PKG_ROOT / "data" / "breakout_state.db"

# 形态追踪（15m K 线，LH → HL → 多头爆发）
PATTERN_KLINE_INTERVAL = os.getenv("OI_PATTERN_INTERVAL", "15m")
PATTERN_KLINE_LIMIT = int(os.getenv("OI_PATTERN_KLINE_LIMIT", "120"))
PATTERN_BB_LENGTH = int(os.getenv("OI_PATTERN_BB_LENGTH", "20"))
PATTERN_BB_MULT = float(os.getenv("OI_PATTERN_BB_MULT", "2.0"))
PATTERN_PIVOT_WINDOW = int(os.getenv("OI_PATTERN_PIVOT_WINDOW", "11"))
PATTERN_WICK_RATIO = float(os.getenv("OI_PATTERN_WICK_RATIO", "0.3"))
PATTERN_STAGE2_VOL_MULT = float(os.getenv("OI_PATTERN_STAGE2_VOL_MULT", "1.5"))
PATTERN_WATCH_MAX_SEC = int(os.getenv("OI_PATTERN_WATCH_MAX_SEC", "14400"))
PATTERN_AUTO_PICK_COUNT = int(os.getenv("OI_PATTERN_AUTO_PICK", "20"))
PATTERN_STATE_DB = _PKG_ROOT / "data" / "pattern_state.db"
PATTERN_CHART_DEFAULT_LIMIT = int(os.getenv("OI_PATTERN_CHART_LIMIT", "500"))
PATTERN_CHART_MAX_LIMIT = int(os.getenv("OI_PATTERN_CHART_MAX_LIMIT", "1500"))
PATTERN_CHART_LOAD_CHUNK = int(os.getenv("OI_PATTERN_CHART_LOAD_CHUNK", "300"))
PATTERN_CHART_INTERVALS = tuple(
    x.strip()
    for x in os.getenv("OI_PATTERN_CHART_INTERVALS", "5m,15m,30m,1h,4h,1d").split(",")
    if x.strip()
)

# 回踩 / Vegas / 射击之星策略（WS 本地监控 + 回测）
STRATEGY_KLINE_INTERVAL = os.getenv("OI_STRATEGY_INTERVAL", "1h")
STRATEGY_KLINE_LIMIT = int(os.getenv("OI_STRATEGY_KLINE_LIMIT", "200"))
STRATEGY_VEGAS_PERIODS = tuple(
    int(x.strip())
    for x in os.getenv("OI_STRATEGY_VEGAS_PERIODS", "144,169,576,676").split(",")
    if x.strip()
)
STRATEGY_PULLBACK_TOL = float(os.getenv("OI_STRATEGY_PULLBACK_TOL", "0.005"))
STRATEGY_PULLBACK_VOL_SHRINK = float(os.getenv("OI_STRATEGY_PULLBACK_VOL_SHRINK", "0.6"))
STRATEGY_SHOOT_WICK_RATIO = float(os.getenv("OI_STRATEGY_SHOOT_WICK_RATIO", "1.5"))
STRATEGY_SHOOT_WICK_MAX_RATIO = float(os.getenv("OI_STRATEGY_SHOOT_WICK_MAX_RATIO", "20.0"))
STRATEGY_OI_MIN_CHANGE_PCT = float(os.getenv("OI_STRATEGY_OI_MIN_CHANGE_PCT", "-2.0"))
STRATEGY_WATCH_MAX_SEC = int(os.getenv("OI_STRATEGY_WATCH_MAX_SEC", "86400"))
STRATEGY_STATE_DB = _PKG_ROOT / "data" / "pullback_state.db"
FSTREAM_WS_BASE = os.getenv("OI_FSTREAM_WS", "wss://fstream.binance.com")
STRATEGY_DEFAULT_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv(
        "OI_STRATEGY_SYMBOLS",
        "BTCUSDT,ETHUSDT,SOLUSDT,ORDIUSDT",
    ).split(",")
    if s.strip()
]


def proxy_url() -> str | None:
    """读取代理，与仓库 volumn 模块一致。"""
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
