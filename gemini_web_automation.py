"""
Gemini web UI automation: simulate user upload, prompt, send, poll reply.

This is the core browser flow for gemini.google.com (not TradingView/screenshots).
Use: ``from gemini_web_automation import analyze_with_gemini_web``
or ``browser_automation.analyze_with_gemini_web`` (thin wrapper).
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
import uuid
from typing import Optional

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
):
    """Gemini web: open session, upload image, inject prompt, send, scrape reply."""
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
                                break
                        except:
                            continue
                    
                    if not add_file_button:
                        print(f"  [WARNING] 未找到添加文件按钮，尝试直接查找上传文件按钮")
                    
                    # 步骤2: 等待浮窗出现，然后查找"上传文件"按钮并使用 pyautogui 点击
                    # 必须先点“添加文件/+”，否则菜单未展开，后续会稳定找不到“上传文件/文件输入框”
                    if add_file_button:
                        # 给菜单展开一个小缓冲，主等待交给 WebDriverWait
                        time.sleep(0.8)
                        
                        # 查找"上传文件"按钮
                        upload_button = None
                        try:
                            # 查找包含"上传文件"文本的可点击父元素（浮窗中的）
                            upload_button = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.XPATH, "//*[contains(@class, 'mdc-list-item') and .//div[contains(text(), '上传文件')]] | //*[contains(@class, 'list-item') and .//*[contains(text(), '上传文件')]]"))
                            )
                            print(f"  [INFO] 找到上传文件按钮（浮窗中）")
                        except:
                            try:
                                upload_button = WebDriverWait(driver, 10).until(
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


def analyze_resources_with_gemini_web(
    resources: list[str],
    prompt: str,
    *,
    symbol: str = "resource_batch",
    keep_browser_open: bool = False,
) -> dict:
    """
    批量文件上传分析：resources 与 prompt 均由外部传入。
    - 不做截图/下载/REST，仅将本地文件逐个上传到 Gemini 网页版分析。
    """
    p = (prompt or "").strip()
    if not p:
        return {"ok": False, "error": "prompt 不能为空", "results": []}
    items = [str(x).strip() for x in (resources or []) if str(x).strip()]
    if not items:
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

    results = []
    for i, fp in enumerate(items, 1):
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
            upload_path = shot
        elif not os.path.isfile(fp):
            results.append(
                {"status": "error", "method": "web", "resource": fp, "error": "文件不存在"}
            )
            continue
        r = analyze_with_gemini_web(
            upload_path,
            symbol=symbol,
            prompt=p,
            keep_browser_open=keep_browser_open and i == len(items),
        )
        # 失败自动重试：等待 3~8 秒，最多再试 2 次
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
                keep_browser_open=keep_browser_open and i == len(items),
            )
        if isinstance(r, dict):
            r["resource"] = fp
            if upload_path != fp:
                r["resource_snapshot"] = upload_path
        results.append(r)
    ok = any(isinstance(x, dict) and x.get("status") == "success" for x in results)
    return {"ok": ok, "count": len(results), "results": results}
