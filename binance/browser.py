"""币安 Square 浏览器自动化公共方法（抓取/发布共用）。"""
from __future__ import annotations

import random
import sys
import time

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def human_pause(lo: float = 0.35, hi: float = 1.25) -> None:
    time.sleep(random.uniform(lo, hi))


def human_pause_after_nav(lo: float = 0.85, hi: float = 2.9) -> None:
    time.sleep(random.uniform(lo, hi))


def wait_driver_execution_context(driver, timeout_sec: float = 18.0) -> bool:
    deadline = time.time() + max(1.0, timeout_sec)
    while time.time() < deadline:
        try:
            try:
                driver.switch_to.default_content()
            except WebDriverException:
                pass
            driver.execute_script("return document.readyState")
            return True
        except WebDriverException:
            time.sleep(0.35)
        except Exception:
            time.sleep(0.35)
    return False


def modifier_open_new_tab_key():
    return Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL


def wait_body(driver, timeout: float = 28.0) -> None:
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    wait_driver_execution_context(driver, min(timeout, 22.0))


def publish_log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[square_publish {ts}] {msg}", flush=True)
