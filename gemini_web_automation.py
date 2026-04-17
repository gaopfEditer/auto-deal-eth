"""
Gemini web UI automation: simulate user upload, prompt, send, poll reply.

This is the core browser flow for gemini.google.com (not TradingView/screenshots).
Use: ``from gemini_web_automation import analyze_with_gemini_web``
or ``browser_automation.analyze_with_gemini_web`` (thin wrapper).
"""
from __future__ import annotations

import base64
import os
import random
import sys
import tempfile
import time
import uuid
from io import BytesIO
from typing import Any, Dict, Optional, Union

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def analyze_with_gemini_web(
    image_path: str,
    symbol: str,
    prompt: Optional[str] = None,
    *,
    keep_browser_open: bool = True,
    clipboard_only: bool = False,
    use_clipboard_upload: bool = False,
):
    """Gemini web: open session, upload image, inject prompt, send, scrape reply.

    clipboard_only: 仅通过剪贴板粘贴图片，不查找 ``input[type=file]`` /「上传文件」等 UI。
    """
    from browser_automation import init_browser

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
            from gemini_analyzer import get_kline_analysis_prompt

            default_prompt = get_kline_analysis_prompt(symbol, multi_timeframe=False)
        
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
            time.sleep(7)
            
            # 尝试查找上传图片的按钮或区域
            # Gemini 网页版需要先点击"添加文件"按钮，然后在浮窗中点击"上传文件"
            file_input = None
            pasted_upload = False

            def _try_paste_image_via_clipboard(img_path: str) -> bool:
                """
                优先走剪贴板粘贴上传（Windows）。
                成功后可跳过“添加文件/上传文件”按钮定位流程。
                """
                print(f"  [INFO] 尝试剪贴板上传: {img_path}")
                if os.name != "nt":
                    print("  [INFO] 非 Windows 环境，跳过剪贴板上传")
                    return False
                if not os.path.isfile(img_path):
                    print("  [WARNING] 图片文件不存在，无法剪贴板上传")
                    return False

                def _set_file_clipboard_via_ctypes(file_path: str) -> bool:
                    """零依赖：使用 ctypes 写入 CF_HDROP（文件剪贴板）。"""
                    try:
                        import ctypes
                        from ctypes import wintypes

                        class POINT(ctypes.Structure):
                            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

                        class DROPFILES(ctypes.Structure):
                            _fields_ = [
                                ("pFiles", wintypes.DWORD),
                                ("pt", POINT),
                                ("fNC", wintypes.BOOL),
                                ("fWide", wintypes.BOOL),
                            ]

                        CF_HDROP = 15
                        GMEM_MOVEABLE = 0x0002
                        GMEM_ZEROINIT = 0x0040
                        GHND = GMEM_MOVEABLE | GMEM_ZEROINIT

                        user32 = ctypes.windll.user32
                        kernel32 = ctypes.windll.kernel32

                        # 双零结尾的 UTF-16LE 文件路径列表（可支持多文件，这里只放一个）
                        payload = (file_path + "\0\0").encode("utf-16le")
                        header = DROPFILES()
                        header.pFiles = ctypes.sizeof(DROPFILES)
                        header.pt = POINT(0, 0)
                        header.fNC = False
                        header.fWide = True

                        total_size = ctypes.sizeof(DROPFILES) + len(payload)
                        hmem = kernel32.GlobalAlloc(GHND, total_size)
                        if not hmem:
                            return False
                        ptr = kernel32.GlobalLock(hmem)
                        if not ptr:
                            kernel32.GlobalFree(hmem)
                            return False
                        try:
                            ctypes.memmove(ptr, ctypes.byref(header), ctypes.sizeof(DROPFILES))
                            ctypes.memmove(
                                ptr + ctypes.sizeof(DROPFILES), payload, len(payload)
                            )
                        finally:
                            kernel32.GlobalUnlock(hmem)

                        if not user32.OpenClipboard(None):
                            kernel32.GlobalFree(hmem)
                            return False
                        try:
                            user32.EmptyClipboard()
                            if not user32.SetClipboardData(CF_HDROP, hmem):
                                kernel32.GlobalFree(hmem)
                                return False
                            # 成功后所有权转移给系统，不再手动 free
                            hmem = None
                            return True
                        finally:
                            user32.CloseClipboard()
                    except Exception as e:
                        print(f"  [DEBUG] ctypes 写文件到剪贴板失败: {e}")
                        return False

                try:
                    import win32clipboard  # type: ignore
                    from PIL import Image
                except Exception:
                    print("  [INFO] 缺少 pywin32/Pillow，回退 ctypes 文件剪贴板方案")
                    if not _set_file_clipboard_via_ctypes(img_path):
                        print("  [WARNING] ctypes 文件剪贴板写入失败")
                        return False
                    print("  [OK] 已通过 ctypes 写入文件到系统剪贴板")
                    # 复用下方粘贴逻辑：只需标记已写剪贴板即可
                    try:
                        body = driver.find_element(By.TAG_NAME, "body")
                        body.click()
                    except Exception:
                        pass
                    pasted = False
                    try:
                        import pyautogui  # type: ignore

                        pyautogui.PAUSE = 0.1
                        pyautogui.hotkey("ctrl", "v")
                        pasted = True
                        print("  [INFO] 已执行 pyautogui Ctrl+V")
                    except Exception as e:
                        print(f"  [DEBUG] pyautogui Ctrl+V 失败，回退 ActionChains: {e}")
                        try:
                            ActionChains(driver).key_down(Keys.CONTROL).send_keys("v").key_up(
                                Keys.CONTROL
                            ).perform()
                            pasted = True
                            print("  [INFO] 已执行 ActionChains Ctrl+V")
                        except Exception as e2:
                            print(f"  [DEBUG] ActionChains Ctrl+V 失败: {e2}")
                            pasted = False
                    if not pasted:
                        return False
                    try:
                        WebDriverWait(driver, 8).until(
                            lambda d: _has_uploaded_attachment_signal()
                        )
                    except Exception:
                        pass
                    if _has_uploaded_attachment_signal():
                        print("  [OK] 文件剪贴板粘贴上传已验证成功（检测到附件信号）")
                        return True
                    print("  [WARNING] 已执行文件粘贴，但未检测到附件信号")
                    return False

                def _has_uploaded_attachment_signal() -> bool:
                    selectors = [
                        "img[src^='blob:']",
                        "img[src^='data:image']",
                        "button[aria-label*='移除']",
                        "button[aria-label*='Remove']",
                        "[class*='upload'] img",
                        "[class*='attachment'] img",
                    ]
                    for sel in selectors:
                        try:
                            els = driver.find_elements(By.CSS_SELECTOR, sel)
                            if els:
                                return True
                        except Exception:
                            continue
                    return False

                try:
                    # 写入剪贴板（CF_DIB 需要去掉 BMP 头 14 字节）
                    img = Image.open(img_path).convert("RGB")
                    bio = BytesIO()
                    img.save(bio, format="BMP")
                    dib = bio.getvalue()[14:]
                    bio.close()

                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
                    finally:
                        win32clipboard.CloseClipboard()
                    print("  [OK] 图片已写入系统剪贴板")

                    # 聚焦页面并粘贴
                    try:
                        body = driver.find_element(By.TAG_NAME, "body")
                        body.click()
                    except Exception:
                        pass
                    pasted = False
                    # 优先真实键盘热键（更接近用户操作）
                    try:
                        import pyautogui  # type: ignore

                        pyautogui.PAUSE = 0.1
                        pyautogui.hotkey("ctrl", "v")
                        pasted = True
                        print("  [INFO] 已执行 pyautogui Ctrl+V")
                    except Exception as e:
                        print(f"  [DEBUG] pyautogui Ctrl+V 失败，回退 ActionChains: {e}")
                        try:
                            ActionChains(driver).key_down(Keys.CONTROL).send_keys("v").key_up(
                                Keys.CONTROL
                            ).perform()
                            pasted = True
                            print("  [INFO] 已执行 ActionChains Ctrl+V")
                        except Exception as e2:
                            print(f"  [DEBUG] ActionChains Ctrl+V 失败: {e2}")
                            pasted = False

                    if not pasted:
                        return False

                    # 粘贴后验证是否出现附件信号
                    try:
                        WebDriverWait(driver, 8).until(
                            lambda d: _has_uploaded_attachment_signal()
                        )
                    except Exception:
                        pass
                    if _has_uploaded_attachment_signal():
                        print("  [OK] 剪贴板粘贴上传已验证成功（检测到附件信号）")
                        return True
                    print("  [WARNING] 已执行粘贴，但未检测到附件信号")
                    return False
                except Exception as e:
                    print(f"  [DEBUG] 剪贴板粘贴上传失败: {e}")
                    return False

            abs_img = os.path.abspath(image_path)
            # 默认关闭剪贴板上传，按用户要求走“上传按钮->上传文件”流程
            if use_clipboard_upload:
                pasted_upload = _try_paste_image_via_clipboard(abs_img)
            if clipboard_only:
                if not use_clipboard_upload:
                    raise RuntimeError(
                        "clipboard_only=True 但 use_clipboard_upload=False，配置冲突"
                    )
                if not pasted_upload:
                    time.sleep(1.2)
                    pasted_upload = _try_paste_image_via_clipboard(abs_img)
                if not pasted_upload:
                    raise RuntimeError(
                        "clipboard_only: 剪贴板粘贴上传失败（未检测到附件），"
                        "已跳过文件选择/上传按钮流程"
                    )
                file_input = None
                print("  [INFO] clipboard_only=True：仅剪贴板贴图，不探测上传文件按钮")

            def _dismiss_upload_intercept_confirm() -> bool:
                """
                某些账号/场景下，Gemini 会在添加文件后弹确认拦截层（如“确定/继续”）。
                尝试自动点击一次，避免流程卡住。
                """
                texts = (
                    "确定",
                    "继续",
                    "允许",
                    "我知道了",
                    "继续上传",
                    "confirm",
                    "continue",
                    "allow",
                    "ok",
                )
                clicked = False
                for t in texts:
                    xpath = (
                        # 仅在弹层/对话框上下文中查找确认按钮，避免误点页面普通“ok”
                        "//*[self::div or @role='dialog' or contains(@class,'dialog') or contains(@class,'modal')"
                        " or contains(@class,'popover') or contains(@class,'menu')]"
                        "//*[self::button or @role='button']"
                        f"[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{t.lower()}')]"
                    )
                    try:
                        btn = WebDriverWait(driver, 0.8).until(
                            EC.element_to_be_clickable((By.XPATH, xpath))
                        )
                        label = (btn.text or btn.get_attribute("aria-label") or "").strip()
                        if not label:
                            continue
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", btn
                        )
                        time.sleep(0.15)
                        try:
                            btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", btn)
                        print(f"  [INFO] 已处理上传拦截确认：query={t} label={label}")
                        clicked = True
                        time.sleep(0.4)
                        break
                    except Exception:
                        continue
                return clicked

            def _drain_upload_intercepts(max_rounds: int = 4, gap_sec: float = 0.35) -> int:
                """
                连续清理上传拦截弹窗：有些场景会连弹 2-3 层确认。
                返回成功点击次数，便于日志观察是否被 Gemini 拦截。
                """
                clicks = 0
                for _ in range(max_rounds):
                    if not _dismiss_upload_intercept_confirm():
                        break
                    clicks += 1
                    time.sleep(gap_sec)
                if clicks > 0:
                    print(f"  [INFO] 已连续处理上传拦截弹窗: {clicks} 次")
                return clicks
            
            # 方法1: 直接查找文件输入框（可能隐藏）
            if not pasted_upload:
                try:
                    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    if file_inputs:
                        file_input = file_inputs[0]
                        print(f"  [INFO] 找到隐藏的文件输入框")
                except Exception:
                    pass
            
            # 方法2: 先点击"添加文件"按钮，然后在浮窗中点击"上传文件"
            if not clipboard_only and not file_input and not pasted_upload:
                try:
                    # 步骤1: 查找并点击"添加文件"按钮（或类似的按钮）
                    add_file_button = None
                    add_file_selectors = [
                        # Gemini 现网常见：加号按钮（Material），打开 upload-file-menu
                        "button.upload-card-button[aria-controls='upload-file-menu']",
                        "button.upload-card-button[aria-label='打开文件上传菜单']",
                        "button.upload-card-button",
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
                                _drain_upload_intercepts()
                                print(f"  [OK] 已点击添加文件按钮")
                                # 等待菜单展开（aria-expanded 或菜单容器出现）
                                try:
                                    WebDriverWait(driver, 10).until(
                                        lambda d: (
                                            (add_file_button.get_attribute("aria-expanded") or "").strip().lower() in ("true", "1")
                                            or len(d.find_elements(By.CSS_SELECTOR, "#upload-file-menu, [id='upload-file-menu'], [aria-controls='upload-file-menu'][aria-expanded='true']")) > 0
                                        )
                                    )
                                except Exception:
                                    # 给一点缓冲，避免后续立刻查找菜单项
                                    time.sleep(0.8)
                                # 菜单展开后再清一轮确认层，避免遮挡“上传文件”菜单项
                                _drain_upload_intercepts(max_rounds=2, gap_sec=0.25)
                                break
                        except:
                            continue
                    
                    if not add_file_button:
                        print(f"  [WARNING] 未找到添加文件按钮，尝试直接查找上传文件按钮")
                    
                    def _is_upload_menu_open() -> bool:
                        try:
                            menu_els = driver.find_elements(
                                By.CSS_SELECTOR,
                                "#upload-file-menu, [id='upload-file-menu'], .mdc-menu-surface--open",
                            )
                            if menu_els:
                                return True
                        except Exception:
                            pass
                        try:
                            items = driver.find_elements(
                                By.XPATH,
                                "//*[contains(@class, 'mdc-list-item') and .//div[contains(text(), '上传文件')]]"
                                " | //div[contains(@class, 'menu-text') and contains(text(), '上传文件')]",
                            )
                            return len(items) > 0
                        except Exception:
                            return False

                    def _ensure_upload_menu_open() -> bool:
                        if _is_upload_menu_open():
                            return True
                        if not add_file_button:
                            return False
                        try:
                            print("  [INFO] 检测到下拉已消失，重新点击添加文件按钮展开菜单")
                            driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});",
                                add_file_button,
                            )
                            time.sleep(0.2)
                            try:
                                add_file_button.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", add_file_button)
                            _drain_upload_intercepts(max_rounds=2, gap_sec=0.2)
                            WebDriverWait(driver, 4).until(lambda d: _is_upload_menu_open())
                            return True
                        except Exception:
                            return False

                    def _find_upload_menu_item():
                        # 仅在菜单容器内找“上传文件”项，避免全局误匹配
                        xps = [
                            "//*[@id='upload-file-menu']//*[self::button or @role='button' or contains(@class,'mdc-list-item')]"
                            "[.//text()[contains(.,'上传文件')] or contains(.,'上传文件') or contains(.,'Upload file') or contains(.,'Upload files')]",
                            "//*[contains(@class,'mdc-menu-surface--open')]//*[self::button or @role='button' or contains(@class,'mdc-list-item')]"
                            "[.//text()[contains(.,'上传文件')] or contains(.,'上传文件') or contains(.,'Upload file') or contains(.,'Upload files')]",
                        ]
                        for xp in xps:
                            try:
                                candidates = driver.find_elements(By.XPATH, xp)
                                for el in candidates:
                                    if not el.is_displayed():
                                        continue
                                    text = (el.text or el.get_attribute("aria-label") or "").strip()
                                    if "上传文件" in text or "Upload file" in text or "Upload files" in text:
                                        return el
                            except Exception:
                                continue
                        return None

                    # 步骤2: 菜单保持打开状态下，立即查找并点击“上传文件”
                    if add_file_button:
                        if not _ensure_upload_menu_open():
                            print("  [WARNING] 添加文件下拉菜单未保持打开")
                        
                        # 查找"上传文件"按钮
                        upload_button = None
                        try:
                            WebDriverWait(driver, 3).until(lambda d: _is_upload_menu_open())
                            upload_button = _find_upload_menu_item()
                            if upload_button:
                                u_text = (upload_button.text or upload_button.get_attribute("aria-label") or "").strip()
                                print(f"  [OK] 菜单内定位到上传文件项: text={u_text}")
                        except Exception:
                            pass
                        
                        if upload_button:
                            # 点击前再次确认菜单没消失，避免拿到陈旧元素
                            if not _ensure_upload_menu_open():
                                print("  [WARNING] 点击上传文件前菜单已关闭，放弃本轮点击")
                                upload_button = None
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
                                _drain_upload_intercepts(max_rounds=3, gap_sec=0.25)
                                # 等待文件选择对话框/文件输入框出现（比固定 sleep 更稳）
                                try:
                                    WebDriverWait(driver, 10).until(
                                        lambda d: d.find_elements(By.CSS_SELECTOR, "input[type='file']")
                                    )
                                except Exception:
                                    pass

                                # 验证是否真的点击成功（检查是否出现文件输入框）
                                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                                if file_inputs:
                                    file_input = file_inputs[0]
                                    print(f"  [OK] 上传文件项点击成功，已出现文件输入框")
                                else:
                                    print(f"  [WARNING] 上传文件项已点击，但未出现文件输入框")
                            except ImportError:
                                print(f"  [WARNING] pyautogui 未安装，尝试其他方法")
                                # 回退到普通点击
                                upload_button.click()
                                _drain_upload_intercepts(max_rounds=3, gap_sec=0.25)
                                time.sleep(2)
                                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                                if file_inputs:
                                    file_input = file_inputs[0]
                            except Exception as e:
                                print(f"  [DEBUG] pyautogui 点击失败: {e}")
                        else:
                            print(f"  [WARNING] 菜单已开但未定位到“上传文件”项（本轮不做后续上传）")
                            
                except Exception as e:
                    print(f"  [DEBUG] 通过添加文件按钮流程失败: {e}")
            
            # 方法3: 直接通过文本内容查找"上传文件"按钮（如果浮窗已经打开）
            if not file_input and not pasted_upload:
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
            if not file_input and not pasted_upload:
                def _locate_file_input_after_click(wait_sec: int = 3):
                    # 先用常规选择器等待，再做一次 JS 全量扫描（兼容 display:none/复杂 DOM）
                    try:
                        file_inputs_wait = WebDriverWait(driver, wait_sec).until(
                            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']"))
                        )
                        if file_inputs_wait:
                            return file_inputs_wait[0]
                    except Exception:
                        pass
                    try:
                        js_input = driver.execute_script(
                            "return document.querySelector('input[type=\"file\"]');"
                        )
                        if js_input is not None:
                            return js_input
                    except Exception:
                        pass
                    return None

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
                        # 验证是否真的点击成功（常规查找 + JS 扫描）
                        found_input = _locate_file_input_after_click(wait_sec=2)
                        if found_input:
                            file_input = found_input
                            print(f"  [OK] 点击成功，找到文件输入框")
                            break
                        else:
                            print(f"  [WARNING] 点击后未找到文件输入框，继续尝试其他选择器")
                    except Exception as e:
                        # 不输出错误，静默继续
                        continue
            
            # 方法4: 再次查找文件输入框（可能在点击后出现）
            if not file_input and not pasted_upload:
                try:
                    file_input = _locate_file_input_after_click(wait_sec=3)
                    if file_input:
                        print(f"  [INFO] 最终找到文件输入框")
                except:
                    pass

            # 方法5: 若点击“上传文件”失效，则重新点击 file-uploader 展开下拉后再点“上传文件”
            if not file_input and not pasted_upload:
                def _reopen_uploader_and_click_upload_once() -> bool:
                    trigger_selectors = [
                        "#file-uploader",
                        "file-uploader",
                        "[id*='file-uploader']",
                        "button.upload-card-button[aria-controls='upload-file-menu']",
                        "button.upload-card-button",
                        "[data-testid='add-file-button']",
                    ]
                    trigger = None
                    for sel in trigger_selectors:
                        try:
                            trigger = WebDriverWait(driver, 2).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                            )
                            if trigger:
                                print(f"  [INFO] 找到 file-uploader 触发器: {sel}")
                                break
                        except Exception:
                            continue
                    if not trigger:
                        return False

                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", trigger)
                    except Exception:
                        pass

                    clicked = False
                    try:
                        trigger.click()
                        clicked = True
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", trigger)
                            clicked = True
                        except Exception:
                            clicked = False
                    if not clicked:
                        return False

                    _drain_upload_intercepts(max_rounds=3, gap_sec=0.25)
                    time.sleep(0.5)

                    upload_btn = None
                    upload_btn_xpaths = [
                        "//*[contains(@class, 'mdc-list-item') and .//div[contains(text(), '上传文件')]]",
                        "//*[contains(@class, 'list-item') and .//*[contains(text(), '上传文件')]]",
                        "//div[contains(@class, 'menu-text') and contains(text(), '上传文件')]",
                        "//span[contains(text(), '上传文件')]",
                        "//*[self::button or @role='button'][contains(., '上传文件') or contains(., 'Upload files') or contains(., 'Upload file')]",
                    ]
                    for xp in upload_btn_xpaths:
                        try:
                            upload_btn = WebDriverWait(driver, 2).until(
                                EC.presence_of_element_located((By.XPATH, xp))
                            )
                            if upload_btn:
                                print("  [INFO] 重新展开后找到“上传文件”菜单项")
                                break
                        except Exception:
                            continue
                    if not upload_btn:
                        return False

                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", upload_btn)
                    except Exception:
                        pass
                    try:
                        upload_btn.click()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", upload_btn)
                        except Exception:
                            return False
                    _drain_upload_intercepts(max_rounds=3, gap_sec=0.25)
                    time.sleep(0.8)
                    return True

                max_reopen_retries = 3
                for i in range(1, max_reopen_retries + 1):
                    print(f"  [INFO] 上传入口重试({i}/{max_reopen_retries})：重新展开 file-uploader")
                    ok = _reopen_uploader_and_click_upload_once()
                    if not ok:
                        print("  [WARNING] 重新展开或点击“上传文件”失败")
                        continue
                    file_input = _locate_file_input_after_click(wait_sec=2)
                    if file_input:
                        print("  [OK] 重试后拿到文件输入框")
                        break
                    print("  [WARNING] 重试后仍未拿到文件输入框，将继续下一轮")

            # 方法6: 点击链路失败时，直接走剪贴板上传兜底（更贴近 Gemini 网页真实交互）
            if not file_input and not pasted_upload:
                try:
                    print("  [INFO] 未拿到文件输入框，尝试剪贴板粘贴上传兜底...")
                    pasted_upload = _try_paste_image_via_clipboard(image_path)
                    if pasted_upload:
                        print("  [OK] 剪贴板上传兜底成功")
                except Exception as e:
                    print(f"  [WARNING] 剪贴板上传兜底失败: {e}")
            
            if pasted_upload:
                print("  ✓ 已通过剪贴板粘贴完成图片上传")
            elif file_input:
                print(f"  正在上传图片: {image_path}")
                # 上传图片
                abs_image_path = os.path.abspath(image_path)
                file_input.send_keys(abs_image_path)
                time.sleep(5)  # 等待图片上传和处理
                print(f"  ✓ 图片上传成功")
                # 上传后主动关闭可能残留的上传下拉/浮层，避免遮挡后续输入
                try:
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                except Exception:
                    pass
                try:
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.click()
                except Exception:
                    pass
                try:
                    still_open = driver.find_elements(
                        By.CSS_SELECTOR,
                        "#upload-file-menu, [id='upload-file-menu'], .mdc-menu-surface--open",
                    )
                    if still_open:
                        print("  [WARNING] 上传后菜单仍可见，已尝试 ESC/点击空白关闭")
                    else:
                        print("  [INFO] 上传后已关闭文件选择相关浮层")
                except Exception:
                    pass
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
                # 清空并输入提示词（并确保输入框获得焦点）
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", text_input)
                except Exception:
                    pass
                try:
                    text_input.click()
                except Exception:
                    try:
                        driver.execute_script("arguments[0].focus();", text_input)
                    except Exception:
                        pass
                # 长 prompt 不用 send_keys 逐字敲（慢、易触发风控/卡顿），改为 JS 直接注入 + 触发事件
                try:
                    driver.execute_script(
                        """
                        var el = arguments[0];
                        var v = arguments[1] || '';
                        try {
                          // textarea / input
                          if (el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && (el.type || '') !== 'file'))) {
                            el.value = v;
                          } else if (el && el.isContentEditable) {
                            // contenteditable
                            el.innerText = v;
                          } else {
                            // 兜底
                            try { el.value = v; } catch (e) {}
                            try { el.innerText = v; } catch (e) {}
                          }
                          // 触发前端监听（Angular/React）
                          el.dispatchEvent(new Event('input', { bubbles: true }));
                          el.dispatchEvent(new Event('change', { bubbles: true }));
                          el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: ' ' }));
                        } catch (e) {}
                        """,
                        text_input,
                        analysis_prompt,
                    )
                    # 轻触发一次，让某些站点从“禁用发送”变为可发送
                    text_input.send_keys(" ")
                except Exception:
                    # JS 注入失败再回退到 send_keys（尽量短）
                    try:
                        text_input.clear()
                    except Exception:
                        pass
                    text_input.send_keys(analysis_prompt)

                # Gemini 的“发送”按钮经常先禁用，且可能被 mic 图标层拦截点击
                # 1) 优先等按钮变为可点（aria-disabled != true）
                send_button = None
                try:
                    send_button = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button.send-button, button[aria-label='发送'], button[aria-label*='Send'], button[type='submit']"))
                    )
                except Exception:
                    send_button = None

                def _send_button_ready(btn):
                    try:
                        if not btn:
                            return False
                        aria = (btn.get_attribute("aria-disabled") or "").strip().lower()
                        if aria in ("true", "1"):
                            return False
                        return btn.is_enabled()
                    except Exception:
                        return False

                sent = False
                if send_button:
                    try:
                        WebDriverWait(driver, 12).until(lambda d: _send_button_ready(send_button))
                    except Exception:
                        pass

                    if _send_button_ready(send_button):
                        try:
                            send_button.click()
                            sent = True
                        except Exception:
                            # 2) click 被拦截时，用 JS 点击兜底
                            try:
                                driver.execute_script("arguments[0].click();", send_button)
                                sent = True
                            except Exception:
                                sent = False

                if not sent:
                    # 3) 最稳：在输入框里按 Enter 发送（多数聊天框支持）
                    try:
                        text_input.click()
                    except Exception:
                        pass
                    text_input.send_keys(Keys.RETURN)
                    sent = True

                print(f"  ✓ 已发送分析请求")
            else:
                print(f"  [WARNING] 未找到输入框，尝试使用键盘输入...")
                # 尝试使用 ActionChains 点击页面并输入
                actions = ActionChains(driver)
                actions.send_keys(analysis_prompt)
                actions.send_keys(Keys.RETURN)
                actions.perform()
            
            # 等待分析结果（仅抓取“最新一条回复节点”，不再回退整页 body 文本）
            print(f"  等待分析结果...")
            try:
                max_wait = int(os.getenv("GEMINI_WEB_RESULT_WAIT", "180"))
            except Exception:
                max_wait = 180
            try:
                stable_sec = int(os.getenv("GEMINI_WEB_RESULT_STABLE", "4"))
            except Exception:
                stable_sec = 4

            result_selectors = [
                ".response",
                "[data-testid='response']",
                ".message-content",
                ".gemini-response",
                "div[class*='response']",
                "div[class*='message']",
            ]

            def _latest_reply_text() -> str:
                # 只取最新一条回复节点，避免把整页内容拼进来
                for selector in result_selectors:
                    try:
                        els = driver.find_elements(By.CSS_SELECTOR, selector)
                        if els:
                            for el in reversed(els):
                                t = (el.text or "").strip()
                                if t:
                                    return t
                    except Exception:
                        continue
                return ""

            last = ""
            last_len = 0
            stable_for = 0
            result_text = ""

            # 先给一点点时间让回复容器出现
            time.sleep(1.5)
            for _ in range(max_wait):
                t = _latest_reply_text()
                if t and len(t) >= 20 and ("正在生成" not in t):
                    result_text = t
                    if len(t) > last_len:
                        stable_for = 0
                        last_len = len(t)
                        last = t
                    else:
                        stable_for += 1
                        # 内容连续 stable_sec 秒不变，认为生成完成
                        if stable_for >= stable_sec:
                            break
                time.sleep(1)

            if result_text and len(result_text.strip()) >= 20:
                print(f"  ✓ 成功获取分析结果", file=sys.stderr)
                from gemini_analyzer import extract_json_from_gemini_text
                import json as _json

                snippet = result_text.strip()
                parsed = extract_json_from_gemini_text(snippet)
                if parsed is not None:
                    print(_json.dumps(parsed, ensure_ascii=False, indent=2))
                else:
                    if len(snippet) > 1500:
                        snippet = snippet[:1500] + "\n...（已截断显示）"
                    print("  ===== Gemini 结果（抓取） =====", file=sys.stderr)
                    print(snippet)
                    print("  =============================", file=sys.stderr)
                analysis_result = {
                    'symbol': symbol,
                    'analysis': result_text,
                    'status': 'success',
                    'method': 'web'
                }
            else:
                # 兜底再等一段时间，仅补抓“最新一条回复节点”
                try:
                    extra_wait = int(os.getenv("GEMINI_WEB_EXTRA_WAIT", "30"))
                except Exception:
                    extra_wait = 30

                if extra_wait > 0:
                    print(f"  [INFO] 先等待 {extra_wait}s 后再补抓最新回复内容...")
                    time.sleep(extra_wait)

                try:
                    result_text2 = _latest_reply_text()
                except Exception:
                    result_text2 = ""

                if result_text2 and len(result_text2.strip()) >= 20 and ("正在生成" not in result_text2):
                    from gemini_analyzer import extract_json_from_gemini_text
                    import json as _json

                    snippet = result_text2.strip()
                    parsed = extract_json_from_gemini_text(snippet)
                    if parsed is not None:
                        print(_json.dumps(parsed, ensure_ascii=False, indent=2))
                    else:
                        if len(snippet) > 1500:
                            snippet = snippet[:1500] + "\n...（已截断显示）"
                        print("  ===== Gemini 结果（补抓） =====", file=sys.stderr)
                        print(snippet)
                        print("  =============================", file=sys.stderr)
                    analysis_result = {
                        'symbol': symbol,
                        'analysis': result_text2,
                        'status': 'success',
                        'method': 'web'
                    }
                else:
                    analysis_result = {
                        'symbol': symbol,
                        'status': 'error',
                        'error': '等待超时：未抓取到最新一条有效回复',
                        'method': 'web'
                    }
                    print(f"  [ERROR] 未抓取到最新一条有效回复（已等待超时）")
            
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
        if not keep_browser_open:
            try:
                driver.quit()
            except Exception:
                pass


def _write_base64_image_to_temp(b64: str, filename_hint: str = "") -> Optional[str]:
    """将 base64（可含 data URL 前缀）解码为临时图片文件路径。"""
    raw = (b64 or "").strip()
    if raw.startswith("data:") and "base64," in raw:
        raw = raw.split("base64,", 1)[1]
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception:
        return None
    if not data or len(data) < 8:
        return None
    hint = (filename_hint or "").lower()
    ext = ".png"
    for cand in (".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".png"):
        if hint.endswith(cand):
            ext = ".jpg" if cand in (".jpg", ".jpeg") else cand
            break
    fd, path = tempfile.mkstemp(prefix="gemini_b64_", suffix=ext)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def analyze_resources_with_gemini_web(
    resources: list[Union[str, Dict[str, Any]]],
    prompt: str,
    *,
    symbol: str = "resource_batch",
    keep_browser_open: bool = False,
    prefer_clipboard_upload: bool = False,
) -> dict:
    """
    批量分析：resources 与 prompt 均由外部传入。

    - 每项可为 ``http(s)`` 字符串、本地文件路径字符串，或 ``{"base64": "...", "filename": "a.png"}``。
    - ``prefer_clipboard_upload`` 为 True 时，对本地路径/URL 截图结果优先走剪贴板贴图。
    - ``base64`` 项始终解码为临时文件后，以 ``clipboard_only`` 方式粘贴。
    """
    p = (prompt or "").strip()
    if not p:
        return {"ok": False, "error": "prompt 不能为空", "results": []}

    raw_items: list[Union[str, Dict[str, Any]]] = []
    for x in resources or []:
        if isinstance(x, dict):
            raw_items.append(x)
        elif isinstance(x, str) and str(x).strip():
            raw_items.append(str(x).strip())
    if not raw_items:
        return {"ok": False, "error": "resources 为空", "results": []}

    def _is_http(s: str) -> bool:
        t = (s or "").strip().lower()
        return t.startswith("http://") or t.startswith("https://")

    def _screenshot_url_to_temp_image(url: str) -> Optional[str]:
        from browser_automation import init_browser

        driver = None
        try:
            driver = init_browser()
            driver.get(url)
            wait_sec = int(os.getenv("GEMINI_WEB_URL_SCREENSHOT_WAIT", "12"))
            if wait_sec > 0:
                time.sleep(wait_sec)
            out = os.path.join(
                tempfile.gettempdir(), f"gemini_web_url_{uuid.uuid4().hex}.png"
            )
            driver.save_screenshot(out)
            if os.path.isfile(out) and os.path.getsize(out) > 64:
                return out
            return None
        except Exception:
            return None
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    results: list[dict] = []
    temp_cleanup: list[str] = []

    def _run_one(
        upload_path: str,
        *,
        clip: bool,
        resource_label: str,
        index: int,
        total: int,
    ) -> dict:
        last_item = keep_browser_open and index == total
        r = analyze_with_gemini_web(
            upload_path,
            symbol=symbol,
            prompt=p,
            keep_browser_open=last_item,
            clipboard_only=clip,
            use_clipboard_upload=clip,
        )
        retries = 0
        while isinstance(r, dict) and r.get("status") == "error" and retries < 2:
            retries += 1
            wait_s = random.uniform(3.0, 8.0)
            print(
                f"[web_retry] 资源分析失败，{wait_s:.1f}s 后重试 "
                f"{retries}/2: {r.get('error', '')}"
            )
            time.sleep(wait_s)
            r = analyze_with_gemini_web(
                upload_path,
                symbol=symbol,
                prompt=p,
                keep_browser_open=last_item,
                clipboard_only=clip,
                use_clipboard_upload=clip,
            )
        if isinstance(r, dict):
            r["resource"] = resource_label
            if upload_path != resource_label:
                r["resource_snapshot"] = upload_path
        return r if isinstance(r, dict) else {"status": "error", "error": str(r)}

    try:
        for i, raw in enumerate(raw_items, 1):
            resource_label = ""
            upload_path = ""
            clip = prefer_clipboard_upload

            if isinstance(raw, dict):
                b64 = raw.get("base64")
                if not isinstance(b64, str) or not b64.strip():
                    b64 = raw.get("b64")
                if not isinstance(b64, str) or not b64.strip():
                    results.append(
                        {
                            "status": "error",
                            "method": "web",
                            "resource": str(raw)[:200],
                            "error": "dict 资源缺少 base64/b64 字段",
                        }
                    )
                    continue
                hint = str(raw.get("filename") or raw.get("name") or "")
                decoded = _write_base64_image_to_temp(b64, hint)
                if not decoded:
                    results.append(
                        {
                            "status": "error",
                            "method": "web",
                            "resource": hint or "<base64>",
                            "error": "base64 解码失败或数据过短",
                        }
                    )
                    continue
                temp_cleanup.append(decoded)
                upload_path = decoded
                resource_label = hint or "<base64>"
                clip = True
            else:
                fp = raw
                resource_label = fp
                upload_path = fp
                if _is_http(fp):
                    shot = _screenshot_url_to_temp_image(fp)
                    if not shot:
                        results.append(
                            {
                                "status": "error",
                                "method": "web",
                                "resource": fp,
                                "error": "URL 打开或截图失败",
                            }
                        )
                        continue
                    temp_cleanup.append(shot)
                    upload_path = shot
                elif not os.path.isfile(fp):
                    results.append(
                        {
                            "status": "error",
                            "method": "web",
                            "resource": fp,
                            "error": "文件不存在",
                        }
                    )
                    continue

            results.append(
                _run_one(
                    upload_path,
                    clip=clip,
                    resource_label=resource_label,
                    index=i,
                    total=len(raw_items),
                )
            )
    finally:
        for pth in temp_cleanup:
            try:
                os.remove(pth)
            except OSError:
                pass

    ok = any(isinstance(x, dict) and x.get("status") == "success" for x in results)
    return {"ok": ok, "count": len(results), "results": results}
