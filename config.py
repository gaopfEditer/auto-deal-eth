"""
配置文件 - 第1部分：导入和基础配置
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False

_REPO_ROOT = Path(__file__).resolve().parent

# 加载环境变量（固定项目根 .env，不依赖 cwd）
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

# Gemini（仅 getinfo/weight 等旧模块仍可读 GEMINI_API_KEY；主流程图分析已改用本地 Ollama chat-image）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_REQUEST_TIMEOUT = int(os.getenv("GEMINI_REQUEST_TIMEOUT", "45"))

# 本地图分析 API：curl 示例
# curl -s http://127.0.0.1:8000/ollama/chat-image -H 'Content-Type: application/json' \
#   -d '{"role":"binance_k_line","prompt":"根据这张图判断趋势","image_path":"/abs/path.png"}'
OLLAMA_CHAT_IMAGE_URL = os.getenv(
    "OLLAMA_CHAT_IMAGE_URL", "http://127.0.0.1:8000/ollama/chat-image"
).strip()
OLLAMA_CHAT_IMAGE_ROLE = os.getenv("OLLAMA_CHAT_IMAGE_ROLE", "binance_k_line").strip()
OLLAMA_CHAT_IMAGE_PROMPT = os.getenv(
    "OLLAMA_CHAT_IMAGE_PROMPT", "根据这张图判断趋势"
).strip()
OLLAMA_CHAT_IMAGE_TIMEOUT = int(os.getenv("OLLAMA_CHAT_IMAGE_TIMEOUT", "120"))
# 榜单逐币 K 线截图分析（gainers_top20）：POST /ollama/chat + promat
# curl -sS -X POST 'http://127.0.0.1:8000/ollama/chat' -H 'Content-Type: application/json' \
#   -d '{"promat":"tv_k_line_hot","image_path":"/tmp/img.png"}'
OLLAMA_CHAT_URL = os.getenv(
    "OLLAMA_CHAT_URL", "http://127.0.0.1:8000/ollama/chat"
).strip()
OLLAMA_RANKS_CHART_PROMAT = os.getenv(
    "OLLAMA_RANKS_CHART_PROMAT", "tv_k_line_hot"
).strip()
# 可选：纯文本 JSON 分类接口（帖子多空），未配置则 classify_square_post_direction 返回 None
OLLAMA_CLASSIFY_CHAT_URL = os.getenv("OLLAMA_CLASSIFY_CHAT_URL", "").strip()

# 代理：不自动设置，避免 Gemini 被不稳定代理影响。需要时手动: source set_proxy_7890.sh

# 目标页面配置
# 默认切换到 TradingView 的 ETHUSDT 1h 页面
# interval=60 表示 1 小时周期
TARGET_URL = os.getenv('TARGET_URL', 'https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT&interval=60')
TARGET_PAGE_SELECTOR = os.getenv('TARGET_PAGE_SELECTOR', 'body')  # 默认截图整个页面

# 币种配置
# 支持的币种列表，格式: ["ETH", "BTC", "SOL"] 等
# 默认只监控 ETH
# 可以通过环境变量 SYMBOLS 配置，用逗号分隔，如: SYMBOLS=ETH,BTC,SOL
SYMBOLS = os.getenv('SYMBOLS', 'ETH').split(',')
# 清理并转换为大写
SYMBOLS = [s.strip().upper() for s in SYMBOLS if s.strip()]
# 如果为空，使用默认值
if not SYMBOLS:
    SYMBOLS = ['ETH']

# 第2部分：时间周期配置
TIME_PERIODS = ['15m', '30m', '1h', '2h']  # 需要截图的4个周期
_DEFAULT_SCREENSHOT_DIR = '/Volumes/RamDisk/app_screenshots'
SCREENSHOT_DIR = os.getenv('SCREENSHOT_DIR', _DEFAULT_SCREENSHOT_DIR).strip() or _DEFAULT_SCREENSHOT_DIR
SCREENSHOT_WIDTH = int(os.getenv('SCREENSHOT_WIDTH', '1920'))
SCREENSHOT_HEIGHT = int(os.getenv('SCREENSHOT_HEIGHT', '1080'))

# 第3部分：通知配置
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
# 流动性/涨幅榜推送群（gainers_top20）；与 TradingView 信号群 TELEGRAM_CHAT_ID 分离
TELEGRAM_MARKET_RANKS_CHAT_ID = os.getenv(
    'TELEGRAM_MARKET_RANKS_CHAT_ID', '-5218901932'
).strip()
# 流动性/涨幅榜 JSON 缓存有效期（小时），默认 4h 内不重复抓取
BINANCE_MARKET_RANKS_CACHE_HOURS = float(
    os.getenv('BINANCE_MARKET_RANKS_CACHE_HOURS', '4') or '4'
)
# gainers_top20 逐币截图+AI 时排除的 base 资产（逗号分隔）
BINANCE_RANKS_EXCLUDE_BASES = os.getenv(
    'BINANCE_RANKS_EXCLUDE_BASES',
    'eth,btc,usdt,usdc,usd1,sui,sol,bnb',
).strip()
# 榜单逐币 K 线截图周期
# gainers_top20 逐币 TradingView 截图周期（15m / 1h / 4h 等，见 dealMsg period_to_tradingview_interval）
BINANCE_RANKS_CHART_PERIOD = os.getenv('BINANCE_RANKS_CHART_PERIOD', '15m').strip() or '15m'

# Chrome浏览器配置
# 使用远程调试模式连接到已运行的Chrome（推荐，最安全）
# 设置为 True 时，会连接到已经打开的Chrome浏览器（需要先手动启动Chrome并启用远程调试）
# 设置为 False 时，会直接启动浏览器（需要确保 Chrome 完全关闭，否则可能触发保护机制）
# 默认使用 True，避免触发 Chrome 的保护机制导致账号数据丢失
USE_REMOTE_DEBUGGING = os.getenv('USE_REMOTE_DEBUGGING', 'True').lower() == 'true'
# 远程调试端口（默认9222）
CHROME_DEBUG_PORT = int(os.getenv('CHROME_DEBUG_PORT', '9222'))
# 是否使用无头模式（headless），使用远程调试时此选项无效
CHROME_HEADLESS = os.getenv('CHROME_HEADLESS', 'False').lower() == 'true'

# Chrome用户配置文件配置（仅在非远程调试模式下使用）
# Chrome用户数据目录（完整路径，包含 User Data）
# Windows 默认路径: C:\Users\你的用户名\AppData\Local\Google\Chrome\User Data
# 可以通过环境变量 CHROME_USER_DATA_DIR 配置
# 如果留空，程序会自动使用默认路径
CHROME_USER_DATA_DIR = os.getenv('CHROME_USER_DATA_DIR', '')
# Chrome配置文件名称（如 Profile 1, Profile 2, Default）
# 如果留空，则使用默认配置文件或无痕模式
# 可以通过环境变量 CHROME_PROFILE_NAME 配置，默认使用 Profile 1
CHROME_PROFILE_NAME = os.getenv('CHROME_PROFILE_NAME', 'Profile 1')

# 定时任务配置
# 执行时间区间列表，格式: ["1:00-3:00", "20:00-22:00"]
# 支持跨天时间段，如 ["22:00-2:00"]
# 留空或空列表表示全天执行
# 可以通过环境变量 TIME_RANGES 配置，用逗号分隔，如: TIME_RANGES=1:00-3:00,20:00-22:00
TIME_RANGES = os.getenv('TIME_RANGES', '').split(',') if os.getenv('TIME_RANGES', '') else []
# 清理空字符串
TIME_RANGES = [tr.strip() for tr in TIME_RANGES if tr.strip()]
# 如果环境变量未设置，使用默认值（空列表表示全天）
if not TIME_RANGES:
    TIME_RANGES = []

# 执行间隔（分钟），在时间区间内按照此间隔执行
# 默认 15 分钟，可以通过环境变量 RUN_INTERVAL_MINUTES 配置
RUN_INTERVAL_MINUTES = int(os.getenv('RUN_INTERVAL_MINUTES', '15'))

# 板块数据配置
# 需要分析的板块/指数列表，格式: ["000300", "中证消费"] 等
# 可以通过环境变量 SECTORS 配置，用逗号分隔，如: SECTORS=000300,000016,中证消费
# 板块类型会自动识别：纯数字代码为指数，中文名称为板块
SECTORS = os.getenv('SECTORS', '').split(',') if os.getenv('SECTORS', '') else []
# 清理空字符串
SECTORS = [s.strip() for s in SECTORS if s.strip()]

# 板块分析时间周期（默认获取所有周期）
SECTOR_ANALYSIS_PERIODS = os.getenv('SECTOR_ANALYSIS_PERIODS', '1m,3m,6m,1y,3y,5y').split(',')
SECTOR_ANALYSIS_PERIODS = [p.strip() for p in SECTOR_ANALYSIS_PERIODS if p.strip()]
if not SECTOR_ANALYSIS_PERIODS:
    SECTOR_ANALYSIS_PERIODS = ['1m', '3m', '6m', '1y', '3y', '5y']

# Square 关注流帖子状态：按发帖时间保留的小时数（binance.posts_state / binance.market_lists_selenium）
# 可通过环境变量 POST_RETENTION_HOURS 覆盖，例如 POST_RETENTION_HOURS=48
POST_RETENTION_HOURS = int(os.getenv('POST_RETENTION_HOURS', '24').strip() or '24')

# 帖子交易信号分析（binance_posts_state）：与下列 YAML 等价
# promat_analysis:
#   ollama:
#     enabled: true
#     base_url: "http://localhost:11434"
#     model: "gemma-uncensored"
# 优先走 Ollama POST {base_url}/api/generate；不可用或失败时回退 LOCAL_CHAT（见 binance_posts_state）
_PROMAT_DEFAULT_PROMPT = _REPO_ROOT / "prompts" / "binance_market_lists_selenium.txt"
PROMAT_ANALYSIS = {
    "ollama": {
        "enabled": os.getenv("PROMAT_ANALYSIS_OLLAMA_ENABLED", "true").strip().lower()
        == "true",
        "base_url": os.getenv(
            "PROMAT_ANALYSIS_OLLAMA_BASE_URL", "http://localhost:11434"
        ).rstrip("/"),
        "model": (
            os.getenv("PROMAT_ANALYSIS_OLLAMA_MODEL", "gemma-uncensored").strip()
            or "gemma-uncensored"
        ),
        "timeout_sec": int(
            os.getenv("PROMAT_ANALYSIS_OLLAMA_TIMEOUT_SEC", "120").strip() or "120"
        ),
    },
    "prompt_path": os.getenv(
        "PROMAT_ANALYSIS_PROMPT_PATH", str(_PROMAT_DEFAULT_PROMPT)
    ).strip()
    or str(_PROMAT_DEFAULT_PROMPT),
}

# publish/signal 润色（style_tianya_classic + strategy_left_ambush），见 prompts/promat/
_PROMAT_PUBLISH_DIR = _REPO_ROOT / "prompts" / "promat"
PROMAT_PUBLISH = {
    "dir": os.getenv("PROMAT_PUBLISH_DIR", str(_PROMAT_PUBLISH_DIR)).strip()
    or str(_PROMAT_PUBLISH_DIR),
    "style_path": str(_PROMAT_PUBLISH_DIR / "style_tianya_classic.txt"),
    "strategy_path": str(_PROMAT_PUBLISH_DIR / "strategy_left_ambush.txt"),
    "compose_path": str(_PROMAT_PUBLISH_DIR / "tv_signal_compose.txt"),
}

# 数据库配置
# 生产环境应从 .env.local 读取，这里提供默认值
DB_HOST = os.getenv('DB_HOST', '60.205.120.196')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'b01c044f2e0bf36e')
DB_NAME = os.getenv('DB_NAME', 'nextjs_jwt')
