"""
浏览器自动化模块 - 第1部分：导入和初始化
"""
from playwright.sync_api import sync_playwright, Page, Browser
import os
import time
from config import (
    TRADINGVIEW_URL, 
    TIME_PERIODS, 
    SCREENSHOT_DIR,
    SCREENSHOT_WIDTH,
    SCREENSHOT_HEIGHT
)

def init_browser():
    """初始化浏览器"""
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': SCREENSHOT_WIDTH, 'height': SCREENSHOT_HEIGHT}
        )
        page = context.new_page()
        return playwright, browser, page
    except Exception as e:
        error_msg = str(e)
        if "Executable doesn't exist" in error_msg or "BrowserType.launch" in error_msg:
            print("\n" + "="*60)
            print("❌ 错误：Playwright浏览器未安装！")
            print("="*60)
            print("\n【自动安装】运行以下命令：")
            print("  cd /Users/mac/frontend/code/1.operations/auto-deal-eth")
            print("  source venv/bin/activate")
            print("  playwright install chromium")
            print("\n【手动下载】如果网络问题，可以手动下载：")
            print("  下载地址: https://cdn.playwright.dev/chrome-for-testing-public/145.0.7632.6/mac-x64/chrome-headless-shell-mac-x64.zip")
            print("  解压到: ~/Library/Caches/ms-playwright/chromium_headless_shell-1208/")
            print("\n【使用代理】如果使用代理：")
            print("  export HTTP_PROXY=http://your-proxy:port")
            print("  export HTTPS_PROXY=http://your-proxy:port")
            print("  playwright install chromium")
            print("\n" + "="*60 + "\n")
        raise

# 第2部分：切换周期和截图功能
def switch_timeframe(page: Page, timeframe: str):
    """切换TradingView的时间周期"""
    try:
        # 方法1: 通过URL参数切换
        url_with_timeframe = f"{TRADINGVIEW_URL}&interval={timeframe}"
        page.goto(url_with_timeframe, wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)  # 等待图表加载
        
        # 方法2: 如果URL参数不行，尝试点击周期按钮
        # 这里可以根据实际页面结构调整选择器
        timeframe_selectors = {
            '15m': 'button[data-name="periods"]',
            '30m': 'button[data-name="periods"]',
            '1h': 'button[data-name="periods"]',
            '2h': 'button[data-name="periods"]'
        }
        return True
    except Exception as e:
        print(f"切换周期失败 {timeframe}: {e}")
        return False

# 第3部分：截图和批量处理
def take_screenshot(page: Page, timeframe: str) -> str:
    """截取K线图并保存"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    screenshot_path = os.path.join(SCREENSHOT_DIR, f'chart_{timeframe}.png')
    
    try:
        # 等待图表完全加载
        page.wait_for_selector('#chart-container', timeout=10000)
        time.sleep(2)  # 额外等待确保图表渲染完成
        
        # 截图整个页面或指定区域
        page.screenshot(path=screenshot_path, full_page=False)
        return screenshot_path
    except Exception as e:
        print(f"截图失败 {timeframe}: {e}")
        return None

def capture_all_timeframes():
    """批量截图所有周期"""
    playwright, browser, page = init_browser()
    screenshot_paths = {}
    
    try:
        # 先打开TradingView（增加重试机制）
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"正在访问TradingView... (尝试 {attempt + 1}/{max_retries})")
                page.goto(TRADINGVIEW_URL, wait_until='domcontentloaded', timeout=30000)
                time.sleep(5)  # 等待页面完全加载
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"❌ 访问TradingView失败: {e}")
                    raise
                print(f"⚠️ 访问失败，3秒后重试... ({e})")
                time.sleep(3)
        
        # 遍历所有周期进行截图
        for timeframe in TIME_PERIODS:
            print(f"正在处理周期: {timeframe}")
            if switch_timeframe(page, timeframe):
                screenshot_path = take_screenshot(page, timeframe)
                if screenshot_path:
                    screenshot_paths[timeframe] = screenshot_path
                time.sleep(2)  # 间隔等待
        
        return screenshot_paths
    finally:
        browser.close()
        playwright.stop()
    
    return screenshot_paths
