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
# 备选所公共 REST（币安 418 / 失败时按顺序轮询）
BYBIT_BASE_URL = os.getenv("OI_BYBIT_BASE_URL", "https://api.bybit.com").rstrip("/")
OKX_BASE_URL = os.getenv("OI_OKX_BASE_URL", "https://www.okx.com").rstrip("/")
BITGET_BASE_URL = os.getenv("OI_BITGET_BASE_URL", "https://api.bitget.com").rstrip("/")
GATE_BASE_URL = os.getenv("OI_GATE_BASE_URL", "https://api.gateio.ws").rstrip("/")
FALLBACK_SOURCE_ORDER = tuple(
    x.strip().lower()
    for x in os.getenv("OI_FALLBACK_SOURCES", "bybit,okx,bitget,gate").split(",")
    if x.strip()
)
FALLBACK_MIN_TICKERS = int(os.getenv("OI_FALLBACK_MIN_TICKERS", "30"))
# 币安 418 / 硬封后，多久内优先走备选所（秒）
BINANCE_BAN_COOLDOWN_SEC = float(os.getenv("OI_BINANCE_BAN_COOLDOWN_SEC", "300"))

# 候选池：fapi 全市场 ticker/24hr 聚合 + OI 量级分层
OI_TIER_MID_MIN_USD = float(os.getenv("OI_TIER_MID_MIN_USD", "10000000"))
OI_TIER_HEAVY_MIN_USD = float(os.getenv("OI_TIER_HEAVY_MIN_USD", "50000000"))
OI_OI_BATCH_CONCURRENCY = int(os.getenv("OI_OI_BATCH_CONCURRENCY", "20"))
# 兼容旧配置：0 表示不限制，监控所有符合量级条件的合约
TOP_N = int(os.getenv("OI_TOP_N", "0"))

# 异动阈值
OI_USD_LIMIT = float(os.getenv("OI_USD_LIMIT", "1500000"))
OI_PCT_LIMIT = float(os.getenv("OI_PCT_LIMIT", "5.0"))
# 单窗口 OI 变动上限：超过视为口径跳变（备选所单位切换 / 脏样本），丢弃差分并重置缓存
OI_DELTA_MAX_PCT = float(os.getenv("OI_DELTA_MAX_PCT", "150"))

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
# 形态 watchlist：每隔 N 秒用合约流入榜 + OI 爆发榜刷新（未进场币可替换）
PATTERN_WATCHLIST_REFRESH_SEC = int(os.getenv("OI_PATTERN_WATCHLIST_REFRESH_SEC", "7200"))
PATTERN_WATCHLIST_REFRESH_TF = os.getenv("OI_PATTERN_WATCHLIST_REFRESH_TF", "15m").strip() or "15m"
# 手动置顶维持时长（秒），到期自动取消；也可手动取消
PATTERN_PIN_TTL_SEC = int(os.getenv("OI_PATTERN_PIN_TTL_SEC", "86400"))
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
STRATEGY_VEGAS_FILTER = int(os.getenv("OI_STRATEGY_VEGAS_FILTER", "12"))
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

# 沙盒纸面交易（逻辑 A/B/C/D · 每日随机 N 币）
SANDBOX_ENABLED = os.getenv("OI_SANDBOX_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
SANDBOX_DAILY_COUNT = int(os.getenv("OI_SANDBOX_DAILY_COUNT", "12"))
# 执行周期：默认 15m + 1h 同等扫描（OI_SANDBOX_INTERVALS=15m 可只跑单周期）
SANDBOX_INTERVALS: tuple[str, ...] = tuple(
    s.strip()
    for s in os.getenv("OI_SANDBOX_INTERVALS", "15m,1h").split(",")
    if s.strip()
) or ("15m", "1h")
# 兼容旧代码：主周期 = 列表首项
SANDBOX_INTERVAL = SANDBOX_INTERVALS[0]
SANDBOX_KLINE_LIMIT = int(os.getenv("OI_SANDBOX_KLINE_LIMIT", "200"))
# 1h/更高周期至少拉够 Vegas 慢速通道（EMA676）
SANDBOX_KLINE_LIMIT_1H = int(os.getenv("OI_SANDBOX_KLINE_LIMIT_1H", "720"))
# 策略参考周期（展示/记录用；信号执行周期为仓位自己的 interval）
SANDBOX_REF_INTERVALS_HUNTER = tuple(
    s.strip()
    for s in os.getenv("OI_SANDBOX_REF_INTERVALS_HUNTER", "15m").split(",")
    if s.strip()
)
SANDBOX_REF_INTERVALS_TREND = tuple(
    s.strip()
    for s in os.getenv("OI_SANDBOX_REF_INTERVALS_TREND", "15m,1h,4h,1d").split(",")
    if s.strip()
)
# 单笔保证金（U）；名义仓位 = 保证金 × 杠杆
SANDBOX_NOTIONAL_USD = float(os.getenv("OI_SANDBOX_NOTIONAL_USD", "1"))
SANDBOX_INITIAL_BALANCE = float(os.getenv("OI_SANDBOX_INITIAL_BALANCE", "1000"))
# 最大同时持仓币数
SANDBOX_MAX_CONCURRENT = int(os.getenv("OI_SANDBOX_MAX_CONCURRENT", "10"))
# —— 短线猎手 S ——
SANDBOX_HUNTER_SL_PAD = float(os.getenv("OI_SANDBOX_HUNTER_SL_PAD", "0.001"))  # 0.1%
SANDBOX_HUNTER_ATR_MULT = float(os.getenv("OI_SANDBOX_HUNTER_ATR_MULT", "2"))
# —— 长线维加斯 T（价变阈值为设计基准；ROE≈价变%×杠杆）——
SANDBOX_TREND_SLOPE_MIN = float(os.getenv("OI_SANDBOX_TREND_SLOPE_MIN", "0.0003"))
SANDBOX_TREND_SL_PAD = float(os.getenv("OI_SANDBOX_TREND_SL_PAD", "0.002"))  # EMA169 外 0.2%
SANDBOX_TREND_BE_PRICE_PCT = float(os.getenv("OI_SANDBOX_TREND_BE_PRICE_PCT", "0.75"))
SANDBOX_TREND_PARTIAL_PRICE_PCT = float(
    os.getenv("OI_SANDBOX_TREND_PARTIAL_PRICE_PCT", "1.0")
)
SANDBOX_TREND_PARTIAL_FRAC = float(os.getenv("OI_SANDBOX_TREND_PARTIAL_FRAC", "0.30"))
SANDBOX_TREND_TRAIL_PCT = float(os.getenv("OI_SANDBOX_TREND_TRAIL_PCT", "1.0"))
# 阶梯上移止损：峰值价变每满 STEP_PROFIT% → SL 相对入场再锁定 STEP_SL_LIFT%
SANDBOX_STEP_TRAIL_PROFIT_PCT = float(
    os.getenv("OI_SANDBOX_STEP_TRAIL_PROFIT_PCT", "2.2")
)
SANDBOX_STEP_TRAIL_SL_LIFT_PCT = float(
    os.getenv("OI_SANDBOX_STEP_TRAIL_SL_LIFT_PCT", "1.0")
)
SANDBOX_BREAKEVEN_PCT = float(os.getenv("OI_SANDBOX_BREAKEVEN_PCT", "1.5"))
SANDBOX_HL_TRAIL_BUF = float(os.getenv("OI_SANDBOX_HL_TRAIL_BUF", "0.005"))
SANDBOX_BB_STOP_BUF = float(os.getenv("OI_SANDBOX_BB_STOP_BUF", "0.003"))
SANDBOX_RANGE_SLOPE_MAX = float(os.getenv("OI_SANDBOX_RANGE_SLOPE_MAX", "0.0015"))
# 主动平仓旧参数（兼容）；S/T 模块主要用上面阈值
SANDBOX_MIN_HOLD_BARS = int(os.getenv("OI_SANDBOX_MIN_HOLD_BARS", "2"))
SANDBOX_SOFT_EXIT_MIN_MOVE_PCT = float(
    os.getenv("OI_SANDBOX_SOFT_EXIT_MIN_MOVE_PCT", "0.25")
)
# 初始止损距离：2.5×ATR(14) 动态上限（取代旧 0.5%/1.5% 百分比硬裁剪）
SANDBOX_SL_ATR_MULT = float(os.getenv("OI_SANDBOX_SL_ATR_MULT", "2.5"))
# 以下百分比仅作兼容占位，入场裁剪已改走 ATR，不再使用
SANDBOX_SL_MAX_PCT_MAJOR = float(os.getenv("OI_SANDBOX_SL_MAX_PCT_MAJOR", "0.5"))
SANDBOX_SL_MAX_PCT_ALT = float(os.getenv("OI_SANDBOX_SL_MAX_PCT_ALT", "1.5"))
SANDBOX_MAJOR_SYMBOLS = tuple(
    s.strip().upper()
    for s in os.getenv("OI_SANDBOX_MAJOR_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if s.strip()
)
# 杠杆：BTC/ETH 100x，山寨 30x（SANDBOX_NOTIONAL_USD 为单笔保证金）
SANDBOX_LEVERAGE_MAJOR = float(os.getenv("OI_SANDBOX_LEVERAGE_MAJOR", "100"))
SANDBOX_LEVERAGE_ALT = float(os.getenv("OI_SANDBOX_LEVERAGE_ALT", "30"))
# 合约 taker 手续费（占名义本金的 %，单边；开+平各收一次，与回测 fee_pct 一致）
SANDBOX_FEE_PCT = float(os.getenv("OI_SANDBOX_FEE_PCT", "0.04"))
# 平仓后至少隔 N 根已收盘 K 才允许同币再入场（防反复触发）
SANDBOX_REENTRY_COOLDOWN_BARS = int(os.getenv("OI_SANDBOX_REENTRY_COOLDOWN_BARS", "8"))
SANDBOX_STATE_DB = _PKG_ROOT / "data" / "sandbox_state.db"

# —— 卡片信号 WebSocket（外部卡片系统推送 → 沙盒评估）——
CARD_WS_ENABLED = os.getenv("OI_CARD_WS_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CARD_WS_PATH = os.getenv("OI_CARD_WS_PATH", "/ws/cards").strip() or "/ws/cards"
# 限价近场：山寨小杠杆（约 20x/30x）默认 1%；主流高杠杆（约 100x）默认 0.2%
CARD_NEAR_ENTRY_PCT = float(os.getenv("OI_CARD_NEAR_ENTRY_PCT", "1.0"))
CARD_NEAR_ENTRY_PCT_MAJOR = float(os.getenv("OI_CARD_NEAR_ENTRY_PCT_MAJOR", "0.2"))
# 卡片杠杆 ≥ 该值视为「主流档」近场阈值（无币种信息时回退）
CARD_NEAR_ENTRY_MAJOR_LEV = float(os.getenv("OI_CARD_NEAR_ENTRY_MAJOR_LEV", "80"))
# 卡片仓位执行评估周期（触 TP/SL 用该周期已收盘 K 的高低点）
CARD_EVAL_INTERVAL = os.getenv("OI_CARD_EVAL_INTERVAL", "15m").strip() or "15m"
CARD_DEFAULT_LEVERAGE = float(os.getenv("OI_CARD_DEFAULT_LEVERAGE", "10"))


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
