"""
配置文件 - 第1部分：导入和基础配置
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Gemini API配置
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyCp812BsFgInOxKsHBzlD01gt4lKgQxe88')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

# TradingView配置
TRADINGVIEW_BASE_URL = os.getenv('TRADINGVIEW_BASE_URL', 'https://www.tradingview.com/chart/?symbol=BINANCE:')
TRADINGVIEW_CHART_SELECTOR = os.getenv('TRADINGVIEW_SELECTOR', '#chart-container')

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
SCREENSHOT_DIR = os.getenv('SCREENSHOT_DIR', './screenshots')
SCREENSHOT_WIDTH = int(os.getenv('SCREENSHOT_WIDTH', '1920'))
SCREENSHOT_HEIGHT = int(os.getenv('SCREENSHOT_HEIGHT', '1080'))

# 第3部分：通知配置
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# Chrome浏览器配置
# 使用远程调试模式连接到已运行的Chrome（推荐）
# 设置为 True 时，会连接到已经打开的Chrome浏览器（需要先手动启动Chrome并启用远程调试）
# 设置为 False 时，会直接打开默认浏览器
USE_REMOTE_DEBUGGING = os.getenv('USE_REMOTE_DEBUGGING', 'False').lower() == 'true'
# 远程调试端口（默认9222）
CHROME_DEBUG_PORT = int(os.getenv('CHROME_DEBUG_PORT', '9222'))
# 是否使用无头模式（headless），使用远程调试时此选项无效
CHROME_HEADLESS = os.getenv('CHROME_HEADLESS', 'False').lower() == 'true'

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
