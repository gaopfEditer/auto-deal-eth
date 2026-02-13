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
    TARGET_URL,
    TARGET_PAGE_SELECTOR,
    SCREENSHOT_DIR,
    SCREENSHOT_WIDTH,
    SCREENSHOT_HEIGHT,
    USE_REMOTE_DEBUGGING,
    CHROME_DEBUG_PORT,
    CHROME_HEADLESS,
    CHROME_USER_DATA_DIR,
    CHROME_PROFILE_NAME
)
from PIL import Image

def check_chrome_running():
    """检查Chrome是否正在运行"""
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq chrome.exe'], 
                                  capture_output=True, text=True, shell=True)
            return 'chrome.exe' in result.stdout
        elif platform.system() == "Darwin":  # Mac
            import subprocess
            result = subprocess.run(['pgrep', '-f', 'Google Chrome'], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        return False
    except Exception:
        return False

def close_chrome_processes():
    """关闭所有 Chrome 进程"""
    try:
        if platform.system() == "Windows":
            import subprocess
            print("[INFO] 正在关闭所有 Chrome 进程...")
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], 
                         capture_output=True, text=True, shell=True)
            time.sleep(2)  # 等待进程完全关闭
            print("[OK] Chrome 进程已关闭")
            return True
        elif platform.system() == "Darwin":  # Mac
            import subprocess
            print("[INFO] 正在关闭所有 Chrome 进程...")
            subprocess.run(['pkill', '-f', 'Google Chrome'], 
                         capture_output=True, text=True)
            time.sleep(2)
            print("[OK] Chrome 进程已关闭")
            return True
        return False
    except Exception as e:
        print(f"[WARNING] 关闭 Chrome 进程时出错: {e}")
        return False

# 已移除 wait_for_profile_unlock 函数，避免误操作账号数据
# 现在只在启动前删除锁文件，不进行其他操作

def verify_chrome_profile(user_data_dir: str, profile_name: str):
    """验证 Chrome Profile 配置是否正确"""
    import json
    
    print("\n" + "="*60)
    print("验证 Chrome Profile 配置...")
    print("="*60)
    
    # 检查用户数据目录
    if not os.path.exists(user_data_dir):
        print(f"[ERROR] Chrome用户数据目录不存在: {user_data_dir}")
        print("[提示] 请检查 CHROME_USER_DATA_DIR 配置是否正确")
        return False
    
    print(f"[OK] Chrome用户数据目录存在: {user_data_dir}")
    
    # 检查 Profile 目录
    profile_path = os.path.join(user_data_dir, profile_name)
    if not os.path.exists(profile_path):
        print(f"[ERROR] Profile 目录不存在: {profile_path}")
        print(f"[提示] 请检查 CHROME_PROFILE_NAME 配置是否正确（当前值: {profile_name}）")
        
        # 列出所有可用的 Profile
        print("\n[INFO] 可用的 Profile 列表:")
        for item in os.listdir(user_data_dir):
            item_path = os.path.join(user_data_dir, item)
            if os.path.isdir(item_path) and (item.startswith('Profile') or item == 'Default'):
                print(f"  - {item}")
        return False
    
    print(f"[OK] Profile 目录存在: {profile_path}")
    
    # 检查 Preferences 文件
    preferences_path = os.path.join(profile_path, 'Preferences')
    if not os.path.exists(preferences_path):
        print(f"[WARNING] Preferences 文件不存在: {preferences_path}")
        print("[提示] 这可能是新创建的 Profile，尚未配置")
        return True  # 仍然返回 True，因为目录存在
    
    print(f"[OK] Preferences 文件存在")
    
    # 尝试读取账号信息
    try:
        with open(preferences_path, 'r', encoding='utf-8') as f:
            prefs = json.load(f)
        
        # 获取账号信息
        account_info = prefs.get('account_info', [])
        profile_info = prefs.get('profile', {})
        profile_name_in_prefs = profile_info.get('name', '')
        
        if account_info:
            print(f"\n[INFO] Profile 账号信息:")
            for account in account_info:
                email = account.get('email', 'N/A')
                print(f"  - 邮箱: {email}")
        elif profile_name_in_prefs:
            print(f"\n[INFO] Profile 名称: {profile_name_in_prefs}")
        else:
            print(f"\n[INFO] Profile 信息: 默认配置")
        
        print("\n" + "="*60)
        print("[OK] Chrome Profile 配置验证通过")
        print("="*60 + "\n")
        return True
        
    except json.JSONDecodeError:
        print(f"[WARNING] Preferences 文件格式错误，无法读取账号信息")
        print("[提示] Profile 目录存在，但配置文件可能损坏")
        return True  # 仍然返回 True，因为目录存在
    except Exception as e:
        print(f"[WARNING] 读取 Preferences 文件时出错: {e}")
        print("[提示] Profile 目录存在，但无法读取详细信息")
        return True  # 仍然返回 True，因为目录存在

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
        
        # 否则，直接打开浏览器（可以使用指定的 Profile）
        else:
            # 检查 Chrome 是否正在运行
            if check_chrome_running():
                print("\n" + "="*60)
                print("[ERROR] Chrome 正在运行！")
                print("="*60)
                print("\n【重要提示】")
                print("使用 Profile 时，Chrome 必须完全关闭，否则会触发 Chrome 的保护机制")
                print("可能导致账号数据被清空！")
                print("\n【解决方法】")
                print("1. 请手动关闭所有 Chrome 窗口和进程")
                print("2. 检查任务管理器，确保没有 chrome.exe 进程")
                print("3. 然后重新运行程序")
                print("\n" + "="*60 + "\n")
                raise Exception("Chrome 正在运行，请先手动关闭所有 Chrome 窗口")
            
            chrome_options = Options()
            
            # 无头模式配置
            if CHROME_HEADLESS:
                chrome_options.add_argument('--headless')
                print("[INFO] 使用无头模式")
            else:
                print("[INFO] 使用有界面模式（可以看到浏览器窗口）")
            
            # 基本配置
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument(f'--window-size={SCREENSHOT_WIDTH},{SCREENSHOT_HEIGHT}')
            chrome_options.add_argument('--disable-gpu')
            # 防止被其他程序篡改的参数
            chrome_options.add_argument('--disable-default-apps')
            chrome_options.add_argument('--disable-sync')  # 禁用同步，避免被其他程序影响
            # 添加远程调试端口，方便调试和访问 http://localhost:9222/json
            chrome_options.add_argument(f'--remote-debugging-port={CHROME_DEBUG_PORT}')
            print(f"[INFO] 已启用远程调试端口: {CHROME_DEBUG_PORT} (可访问 http://localhost:{CHROME_DEBUG_PORT}/json)")
            
            # 如果配置了用户数据目录和 Profile，使用指定的 Profile
            user_data_dir = None
            profile_name = None
            
            if CHROME_USER_DATA_DIR and CHROME_USER_DATA_DIR.strip():
                user_data_dir = os.path.expanduser(CHROME_USER_DATA_DIR.strip())
                if CHROME_PROFILE_NAME and CHROME_PROFILE_NAME.strip():
                    profile_name = CHROME_PROFILE_NAME.strip()
            elif CHROME_PROFILE_NAME and CHROME_PROFILE_NAME.strip():
                # 如果只配置了 Profile 名称，尝试使用默认用户数据目录
                if platform.system() == "Windows":
                    default_user_data = os.path.join(os.getenv('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
                elif platform.system() == "Darwin":  # Mac
                    default_user_data = os.path.expanduser('~/Library/Application Support/Google/Chrome')
                else:  # Linux
                    default_user_data = os.path.expanduser('~/.config/google-chrome')
                
                if os.path.exists(default_user_data):
                    user_data_dir = default_user_data
                    profile_name = CHROME_PROFILE_NAME.strip()
            
            # 如果配置了 Profile，验证并应用
            if user_data_dir and profile_name:
                abs_user_data_dir = os.path.abspath(user_data_dir)
                
                # 重要：不删除锁文件，不访问 Profile 文件
                # 让 Chrome 自己管理，避免触发保护机制
                # 只验证目录存在即可
                profile_path = os.path.join(abs_user_data_dir, profile_name)
                if os.path.exists(profile_path):
                    print(f"[INFO] Profile 目录存在: {profile_path}")
                    print(f"[INFO] 使用配置文件: {profile_name}")
                else:
                    print(f"[WARNING] Profile 目录不存在: {profile_path}")
                    print(f"[INFO] Chrome 将创建新的 Profile")
                
                # 直接使用，不进行任何文件操作
                if os.path.exists(abs_user_data_dir):
                    # 明确指定用户数据目录和 Profile，使用绝对路径避免被其他程序篡改
                    chrome_options.add_argument(f'--user-data-dir={abs_user_data_dir}')
                    chrome_options.add_argument(f'--profile-directory={profile_name}')
                    print(f"[INFO] 使用Chrome用户配置文件: {abs_user_data_dir}")
                    print(f"[INFO] 使用配置文件: {profile_name}")
                    print(f"[INFO] 注意：请确保 Chrome 已完全关闭，否则可能触发保护机制")
                else:
                    print(f"[WARNING] 用户数据目录不存在，将使用无痕模式")
            elif user_data_dir:
                # 只配置了用户数据目录，没有指定 Profile
                if os.path.exists(user_data_dir):
                    chrome_options.add_argument(f'--user-data-dir={user_data_dir}')
                    print(f"[INFO] 使用Chrome用户配置文件: {user_data_dir}")
                    print(f"[INFO] 使用默认配置文件")
                else:
                    print(f"[WARNING] Chrome用户数据目录不存在: {user_data_dir}")
                    print(f"[INFO] 使用无痕模式（未登录状态）")
            else:
                print("[INFO] 使用无痕模式（未登录状态）")
            
            # 使用 webdriver-manager 自动管理 ChromeDriver
            try:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception:
                # 如果 webdriver-manager 失败，尝试直接使用系统 ChromeDriver
                driver = webdriver.Chrome(options=chrome_options)
            
            driver.set_window_size(SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT)
            print("[OK] 浏览器已启动")
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
        elif "crashed" in error_msg.lower() or "not reachable" in error_msg.lower() or "devtoolsactiveport" in error_msg.lower():
            print("\n" + "="*60)
            print("[ERROR] Chrome启动失败！")
            print("="*60)
            print("\n【可能的原因】")
            print("1. Chrome浏览器正在运行，导致冲突")
            print("2. Chrome版本与ChromeDriver不匹配")
            print("3. 系统资源不足")
            print("\n【解决方法】")
            if not USE_REMOTE_DEBUGGING:
                print("1. 推荐：使用远程调试模式（不会修改Chrome配置）")
                print("   - 设置 USE_REMOTE_DEBUGGING=True")
                print("   - 以远程调试模式启动Chrome:")
                if platform.system() == "Windows":
                    print(f'     "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={CHROME_DEBUG_PORT}')
                elif platform.system() == "Darwin":  # Mac
                    print(f'     /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={CHROME_DEBUG_PORT}')
                print("   - 在Chrome中登录需要的账号")
                print("   - 然后运行程序")
                print("2. 或者：关闭所有Chrome窗口后重新运行")
            else:
                print("1. 确保Chrome已以远程调试模式启动")
                print("2. 检查远程调试端口是否正确")
            print("\n" + "="*60 + "\n")
        raise

# 第2部分：切换币种和周期功能
def switch_symbol(driver, symbol: str):
    """切换TradingView的币种"""
    try:
        from config import TRADINGVIEW_BASE_URL
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
        from config import TIME_PERIODS
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
    from config import TIME_PERIODS
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

def capture_target_page():
    """截图目标页面（tophub.today）"""
    driver = init_browser()
    screenshot_path = None
    
    try:
        print(f"正在访问目标页面: {TARGET_URL}")
        max_retries = 3
        for attempt in range(max_retries):
            try:
                driver.get(TARGET_URL)
                time.sleep(5)  # 等待页面完全加载
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[ERROR] 访问目标页面失败: {e}")
                    raise
                print(f"[WARNING] 访问失败，3秒后重试... ({e})")
                time.sleep(3)
        
        # 等待页面元素加载
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, TARGET_PAGE_SELECTOR))
            )
        except TimeoutException:
            print(f"[WARNING] 未找到选择器 {TARGET_PAGE_SELECTOR}，继续截图")
        
        time.sleep(3)  # 额外等待确保页面渲染完成
        
        # 截图
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        screenshot_path = os.path.join(SCREENSHOT_DIR, 'tophub_page.png')
        driver.save_screenshot(screenshot_path)
        print(f"[OK] 截图已保存: {screenshot_path}")
        
        return screenshot_path
    except Exception as e:
        print(f"[ERROR] 截图失败: {e}")
        return None
    finally:
        driver.quit()

def capture_all_timeframes():
    """批量截图所有周期（兼容旧接口，默认ETH）"""
    from config import SYMBOLS
    symbol = SYMBOLS[0] if SYMBOLS else 'ETH'
    screenshot_paths, _ = capture_all_timeframes_for_symbol(symbol)
    return screenshot_paths

def analyze_with_gemini_web(image_path: str, symbol: str, prompt: str = None):
    """使用 Gemini 网页版进行分析（浏览器自动化方式）"""
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    import os
    
    driver = init_browser()
    analysis_result = None
    
    try:
        # 根据symbol判断分析类型
        if symbol == "tophub" or "tophub" in symbol.lower():
            default_prompt = """请分析这个网页截图的内容，并严格按照 JSON 格式输出分析结果。

这是一个技术开发者热门内容聚合页面（tophub.today/c/developer）。

分析要求：
1. 识别页面上的主要内容类型和主题
2. 提取热门文章/项目的标题和关键信息
3. 分析当前技术趋势和热点话题
4. 总结页面上的重要信息
5. 提供有价值的洞察

输出格式必须符合以下 JSON 结构：
{
    "page_type": "string",
    "main_topics": ["string"],
    "hot_items": [
        {
            "title": "string",
            "description": "string",
            "category": "string"
        }
    ],
    "trends": "string",
    "insights": "string",
    "summary": "string"
}"""
        else:
            default_prompt = f"""你是一个资深的加密货币技术分析师。请分析提供的 K 线图表，并严格按照 JSON 格式输出建议。

币种：{symbol}

分析要求：
1. 识别当前趋势（上涨/下跌/震荡）
2. 识别关键支撑位和阻力位
3. 分析技术指标信号（MACD, RSI, Bollinger Bands 等）
4. 给出明确交易建议（Long/Short/Neutral）
5. 评估风险等级（Low/Medium/High）

输出格式必须符合以下 JSON 结构：
{{
    "symbol": "{symbol}",
    "trend": "string",
    "support_level": "string",
    "resistance_level": "string",
    "indicators": {{
        "macd": "string",
        "rsi": "string",
        "bb": "string"
    }},
    "recommendation": "string",
    "risk_level": "string",
    "reasoning": "string"
}}"""
        
        analysis_prompt = prompt if prompt else default_prompt
        
        print(f"  正在打开 Gemini 网页版...")
        # 打开 Gemini 网页版
        driver.get("https://gemini.google.com")
        time.sleep(5)  # 等待页面加载
        
        # 等待页面元素加载
        try:
            # 查找输入框或上传按钮
            # Gemini 网页版可能有不同的界面，需要尝试多种选择器
            print(f"  等待页面元素加载...")
            time.sleep(3)
            
            # 尝试查找上传图片的按钮或区域
            # Gemini 网页版需要先点击"添加文件"按钮，然后在浮窗中点击"上传文件"
            file_input = None
            
            # 方法1: 直接查找文件输入框（可能隐藏）
            try:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_inputs:
                    file_input = file_inputs[0]
                    print(f"  [INFO] 找到隐藏的文件输入框")
            except:
                pass
            
            # 方法2: 先点击"添加文件"按钮，然后在浮窗中点击"上传文件"
            if not file_input:
                try:
                    # 步骤1: 查找并点击"添加文件"按钮（或类似的按钮）
                    add_file_button = None
                    add_file_selectors = [
                        "//button[contains(text(), '添加文件')]",
                        "//button[contains(text(), 'Add file')]",
                        "//button[contains(@aria-label, '添加')]",
                        "//button[contains(@aria-label, 'Add')]",
                        "//*[@role='button' and contains(text(), '添加')]",
                        "//*[@role='button' and contains(text(), 'Add')]",
                        "button[aria-label*='add']",
                        "button[aria-label*='Add']",
                        "[data-testid='add-file-button']",
                    ]
                    
                    for selector in add_file_selectors:
                        try:
                            if selector.startswith("//"):
                                add_file_button = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.XPATH, selector))
                                )
                            else:
                                add_file_button = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                                )
                            if add_file_button:
                                print(f"  [INFO] 找到添加文件按钮，正在点击...")
                                # 使用普通方法点击"添加文件"按钮
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_file_button)
                                time.sleep(0.3)
                                add_file_button.click()
                                print(f"  [OK] 已点击添加文件按钮")
                                time.sleep(1.5)  # 等待浮窗出现
                                break
                        except:
                            continue
                    
                    if not add_file_button:
                        print(f"  [WARNING] 未找到添加文件按钮，尝试直接查找上传文件按钮")
                    
                    # 步骤2: 等待浮窗出现，然后查找"上传文件"按钮并使用 pyautogui 点击
                    if add_file_button or True:  # 即使没找到添加文件按钮，也尝试查找上传文件按钮
                        time.sleep(1)  # 等待浮窗出现
                        
                        # 查找"上传文件"按钮
                        upload_button = None
                        try:
                            # 查找包含"上传文件"文本的可点击父元素（浮窗中的）
                            upload_button = WebDriverWait(driver, 3).until(
                                EC.presence_of_element_located((By.XPATH, "//*[contains(@class, 'mdc-list-item') and .//div[contains(text(), '上传文件')]] | //*[contains(@class, 'list-item') and .//*[contains(text(), '上传文件')]]"))
                            )
                            print(f"  [INFO] 找到上传文件按钮（浮窗中）")
                        except:
                            try:
                                upload_button = WebDriverWait(driver, 3).until(
                                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'menu-text') and contains(text(), '上传文件')] | //div[contains(text(), '上传文件')] | //span[contains(text(), '上传文件')] | //*[contains(text(), '上传文件')]"))
                                )
                                print(f"  [INFO] 找到上传文件按钮（文本元素）")
                            except:
                                pass
                        
                        if upload_button:
                            # 使用 pyautogui 点击"上传文件"按钮（浮窗中的）
                            try:
                                import pyautogui
                                
                                # 滚动到元素可见
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", upload_button)
                                time.sleep(0.5)
                                
                                # 使用 location_once_scrolled_into_view 获取滚动后的位置
                                location = upload_button.location_once_scrolled_into_view
                                size = upload_button.size
                                
                                # 获取浏览器窗口的位置
                                window_position = driver.get_window_position()
                                
                                # 计算元素中心点在浏览器窗口中的坐标
                                element_center_x = location['x'] + size['width'] // 2
                                element_center_y = location['y'] + size['height'] // 2
                                
                                # 计算屏幕上的绝对坐标
                                offset_x = 50   # 可以根据实际情况调整
                                offset_y = 150  # 可以根据实际情况调整（通常 100-200 之间）
                                
                                screen_x = window_position['x'] + element_center_x + offset_x
                                screen_y = window_position['y'] + element_center_y + offset_y
                                
                                print(f"  [INFO] 使用 pyautogui 点击上传文件按钮（浮窗中）")
                                print(f"  [INFO] 元素位置: {location}, 中心点: ({element_center_x}, {element_center_y})")
                                print(f"  [INFO] 屏幕坐标: ({screen_x}, {screen_y})")
                                
                                # 使用 pyautogui 点击屏幕坐标
                                pyautogui.PAUSE = 0.1
                                pyautogui.click(screen_x, screen_y)
                                print(f"  [OK] pyautogui 坐标点击完成")
                                time.sleep(2)  # 等待文件选择对话框打开
                                
                                # 验证是否真的点击成功（检查是否出现文件输入框）
                                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                                if file_inputs:
                                    file_input = file_inputs[0]
                                    print(f"  [OK] 点击成功，找到文件输入框")
                                else:
                                    print(f"  [WARNING] 点击后未找到文件输入框")
                            except ImportError:
                                print(f"  [WARNING] pyautogui 未安装，尝试其他方法")
                                # 回退到普通点击
                                upload_button.click()
                                time.sleep(2)
                                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                                if file_inputs:
                                    file_input = file_inputs[0]
                            except Exception as e:
                                print(f"  [DEBUG] pyautogui 点击失败: {e}")
                        else:
                            print(f"  [WARNING] 未找到上传文件按钮（浮窗中）")
                            
                except Exception as e:
                    print(f"  [DEBUG] 通过添加文件按钮流程失败: {e}")
            
            # 方法3: 直接通过文本内容查找"上传文件"按钮（如果浮窗已经打开）
            if not file_input:
                try:
                    # 首先尝试查找可点击的父容器（更可靠）
                    upload_button = None
                    try:
                        # 查找包含"上传文件"文本的可点击父元素
                        upload_button = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, "//*[contains(@class, 'mdc-list-item') and .//div[contains(text(), '上传文件')]] | //*[contains(@class, 'list-item') and .//*[contains(text(), '上传文件')]]"))
                        )
                        print(f"  [INFO] 找到上传文件按钮（父容器）")
                    except:
                        # 如果找不到父容器，查找文本元素
                        try:
                            upload_button = WebDriverWait(driver, 3).until(
                                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'menu-text') and contains(text(), '上传文件')] | //div[contains(text(), '上传文件')] | //span[contains(text(), '上传文件')] | //*[contains(text(), '上传文件')]"))
                            )
                            print(f"  [INFO] 找到上传文件按钮（文本元素）")
                        except:
                            pass
                    
                    if not upload_button:
                        raise Exception("未找到上传文件按钮")
                    
                    # 滚动到元素可见
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", upload_button)
                    time.sleep(0.5)
                    
                    # 尝试多种点击方式，优先使用 pyautogui（最可靠）
                    clicked = False
                    file_input = None
                    
                    # 方法1: 优先使用 pyautogui 坐标点击（最可靠，绕过浏览器限制）
                    try:
                        import pyautogui
                        
                        # 使用 location_once_scrolled_into_view 获取滚动后的位置
                        location = upload_button.location_once_scrolled_into_view
                        size = upload_button.size
                        
                        # 获取浏览器窗口的位置
                        window_position = driver.get_window_position()
                        
                        # 计算元素中心点在浏览器窗口中的坐标
                        element_center_x = location['x'] + size['width'] // 2
                        element_center_y = location['y'] + size['height'] // 2
                        
                        # 计算屏幕上的绝对坐标
                        offset_x = 50   # 可以根据实际情况调整
                        offset_y = 150  # 可以根据实际情况调整（通常 100-200 之间）
                        
                        screen_x = window_position['x'] + element_center_x + offset_x
                        screen_y = window_position['y'] + element_center_y + offset_y
                        
                        print(f"  [INFO] 使用 pyautogui 坐标点击（最可靠）")
                        print(f"  [INFO] 元素位置: {location}, 中心点: ({element_center_x}, {element_center_y})")
                        print(f"  [INFO] 浏览器窗口位置: {window_position}")
                        print(f"  [INFO] 屏幕坐标: ({screen_x}, {screen_y})")
                        
                        # 使用 pyautogui 点击屏幕坐标
                        pyautogui.PAUSE = 0.1
                        pyautogui.click(screen_x, screen_y)
                        print(f"  [OK] pyautogui 坐标点击完成")
                        time.sleep(2)  # 等待点击生效和菜单打开
                        
                        # 验证是否真的点击成功（检查是否出现文件输入框）
                        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                        if file_inputs:
                            file_input = file_inputs[0]
                            print(f"  [OK] 点击成功，找到文件输入框")
                            clicked = True
                        else:
                            print(f"  [WARNING] 点击后未找到文件输入框，继续尝试其他方法")
                    except ImportError:
                        print(f"  [WARNING] pyautogui 未安装，将尝试其他方法")
                    except Exception as e:
                        print(f"  [DEBUG] pyautogui 坐标点击失败: {e}")
                    
                    # 方法2: 使用 JavaScript 点击（备用方法）
                    if not clicked:
                        try:
                            driver.execute_script("arguments[0].click();", upload_button)
                            print(f"  [INFO] 使用 JavaScript 点击")
                            time.sleep(1.5)
                            # 验证是否真的点击成功
                            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                            if file_inputs:
                                file_input = file_inputs[0]
                                print(f"  [OK] JavaScript 点击成功（找到文件输入框）")
                                clicked = True
                            else:
                                print(f"  [WARNING] JavaScript 点击未生效（未找到文件输入框）")
                        except Exception as e:
                            print(f"  [DEBUG] JavaScript 点击失败: {e}")
                    
                    # 方法3: 普通点击
                    if not clicked:
                        try:
                            upload_button.click()
                            print(f"  [INFO] 使用普通点击")
                            time.sleep(1.5)
                            # 验证是否真的点击成功
                            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                            if file_inputs:
                                file_input = file_inputs[0]
                                print(f"  [OK] 普通点击成功（找到文件输入框）")
                                clicked = True
                            else:
                                print(f"  [WARNING] 普通点击未生效")
                        except Exception as e:
                            print(f"  [DEBUG] 普通点击失败: {e}")
                    
                    # 方法4: 使用 ActionChains 点击
                    if not clicked:
                        try:
                            from selenium.webdriver.common.action_chains import ActionChains
                            actions = ActionChains(driver)
                            actions.move_to_element(upload_button).pause(0.2).click().perform()
                            print(f"  [INFO] 使用 ActionChains 点击")
                            time.sleep(1.5)
                            # 验证是否真的点击成功
                            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                            if file_inputs:
                                file_input = file_inputs[0]
                                print(f"  [OK] ActionChains 点击成功（找到文件输入框）")
                                clicked = True
                            else:
                                print(f"  [WARNING] ActionChains 点击未生效")
                        except Exception as e:
                            print(f"  [DEBUG] ActionChains 点击失败: {e}")
                    
                    # 方法5: 尝试点击父元素
                    if not clicked:
                        try:
                            # 找到可点击的父元素
                            parent = driver.execute_script("""
                                var elem = arguments[0];
                                while (elem && elem.parentElement) {
                                    elem = elem.parentElement;
                                    if (elem.onclick || elem.getAttribute('role') === 'button' || elem.tagName === 'BUTTON') {
                                        return elem;
                                    }
                                }
                                return arguments[0].closest('[role="button"], button, [onclick]');
                            """, upload_button)
                            if parent:
                                driver.execute_script("arguments[0].click();", parent)
                                print(f"  [INFO] 通过点击父元素")
                                time.sleep(1.5)
                                # 验证是否真的点击成功
                                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                                if file_inputs:
                                    file_input = file_inputs[0]
                                    print(f"  [OK] 点击父元素成功（找到文件输入框）")
                                    clicked = True
                                else:
                                    print(f"  [WARNING] 点击父元素未生效")
                        except Exception as e:
                            print(f"  [DEBUG] 点击父元素失败: {e}")
                    
                    # 方法6: 使用 JavaScript 在元素中心触发点击事件（备用）
                    if not clicked:
                        try:
                            # 使用 JavaScript 在元素中心位置触发点击
                            driver.execute_script("""
                                var elem = arguments[0];
                                var rect = elem.getBoundingClientRect();
                                var x = rect.left + rect.width / 2;
                                var y = rect.top + rect.height / 2;
                                
                                // 创建并触发点击事件
                                var clickEvent = new MouseEvent('click', {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true,
                                    clientX: x,
                                    clientY: y,
                                    button: 0
                                });
                                
                                // 先触发 mousedown
                                var mouseDownEvent = new MouseEvent('mousedown', {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true,
                                    clientX: x,
                                    clientY: y,
                                    button: 0
                                });
                                
                                // 再触发 mouseup
                                var mouseUpEvent = new MouseEvent('mouseup', {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true,
                                    clientX: x,
                                    clientY: y,
                                    button: 0
                                });
                                
                                elem.dispatchEvent(mouseDownEvent);
                                setTimeout(function() {
                                    elem.dispatchEvent(mouseUpEvent);
                                    elem.dispatchEvent(clickEvent);
                                }, 10);
                            """, upload_button)
                            print(f"  [INFO] 使用 JavaScript 坐标事件")
                            time.sleep(1.5)
                            # 验证是否真的点击成功
                            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                            if file_inputs:
                                file_input = file_inputs[0]
                                print(f"  [OK] JavaScript 坐标事件成功（找到文件输入框）")
                                clicked = True
                            else:
                                print(f"  [WARNING] JavaScript 坐标事件未生效")
                        except Exception as e:
                            print(f"  [DEBUG] JavaScript 坐标事件失败: {e}")
                    
                    # 如果所有方法都尝试了但还没找到文件输入框，最后再查找一次
                    if not file_input and clicked:
                        print(f"  [INFO] 点击已完成，查找文件输入框...")
                        time.sleep(2)
                        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                        if file_inputs:
                            file_input = file_inputs[0]
                            print(f"  [OK] 找到文件输入框")
                    
                    if not clicked and not file_input:
                        print(f"  [WARNING] 所有点击方式都失败，未找到文件输入框")
                        
                except Exception as e:
                    print(f"  [DEBUG] 通过文本查找失败: {e}")
            
            # 方法3: 尝试其他常见的选择器（使用 pyautogui 点击）
            if not file_input:
                upload_selectors = [
                    "button[aria-label*='upload']",
                    "button[aria-label*='Upload']",
                    "button[aria-label*='上传']",
                    "[data-testid='upload-button']",
                    ".upload-button",
                    "[role='button'][aria-label*='upload']",
                    "[role='button'][aria-label*='Upload']",
                ]
                
                for selector in upload_selectors:
                    try:
                        button = WebDriverWait(driver, 2).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        print(f"  [INFO] 找到上传按钮 ({selector})，使用 pyautogui 点击...")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                        time.sleep(0.5)
                        
                        # 使用 pyautogui 坐标点击
                        try:
                            import pyautogui
                            location = button.location_once_scrolled_into_view
                            size = button.size
                            window_position = driver.get_window_position()
                            
                            element_center_x = location['x'] + size['width'] // 2
                            element_center_y = location['y'] + size['height'] // 2
                            
                            screen_x = window_position['x'] + element_center_x + 50
                            screen_y = window_position['y'] + element_center_y + 150
                            
                            pyautogui.PAUSE = 0.1
                            pyautogui.click(screen_x, screen_y)
                            print(f"  [INFO] pyautogui 坐标点击完成")
                        except ImportError:
                            # 如果 pyautogui 未安装，尝试 JavaScript 点击
                            driver.execute_script("arguments[0].click();", button)
                            print(f"  [INFO] 使用 JavaScript 点击（pyautogui 未安装）")
                        except Exception as e:
                            print(f"  [DEBUG] pyautogui 点击失败: {e}")
                            driver.execute_script("arguments[0].click();", button)
                            print(f"  [INFO] 回退到 JavaScript 点击")
                        
                        time.sleep(2)
                        # 验证是否真的点击成功
                        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                        if file_inputs:
                            file_input = file_inputs[0]
                            print(f"  [OK] 点击成功，找到文件输入框")
                            break
                        else:
                            print(f"  [WARNING] 点击后未找到文件输入框，继续尝试其他选择器")
                    except Exception as e:
                        # 不输出错误，静默继续
                        continue
            
            # 方法4: 再次查找文件输入框（可能在点击后出现）
            if not file_input:
                try:
                    file_inputs = WebDriverWait(driver, 3).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']"))
                    )
                    if file_inputs:
                        file_input = file_inputs[0]
                        print(f"  [INFO] 最终找到文件输入框")
                except:
                    pass
            
            if file_input:
                print(f"  正在上传图片: {image_path}")
                # 上传图片
                abs_image_path = os.path.abspath(image_path)
                file_input.send_keys(abs_image_path)
                time.sleep(5)  # 等待图片上传和处理
                print(f"  ✓ 图片上传成功")
            else:
                # 如果找不到上传按钮，提示用户手动操作
                print(f"  [INFO] 未找到自动上传按钮")
                print(f"  [提示] 请在浏览器中手动上传图片:")
                print(f"    1. 点击 Gemini 网页版中的图片上传按钮")
                print(f"    2. 选择图片文件: {os.path.abspath(image_path)}")
                print(f"    3. 程序将在 15 秒后继续...")
                time.sleep(15)  # 给用户时间手动上传
            
            # 等待图片处理完成
            time.sleep(3)
            
            # 查找输入框并输入提示词
            print(f"  正在输入分析提示词...")
            input_selectors = [
                "textarea",
                "div[contenteditable='true']",
                "input[type='text']",
                "[data-testid='input']",
                ".input-box",
                "#input"
            ]
            
            text_input = None
            for selector in input_selectors:
                try:
                    text_input = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    if text_input:
                        break
                except:
                    continue
            
            if text_input:
                # 清空并输入提示词
                text_input.clear()
                text_input.send_keys(analysis_prompt)
                time.sleep(1)
                
                # 查找发送按钮并点击
                send_selectors = [
                    "button[type='submit']",
                    "button[aria-label*='send']",
                    "button[aria-label*='Send']",
                    "[data-testid='send-button']",
                    "button:contains('Send')",
                    "button:contains('发送')",
                    ".send-button"
                ]
                
                send_button = None
                for selector in send_selectors:
                    try:
                        send_button = driver.find_element(By.CSS_SELECTOR, selector)
                        if send_button and send_button.is_enabled():
                            break
                    except:
                        continue
                
                if send_button:
                    send_button.click()
                else:
                    # 如果找不到发送按钮，尝试按 Enter 键
                    text_input.send_keys(Keys.RETURN)
                
                print(f"  ✓ 已发送分析请求")
            else:
                print(f"  [WARNING] 未找到输入框，尝试使用键盘输入...")
                # 尝试使用 ActionChains 点击页面并输入
                actions = ActionChains(driver)
                actions.send_keys(analysis_prompt)
                actions.send_keys(Keys.RETURN)
                actions.perform()
            
            # 等待分析结果
            print(f"  等待分析结果...")
            time.sleep(10)  # 等待 Gemini 生成结果
            
            # 查找结果区域
            result_selectors = [
                ".response",
                "[data-testid='response']",
                ".message-content",
                ".gemini-response",
                "div[class*='response']",
                "div[class*='message']"
            ]
            
            result_text = None
            for selector in result_selectors:
                try:
                    result_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if result_elements:
                        # 获取最后一个结果元素（最新的响应）
                        result_text = result_elements[-1].text
                        if result_text and len(result_text) > 50:  # 确保有实际内容
                            break
                except:
                    continue
            
            # 如果找不到结果，尝试获取整个页面的文本
            if not result_text:
                try:
                    body = driver.find_element(By.TAG_NAME, "body")
                    result_text = body.text
                except:
                    pass
            
            if result_text and len(result_text.strip()) > 50:
                print(f"  ✓ 成功获取分析结果")
                analysis_result = {
                    'symbol': symbol,
                    'analysis': result_text,
                    'status': 'success',
                    'method': 'web'
                }
            else:
                print(f"  [INFO] 等待 Gemini 生成分析结果...")
                print(f"  [提示] 如果结果未自动获取，请在浏览器中查看 Gemini 的分析结果")
                # 再等待一段时间让 Gemini 生成结果
                time.sleep(20)
                # 再次尝试获取结果
                try:
                    body = driver.find_element(By.TAG_NAME, "body")
                    result_text = body.text
                    # 尝试提取更具体的结果内容
                    if result_text and len(result_text.strip()) > 50:
                        analysis_result = {
                            'symbol': symbol,
                            'analysis': result_text,
                            'status': 'success',
                            'method': 'web'
                        }
                        print(f"  ✓ 成功获取分析结果")
                    else:
                        # 即使无法自动获取，也返回成功状态，因为结果在浏览器中可见
                        analysis_result = {
                            'symbol': symbol,
                            'status': 'success',
                            'message': '分析结果已在浏览器中显示，请查看 Gemini 网页版',
                            'method': 'web'
                        }
                        print(f"  [INFO] 分析结果已在浏览器中显示，请手动查看")
                except:
                    analysis_result = {
                        'symbol': symbol,
                        'status': 'success',
                        'message': '分析结果已在浏览器中显示，请查看 Gemini 网页版',
                        'method': 'web'
                    }
                    print(f"  [INFO] 分析结果已在浏览器中显示，请手动查看")
            
        except TimeoutException:
            print(f"  [ERROR] 页面元素加载超时")
            analysis_result = {
                'symbol': symbol,
                'status': 'error',
                'error': '页面元素加载超时',
                'method': 'web'
            }
        except Exception as e:
            print(f"  [ERROR] 浏览器操作失败: {e}")
            analysis_result = {
                'symbol': symbol,
                'status': 'error',
                'error': str(e),
                'method': 'web'
            }
        
        return analysis_result
        
    except Exception as e:
        print(f"[ERROR] Gemini 网页版分析失败: {e}")
        return {
            'symbol': symbol,
            'status': 'error',
            'error': str(e),
            'method': 'web'
        }
    finally:
        # 不关闭浏览器，保持浏览器打开以便用户查看结果
        # 注意：如果使用远程调试模式，driver.quit() 不会关闭浏览器窗口
        # 如果使用直接打开模式，driver.quit() 会关闭浏览器
        # 这里保持浏览器打开，让用户可以看到分析结果
        print(f"  [提示] 浏览器将保持打开状态，您可以查看完整的分析结果")
        # driver.quit()  # 如果需要自动关闭浏览器，取消注释此行
