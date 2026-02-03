"""
配置文件 - 第1部分：导入和基础配置
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Gemini API配置
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-exp')

# TradingView配置
TRADINGVIEW_URL = os.getenv('TRADINGVIEW_URL', 'https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT')
TRADINGVIEW_CHART_SELECTOR = os.getenv('TRADINGVIEW_SELECTOR', '#chart-container')

# 第2部分：时间周期配置
TIME_PERIODS = ['15m', '30m', '1h', '2h']  # 需要截图的4个周期
SCREENSHOT_DIR = os.getenv('SCREENSHOT_DIR', './screenshots')
SCREENSHOT_WIDTH = int(os.getenv('SCREENSHOT_WIDTH', '1920'))
SCREENSHOT_HEIGHT = int(os.getenv('SCREENSHOT_HEIGHT', '1080'))

# 第3部分：通知配置
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# 定时任务配置
RUN_INTERVAL_MINUTES = int(os.getenv('RUN_INTERVAL_MINUTES', '15'))
