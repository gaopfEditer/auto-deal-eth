"""
浏览器自动化模块 - 第1部分：导入和初始化
"""
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
import os
import time
import platform
from config import (
    TRADINGVIEW_BASE_URL, 
    TIME_PERIODS, 
    SCREENSHOT_DIR,
    SCREENSHOT_WIDTH,
    SCREENSHOT_HEIGHT,
    USE_REMOTE_DEBUGGING,
    CHROME_DEBUG_PORT,
    CHROME_HEADLESS
)
from PIL import Image

def init_browser():
    """初始化浏览器"""
    try:
        # 如果使用远程调试模式，连接到已运行的Chrome
        if USE_REMOTE_DEBUGGING:
            print(f"[INFO] 使用远程调试模式，连接到已运行的Chrome（端口 {CHROME_DEBUG_PORT}）")
            print("[INFO] 请确保Chrome已启动并启用了远程调试")
            
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")
            
            # 使用 webdriver-manager 自动管理 ChromeDriver
            try:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception:
                # 如果 webdriver-manager 失败，尝试直接使用系统 ChromeDriver
                driver = webdriver.Chrome(options=chrome_options)
            
            print("[OK] 成功连接到已运行的Chrome浏览器")
            return driver
        
        # 否则，直接打开默认浏览器（完全使用系统默认配置，不读取任何用户配置文件）
        else:
            print("[INFO] 直接打开默认浏览器（使用系统默认配置）")
            chrome_options = Options()
            
            # 重要：不添加任何 --user-data-dir 参数，让 Chrome 使用系统默认配置
            # 这样会自动使用默认账号和设置，不会触发安全检测
            
            # 无头模式配置
            if CHROME_HEADLESS:
                chrome_options.add_argument('--headless')
                print("[INFO] 使用无头模式")
            else:
                print("[INFO] 使用有界面模式（可以看到浏览器窗口）")
            
            # 基本配置（不涉及用户数据）
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument(f'--window-size={SCREENSHOT_WIDTH},{SCREENSHOT_HEIGHT}')
            chrome_options.add_argument('--disable-gpu')
            # 禁用一些可能导致读取用户配置的选项
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins-discovery')
            
            # 使用 webdriver-manager 自动管理 ChromeDriver
            try:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception:
                # 如果 webdriver-manager 失败，尝试直接使用系统 ChromeDriver
                driver = webdriver.Chrome(options=chrome_options)
            
            driver.set_window_size(SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT)
            print("[OK] 浏览器已启动，使用系统默认配置")
            return driver
    except Exception as e:
        error_msg = str(e)
        if "chromedriver" in error_msg.lower() or "executable" in error_msg.lower():
            print("\n" + "="*60)
            print("[ERROR] 错误：ChromeDriver未安装或Chrome浏览器未找到！")
            print("="*60)
            print("\n【解决方案】")
            print("1. 确保已安装 Chrome 浏览器")
            print("2. 安装 ChromeDriver:")
            print("   - Windows: 下载 https://chromedriver.chromium.org/")
            print("   - 或使用: pip install webdriver-manager")
            print("3. 将 ChromeDriver 添加到系统 PATH")
            print("\n" + "="*60 + "\n")
        elif "connection refused" in error_msg.lower() or "cannot connect" in error_msg.lower():
            print("\n" + "="*60)
            print("[ERROR] 无法连接到Chrome远程调试端口！")
            print("="*60)
            print("\n【解决方法】")
            if USE_REMOTE_DEBUGGING:
                print("1. 确保Chrome已启动并启用了远程调试")
                print("2. 启动Chrome时添加参数：")
                if platform.system() == "Windows":
                    print(f'   "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={CHROME_DEBUG_PORT}')
                elif platform.system() == "Darwin":  # Mac
                    print(f'   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={CHROME_DEBUG_PORT}')
                print("3. 或者设置 USE_REMOTE_DEBUGGING=False 使用直接打开浏览器模式")
            else:
                print("1. Chrome可能未正确安装")
                print("2. 检查ChromeDriver是否正确安装")
            print("\n" + "="*60 + "\n")
        elif "crashed" in error_msg.lower() or "not reachable" in error_msg.lower():
            print("\n" + "="*60)
            print("[ERROR] Chrome启动失败！")
            print("="*60)
            print("\n【可能的原因】")
            print("1. Chrome浏览器正在运行，导致冲突")
            print("2. Chrome版本与ChromeDriver不匹配")
            print("3. 系统资源不足")
            print("\n【解决方法】")
            if not USE_REMOTE_DEBUGGING:
                print("1. 尝试关闭所有Chrome窗口后重新运行")
                print("2. 或者设置 USE_REMOTE_DEBUGGING=True 使用远程调试模式")
            print("\n" + "="*60 + "\n")
        raise

# 第2部分：切换币种和周期功能
def switch_symbol(driver, symbol: str):
    """切换TradingView的币种"""
    try:
        url = f"{TRADINGVIEW_BASE_URL}{symbol}USDT"
        driver.get(url)
        time.sleep(3)  # 等待页面加载
        print(f"[OK] 已切换到币种: {symbol}")
        return True
    except Exception as e:
        print(f"[ERROR] 切换币种失败 {symbol}: {e}")
        return False

def switch_timeframe(driver, timeframe: str):
    """切换TradingView的时间周期"""
    try:
        # 通过URL参数切换周期
        current_url = driver.current_url
        if 'interval=' in current_url:
            url_with_timeframe = current_url.split('&interval=')[0] + f'&interval={timeframe}'
        else:
            url_with_timeframe = current_url + f'&interval={timeframe}'
        driver.get(url_with_timeframe)
        time.sleep(3)  # 等待图表加载
        return True
    except Exception as e:
        print(f"[ERROR] 切换周期失败 {timeframe}: {e}")
        return False

# 第3部分：截图和批量处理
def take_screenshot(driver, symbol: str, timeframe: str) -> str:
    """截取K线图并保存"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    screenshot_path = os.path.join(SCREENSHOT_DIR, f'{symbol}_{timeframe}.png')
    
    try:
        # 等待图表完全加载
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, 'chart-container'))
            )
        except TimeoutException:
            # 如果找不到 chart-container，尝试其他选择器
            pass
        
        time.sleep(2)  # 额外等待确保图表渲染完成
        
        # 截图整个页面
        driver.save_screenshot(screenshot_path)
        return screenshot_path
    except Exception as e:
        print(f"[ERROR] 截图失败 {symbol} {timeframe}: {e}")
        return None

def combine_images(image_paths: dict, symbol: str) -> str:
    """将4个周期的图片组合成一张图片（2x2布局）"""
    try:
        images = []
        for timeframe in TIME_PERIODS:
            if timeframe in image_paths and image_paths[timeframe]:
                img = Image.open(image_paths[timeframe])
                images.append((img, timeframe))
        
        if len(images) != 4:
            print(f"[WARNING] 图片数量不足4张，无法组合")
            return None
        
        # 计算组合图片的尺寸（2x2布局）
        # 假设每张图片尺寸相同
        img_width, img_height = images[0][0].size
        combined_width = img_width * 2
        combined_height = img_height * 2
        
        # 创建组合图片
        combined_image = Image.new('RGB', (combined_width, combined_height), 'white')
        
        # 布局：左上(15m), 右上(30m), 左下(1h), 右下(2h)
        positions = [
            (0, 0),           # 15m - 左上
            (img_width, 0),   # 30m - 右上
            (0, img_height),  # 1h - 左下
            (img_width, img_height)  # 2h - 右下
        ]
        
        for idx, (img, timeframe) in enumerate(images):
            combined_image.paste(img, positions[idx])
        
        # 保存组合图片
        combined_path = os.path.join(SCREENSHOT_DIR, f'{symbol}_combined.png')
        combined_image.save(combined_path)
        print(f"[OK] 组合图片已保存: {combined_path}")
        return combined_path
    except Exception as e:
        print(f"[ERROR] 组合图片失败: {e}")
        return None

def capture_all_timeframes_for_symbol(symbol: str):
    """为指定币种批量截图所有周期，并组合成一张图片"""
    driver = init_browser()
    screenshot_paths = {}
    
    try:
        # 切换到指定币种
        if not switch_symbol(driver, symbol):
            return None, None
        
        # 遍历所有周期进行截图
        for timeframe in TIME_PERIODS:
            print(f"  正在处理周期: {timeframe}")
            if switch_timeframe(driver, timeframe):
                screenshot_path = take_screenshot(driver, symbol, timeframe)
                if screenshot_path:
                    screenshot_paths[timeframe] = screenshot_path
                time.sleep(2)  # 间隔等待
        
        # 组合图片
        combined_path = None
        if len(screenshot_paths) == 4:
            print(f"  正在组合图片...")
            combined_path = combine_images(screenshot_paths, symbol)
        
        return screenshot_paths, combined_path
    finally:
        driver.quit()

def capture_all_timeframes():
    """批量截图所有周期（兼容旧接口，默认ETH）"""
    from config import SYMBOLS
    symbol = SYMBOLS[0] if SYMBOLS else 'ETH'
    screenshot_paths, _ = capture_all_timeframes_for_symbol(symbol)
    return screenshot_paths
