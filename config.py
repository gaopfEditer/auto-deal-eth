"""
配置文件 - 第1部分：导入和基础配置
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Gemini API配置
# 如果不需要 AI 分析，可以不配置 GEMINI_API_KEY，程序会自动跳过分析步骤
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

# TradingView配置（已注释，暂时不使用）
# TRADINGVIEW_BASE_URL = os.getenv('TRADINGVIEW_BASE_URL', 'https://www.tradingview.com/chart/?symbol=BINANCE:')
# TRADINGVIEW_CHART_SELECTOR = os.getenv('TRADINGVIEW_SELECTOR', '#chart-container')

# 目标页面配置
TARGET_URL = os.getenv('TARGET_URL', 'https://tophub.today/c/developer')
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
SCREENSHOT_DIR = os.getenv('SCREENSHOT_DIR', './screenshots')
SCREENSHOT_WIDTH = int(os.getenv('SCREENSHOT_WIDTH', '1920'))
SCREENSHOT_HEIGHT = int(os.getenv('SCREENSHOT_HEIGHT', '1080'))

# 第3部分：通知配置
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

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

# 数据库配置
# 生产环境应从 .env.local 读取，这里提供默认值
DB_HOST = os.getenv('DB_HOST', '60.205.120.196')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'b01c044f2e0bf36e')
DB_NAME = os.getenv('DB_NAME', 'nextjs_jwt')
