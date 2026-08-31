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
import sys
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
from typing import Optional

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

def focus_last_tab(driver) -> bool:
    """
    仅记录/确认最后一个页签，不 Selenium switch_to（switch_to 会抢焦点）。
    真正导航请用 navigate_in_last_tab。
    """
    try:
        handles = list(driver.window_handles or [])
    except Exception:
        return False
    return bool(handles)


def navigate_in_last_tab(driver, url: str) -> None:
    """在最后一个已有页签打开 URL。

    CDP 导航 → activateTarget（页签可见）→ 卸静默绑定 → Selenium switch_to 末页签
    → 立即还 OS 焦点，避免 Cursor 被抢走。
    """
    url = (url or "").strip()
    if not url:
        return

    from binance.cdp_silent import capture_os_focus, restore_os_focus, set_binding

    prev_focus = capture_os_focus()
    try:
        from binance.cdp_navigation import cdp_goto

        session = cdp_goto(
            driver,
            url,
            page_load_timeout=90,
            log_prefix="CDP-last-tab",
            last_tab=True,
            persistent=False,
        )
        href = ""
        try:
            if session and session.binding:
                href = str(session.binding.current_url() or "")
        except Exception:
            href = ""
        print(f"[OK] 静默 CDP 已在最后一页签打开: {url[:80]}")
        if href:
            print(f"[OK] 校验 location.href: {href[:120]}")

        # 卸静默绑定：后续 Gemini 用完整 Selenium（SilentWebElement 半残会卡住）
        set_binding(driver, None)
        tid = str((session.target_id if session else "") or "")
        handles = list(driver.window_handles or [])
        switched = False
        if tid and handles:
            for h in handles:
                hs = str(h or "")
                if hs == tid or tid in hs or hs.endswith(tid) or hs.replace("CDwindow-", "") == tid:
                    driver.switch_to.window(h)
                    switched = True
                    break
        if not switched and handles:
            driver.switch_to.window(handles[-1])
        try:
            cur = str(driver.current_url or "")
        except Exception:
            cur = ""
        # 若可见页签仍不是目标域，再 Selenium get 一次（保证你能看见打开）
        want = (url.split("://", 1)[-1].split("/", 1)[0] or "").lower()
        if want and want not in cur.lower():
            print(f"[WARN] 末页签 URL 不匹配（{cur[:60] or '空'}），Selenium 再 get 一次")
            driver.get(url)
            try:
                cur = str(driver.current_url or "")
            except Exception:
                cur = ""
        print(f"[OK] 已切到可见末页签，Selenium current_url={cur[:120] or '(空)'}")
        return
    except Exception as e:
        print(f"[WARN] 静默 CDP 导航失败，尝试还焦回退: {e}")
        try:
            set_binding(driver, None)
        except Exception:
            pass

        try:
            handles = list(driver.window_handles or [])
        except Exception:
            handles = []
        if not handles:
            try:
                driver.execute_cdp_cmd(
                    "Target.createTarget",
                    {"url": "about:blank", "background": True},
                )
                time.sleep(0.15)
                handles = list(driver.window_handles or [])
            except Exception:
                pass
        if handles:
            try:
                driver.switch_to.window(handles[-1])
            except Exception:
                pass
        try:
            driver.get(url)
            print(f"[OK] Selenium 回退已打开: {url[:80]}")
        except Exception as e2:
            print(f"[ERROR] 导航失败: {e2}")
            raise
    finally:
        restore_os_focus(prev_focus)


def init_browser(use_remote_debugging: Optional[bool] = None):
    """
    初始化浏览器。

    :param use_remote_debugging: 是否连接已开启远程调试的 Chrome。
        None 时使用 config 中的 USE_REMOTE_DEBUGGING。
    """
    try:
        remote = USE_REMOTE_DEBUGGING if use_remote_debugging is None else use_remote_debugging
        # 如果使用远程调试模式，连接到已运行的Chrome
        if remote:
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
            
            # 连接后不 switch_to，避免抢焦点；具体打开 URL 时走静默 CDP
            print("[OK] 成功连接到已运行的Chrome浏览器（不抢焦点）")
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
        # TradingView 图表资源/脚本较多，建议额外等待渲染稳定后再截图
        # 可通过环境变量 TRADINGVIEW_SCREENSHOT_WAIT 覆盖（秒），默认 10
        try:
            extra_wait = int(os.getenv("TRADINGVIEW_SCREENSHOT_WAIT", "10"))
        except Exception:
            extra_wait = 20
        if extra_wait > 0:
            time.sleep(extra_wait)
        
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
                time.sleep(15)  # 等待15秒后再开始截图
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
    """
    使用 Gemini 网页版进行分析（模拟用户上传、填词、发送、抓取回复）。
    核心实现位于 gemini_web_automation 模块，便于单独维护与复用。
    """
    from gemini_web_automation import analyze_with_gemini_web as _gemini_web_run
    return _gemini_web_run(image_path, symbol, prompt)

