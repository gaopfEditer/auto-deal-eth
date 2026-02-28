"""
使用 Playwright 或 Selenium 将 screenshots/chart_15m.png 上传到 Gemini 网页进行分析

说明: Playwright Chromium 每次都是临时实例，登录/数据不会保留。
      USE_CHROME_CDP=1 时使用 Selenium 直连 Chrome（debugger_address），
      不依赖 /json/version，可保留登录态。

【重要】Chrome 136+ 使用默认 User Data 时 --remote-debugging-port 会被忽略，
       必须用 run_chrome_for_debug.ps1 启动（非默认 user-data-dir）。

【推荐】连接已运行的 Chrome（保留登录态）:
  1. 关闭所有 Chrome，运行 test/run_chrome_for_debug.ps1
  2. 首次在 ChromeDebug 中登录 Gemini
  3. 运行: $env:USE_CHROME_CDP="1"; python test/test_gemini_upload_playwright.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

GEMINI_URL = "https://gemini.google.com/app/539fbc616d553205"
IMAGE_PATH = os.path.join(ROOT, "screenshots", "chart_15m.png")


def _run_gemini_upload_selenium():
    """USE_CHROME_CDP=1 时用 Selenium 连接 Chrome（不依赖 /json/version）"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
    except ImportError:
        print("[WARN] 需要 selenium，运行: pip install selenium webdriver-manager")
        return False

    try:
        from config import CHROME_DEBUG_PORT
    except ImportError:
        CHROME_DEBUG_PORT = 9222

    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    except Exception:
        driver = webdriver.Chrome(options=opts)

    try:
        driver.get(GEMINI_URL)
        time.sleep(5)
        # 查找文件输入框
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if file_inputs:
            file_inputs[0].send_keys(IMAGE_PATH)
        else:
            add_btns = driver.find_elements(By.XPATH, "//*[contains(text(),'添加文件') or contains(text(),'Add file')]")
            if add_btns:
                add_btns[0].click()
                time.sleep(1.5)
            upload_btns = driver.find_elements(By.XPATH, "//*[contains(text(),'上传文件') or contains(text(),'Upload file')]")
            if upload_btns:
                upload_btns[0].click()
                time.sleep(1)
            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if file_inputs:
                file_inputs[0].send_keys(IMAGE_PATH)
        time.sleep(5)
        print("图片已上传，等待 Gemini 分析...")
        time.sleep(10)
        print("完成")
    except Exception as e:
        print(f"[WARN] {e}")
        import traceback
        traceback.print_exc()
    finally:
        pass  # 不关闭 driver，保留 Chrome 给用户

    return True


def _get_chrome_context(playwright):
    """获取带 Chrome 用户配置的浏览器上下文
    返回 (context, close_fn, page_or_none): page_or_none 非空时直接使用该页面，不可 new_page
    """
    try:
        from config import CHROME_USER_DATA_DIR, CHROME_PROFILE_NAME, CHROME_DEBUG_PORT
    except ImportError:
        CHROME_USER_DATA_DIR = ""
        CHROME_PROFILE_NAME = "Profile 1"
        CHROME_DEBUG_PORT = 9222

    use_cdp = os.getenv("USE_CHROME_CDP", "").lower() in ("1", "true")
    if use_cdp:
        import json
        import urllib.request

        base_url = f"http://127.0.0.1:{CHROME_DEBUG_PORT}"
        last_err = None

        # 1) 直接从 9222/json 取 ws URL 连接（绕过 /json/version 的 400）
        ws_url = None
        try:
            req = urllib.request.urlopen(f"{base_url}/json", timeout=5)
            data = json.loads(req.read().decode())
            if isinstance(data, list) and data:
                ws_url = data[0].get("webSocketDebuggerUrl")
            elif isinstance(data, dict):
                ws_url = data.get("webSocketDebuggerUrl")
        except Exception as e:
            last_err = e
        if ws_url:
            ws_url = ws_url.replace("localhost", "127.0.0.1")
            try:
                browser = playwright.chromium.connect_over_cdp(ws_url)
                page = None
                for c in browser.contexts:
                    if c.pages:
                        page = c.pages[0]
                        break
                if page is not None:
                    return page.context, None, page
                last_err = Exception("Chrome 无可用页面，请先打开至少一个标签页")
            except Exception as e:
                last_err = e

        # 2) 启动 cdp_proxy 子进程（监听 9223），再通过 HTTP 连接
        proxy_port = CHROME_DEBUG_PORT + 1  # 9223
        cdp_proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdp_proxy.py")
        proc = None
        try:
            import subprocess
            proc = subprocess.Popen(
                [sys.executable, cdp_proxy_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=ROOT,
            )
            for _ in range(20):
                time.sleep(0.25)
                try:
                    r = urllib.request.urlopen(f"http://127.0.0.1:{proxy_port}/json", timeout=1)
                    r.read()
                    break
                except Exception:
                    pass
            else:
                raise RuntimeError("cdp_proxy 未就绪")
            proxy_url = f"http://127.0.0.1:{proxy_port}"
            browser = playwright.chromium.connect_over_cdp(proxy_url)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            return ctx, (lambda: proc.terminate() if proc else None), None
        except Exception as e:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            last_err = e

        print(f"[WARN] 连接 Chrome CDP 失败: {last_err}")
        print("  请用非默认目录启动（ChromeDebug），参见本文件开头说明。")

    return None, None, None


def run_gemini_upload():
    """使用 Playwright 或 Selenium 打开 Gemini，上传 chart_15m.png 进行分析"""
    if not os.path.exists(IMAGE_PATH):
        print(f"[ERROR] 图片不存在: {IMAGE_PATH}")
        return False

    # USE_CHROME_CDP=1 时用 Selenium 直连，完全绕过 Playwright 的 /json/version 400 问题
    if os.getenv("USE_CHROME_CDP", "").lower() in ("1", "true"):
        print(f"使用 Selenium 连接已启动的 Chrome...")
        print(f"URL: {GEMINI_URL}")
        print(f"图片: {IMAGE_PATH}")
        return _run_gemini_upload_selenium()

    from playwright.sync_api import sync_playwright

    print(f"正在使用 Playwright 打开 Gemini...")
    print(f"URL: {GEMINI_URL}")
    print(f"图片: {IMAGE_PATH}")

    with sync_playwright() as p:
        ctx, close_fn, page_or_none = _get_chrome_context(p)
        if ctx is None:
            print("[INFO] 使用 Playwright Chromium（建议用 USE_CHROME_CDP=1 连接已启动的 Chrome）")
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-automation",
                ],
            )
            ctx = browser.new_context(
                ignore_https_errors=False,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            close_fn = lambda: browser.close()
            page_or_none = None

        if page_or_none is not None:
            page = page_or_none
            page.bring_to_front()
        else:
            page = ctx.new_page()
        page.set_default_timeout(0)

        try:
            print("正在导航到 Gemini...", flush=True)
            page.goto(GEMINI_URL, wait_until="commit", timeout=60000)
            print("导航完成，等待页面加载...", flush=True)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

            # 策略1: 直接查找 input[type='file'] 并上传
            file_input = page.locator("input[type='file']")
            if file_input.count() > 0:
                print("找到 input[type='file']，直接 set_input_files...")
                file_input.first.set_input_files(IMAGE_PATH)
            else:
                # 策略2: 点击 "添加文件" 打开浮窗，再点击 "上传文件" 触发文件选择
                add_loc = page.get_by_text("添加文件").or_(page.get_by_text("Add file"))
                if add_loc.count() > 0:
                    print("找到添加文件按钮，点击...")
                    add_loc.first.click()
                    page.wait_for_timeout(1500)

                upload_loc = page.get_by_text("上传文件").or_(page.get_by_text("Upload file"))
                if upload_loc.count() > 0:
                    print("找到上传文件按钮，使用 expect_file_chooser 上传...")
                    with page.expect_file_chooser(timeout=0) as fc_info:
                        upload_loc.first.click()
                    fc_info.value.set_files(IMAGE_PATH)
                else:
                    # 策略3: 任意可点击元素触发 file chooser
                    file_input = page.locator("input[type='file']")
                    if file_input.count() > 0:
                        file_input.first.set_input_files(IMAGE_PATH)
                    else:
                        with page.expect_file_chooser(timeout=0) as fc_info:
                            page.locator("[aria-label*='upload'], [aria-label*='Upload'], [aria-label*='添加']").first.click()
                        fc_info.value.set_files(IMAGE_PATH)

            page.wait_for_timeout(5000)
            print("图片已上传，等待 Gemini 分析...")
            page.wait_for_timeout(10000)
            print("完成")

        except Exception as e:
            print(f"[WARN] {e}")
            if "Timeout" in str(e):
                print("[提示] 自动操作超时，可手动上传图片后按回车继续，或直接关闭浏览器退出")
                try:
                    input("按回车关闭...")
                except (EOFError, KeyboardInterrupt):
                    pass
            elif "ERR_CONNECTION_CLOSED" in str(e) or "net::" in str(e):
                print("[提示] Gemini 可能限制自动化浏览器，建议使用 USE_CHROME_CDP=1 连接已启动的 Chrome")
            import traceback
            traceback.print_exc()
        finally:
            if close_fn:
                close_fn()

    return True


if __name__ == "__main__":
    run_gemini_upload()
