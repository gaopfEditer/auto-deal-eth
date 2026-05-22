#!/usr/bin/env python3
"""
币安广场（Square）发帖：Selenium + 已登录 Chrome（远程调试 9222）。

与 binance.market_lists_selenium 相同前置：Chrome 需带 --remote-debugging-port=9222 且已登录币安。

用法：
  python -m binance.square_publish --text "今日观点 …"
  python -m binance.square_publish --text-file ./draft.txt --image a.png --image b.png
  python -m binance.square_publish --text "试填" --dry-run
  python -m binance.square_publish --text "…" --no-submit

环境变量：
  BINANCE_SQUARE_PUBLISH_URL   打开的首页，默认 https://www.binance.com/zh-CN/square
  BINANCE_SQUARE_PUBLISH_WAIT  进入编辑区后额外等待秒数，默认 8
  BINANCE_SQUARE_IMAGE_UPLOAD_WAIT  选图后等待上传秒数，默认 12
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from browser_automation import init_browser
from binance.browser import (
    human_pause,
    human_pause_after_nav,
    modifier_open_new_tab_key,
    publish_log,
    wait_body,
    wait_driver_execution_context,
)

DEFAULT_SQUARE_URL = os.getenv(
    "BINANCE_SQUARE_PUBLISH_URL", "https://www.binance.com/zh-CN/square"
).strip()
PUBLISH_WAIT_SEC = float(os.getenv("BINANCE_SQUARE_PUBLISH_WAIT", "8") or "8")
IMAGE_UPLOAD_WAIT_SEC = float(
    os.getenv("BINANCE_SQUARE_IMAGE_UPLOAD_WAIT", "12") or "12"
)

# 打开发帖入口：按钮/链接文案（中英）
_COMPOSE_LABELS = (
    "发帖",
    "发布",
    "发帖子",
    "写点什么",
    "分享你的想法",
    "Share your idea",
    "Create post",
    "Post",
    "New post",
)

_SUBMIT_LABELS = (
    "发布",
    "发帖",
    "Post",
    "Publish",
    "发送",
    "Submit",
)

_DISMISS_COOKIE_JS = r"""
(function() {
  const words = ['接受', '同意', 'Allow', 'Accept', 'OK', '确定', 'Got it'];
  const nodes = document.querySelectorAll('button, a, [role="button"]');
  for (const el of nodes) {
    const t = (el.innerText || el.textContent || '').trim();
    if (!t || t.length > 24) continue;
    if (words.some(w => t === w || t.includes(w))) {
      try { el.click(); return true; } catch (_) {}
    }
  }
  return false;
})();
"""

_FIND_COMPOSE_JS = r"""
const labels = arguments[0];
function visible(el) {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return false;
  const st = window.getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) < 0.05) return false;
  return true;
}
function score(el) {
  const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
  if (!t) return 0;
  for (let i = 0; i < labels.length; i++) {
    if (t.includes(labels[i])) return 100 - i;
  }
  return 0;
}
const nodes = Array.from(document.querySelectorAll(
  'button, a, [role="button"], div[role="button"]'
));
let best = null, bestSc = 0;
for (const el of nodes) {
  if (!visible(el)) continue;
  const sc = score(el);
  if (sc > bestSc) { bestSc = sc; best = el; }
}
// 广场顶栏「写评论」输入框占位：点击后进入发帖
if (!best) {
  const placeholders = ['分享', 'Share', '说点什么', '想法'];
  const inputs = Array.from(document.querySelectorAll(
    'textarea, input[type="text"], [contenteditable="true"], [role="textbox"]'
  ));
  for (const el of inputs) {
    if (!visible(el)) continue;
    const ph = (el.getAttribute('placeholder') || el.getAttribute('aria-label') || '').trim();
    if (placeholders.some(p => ph.includes(p))) { best = el; break; }
  }
}
if (!best) return null;
best.setAttribute('data-auto-deal-eth-compose', '1');
return true;
"""

_FIND_EDITOR_JS = r"""
function visible(el) {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 40 || r.height < 18) return false;
  const st = window.getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none') return false;
  return true;
}
const selectors = [
  'div[contenteditable="true"][role="textbox"]',
  'div[contenteditable="true"]',
  'textarea',
  '[role="textbox"]'
];
for (const sel of selectors) {
  const list = Array.from(document.querySelectorAll(sel));
  for (const el of list) {
    if (!visible(el)) continue;
    if (el.closest('[contenteditable="false"]')) continue;
    el.setAttribute('data-auto-deal-eth-editor', '1');
    return true;
  }
}
return false;
"""

_SET_EDITOR_TEXT_JS = r"""
const text = arguments[0];
const el = document.querySelector('[data-auto-deal-eth-editor="1"]');
if (!el) return false;
el.focus();
if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
  el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
} else {
  el.innerText = text;
  el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text }));
}
return true;
"""

_FIND_SUBMIT_JS = r"""
const labels = arguments[0];
function visible(el) {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return false;
  const st = window.getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) < 0.05) return false;
  return true;
}
function disabled(el) {
  return el.disabled || el.getAttribute('aria-disabled') === 'true';
}
const nodes = Array.from(document.querySelectorAll('button, [role="button"]'));
let best = null, bestSc = 0;
for (const el of nodes) {
  if (!visible(el) || disabled(el)) continue;
  const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
  if (!t) continue;
  for (let i = 0; i < labels.length; i++) {
    if (t === labels[i] || t.includes(labels[i])) {
      const sc = 90 - i;
      if (sc > bestSc) { bestSc = sc; best = el; }
    }
  }
}
if (!best) return null;
best.setAttribute('data-auto-deal-eth-submit', '1');
return true;
"""


@dataclass
class PublishResult:
    ok: bool
    submitted: bool = False
    post_url: str = ""
    error: str = ""
    steps: List[str] = field(default_factory=list)
    text_length: int = 0
    image_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_image_paths(paths: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    if not paths:
        return out
    for p in paths:
        for part in re.split(r"[,;\s]+", str(p).strip()):
            if not part:
                continue
            ap = os.path.abspath(os.path.expanduser(part))
            if not os.path.isfile(ap):
                raise FileNotFoundError(f"图片不存在: {part}")
            low = ap.lower()
            if not low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
                raise ValueError(f"不支持的图片格式: {ap}")
            out.append(ap)
    return out


def _click_marked(driver, attr: str, *, log: str) -> bool:
    sel = f'[data-auto-deal-eth-{attr}="1"]'
    try:
        el = driver.find_element(By.CSS_SELECTOR, sel)
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center'});", el
        )
        human_pause(0.2, 0.5)
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        publish_log(log)
        return True
    except Exception as e:
        publish_log(f"{log} 失败: {e}")
        return False


def _type_into_editor(driver, el: WebElement, text: str) -> None:
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    human_pause(0.15, 0.35)
    # 优先键盘输入（部分编辑器对 JS 赋值不触发校验）
    try:
        el.send_keys(modifier_open_new_tab_key() + "a")
        human_pause(0.05, 0.12)
        el.send_keys(Keys.DELETE)
        human_pause(0.05, 0.12)
        el.send_keys(text)
        return
    except Exception:
        pass
    ok = driver.execute_script(_SET_EDITOR_TEXT_JS, text)
    if not ok:
        raise RuntimeError("无法写入正文编辑区")


def _upload_images(driver, image_paths: List[str]) -> int:
    if not image_paths:
        return 0
    uploaded = 0
    inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
    visible_inputs: List[WebElement] = []
    for inp in inputs:
        try:
            accept = (inp.get_attribute("accept") or "").lower()
            if accept and "image" not in accept and "*" not in accept:
                continue
            visible_inputs.append(inp)
        except Exception:
            continue

    if not visible_inputs:
        # 尝试点「图片」「添加图片」再找 file input
        driver.execute_script(
            """
            const words = ['图片', '图像', '添加图片', '上传图片', 'Photo', 'Image'];
            const nodes = document.querySelectorAll('button, [role="button"], label');
            for (const el of nodes) {
              const t = (el.innerText || el.textContent || '').trim();
              if (words.some(w => t.includes(w))) {
                try { el.click(); return true; } catch (_) {}
              }
            }
            return false;
            """
        )
        human_pause(0.5, 1.0)
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        visible_inputs = list(inputs)

    if not visible_inputs:
        publish_log("未找到图片上传 input[type=file]，已跳过图片")
        return 0

    target = visible_inputs[0]
    # 单 input 多图：Windows 部分 Chrome 支持换行分隔路径
    joined = "\n".join(image_paths)
    try:
        target.send_keys(joined)
        uploaded = len(image_paths)
    except Exception:
        for ap in image_paths:
            try:
                target.send_keys(ap)
                uploaded += 1
                human_pause(0.4, 0.9)
            except Exception as e:
                publish_log(f"上传失败 {ap}: {e}")

    if uploaded:
        publish_log(f"已选择 {uploaded} 张图片，等待上传 {IMAGE_UPLOAD_WAIT_SEC:.0f}s …")
        time.sleep(max(2.0, IMAGE_UPLOAD_WAIT_SEC))
    return uploaded


def publish_square_post(
    text: str,
    image_paths: Optional[Sequence[str]] = None,
    *,
    square_url: str = DEFAULT_SQUARE_URL,
    submit: bool = True,
    driver=None,
    close_driver: bool = True,
) -> PublishResult:
    """
    发布一条广场动态（文字 + 可选多图）。

    :param submit: False 时只填写/选图，不点击「发布」
    :param driver: 传入则复用已有 WebDriver；否则内部 init_browser(远程调试)
    """
    body = (text or "").strip()
    if not body and not image_paths:
        return PublishResult(ok=False, error="正文与图片不能同时为空")

    images = _normalize_image_paths(image_paths)
    steps: List[str] = []
    own_driver = driver is None

    if own_driver:
        publish_log("连接 Chrome（远程调试）…")
        driver = init_browser(use_remote_debugging=True)

    result = PublishResult(
        ok=False,
        submitted=False,
        text_length=len(body),
        image_count=len(images),
        steps=steps,
    )

    try:
        publish_log(f"打开 {square_url}")
        driver.get(square_url)
        wait_body(driver)
        human_pause_after_nav()

        try:
            driver.execute_script(_DISMISS_COOKIE_JS)
        except Exception:
            pass
        human_pause(0.3, 0.7)

        found_compose = driver.execute_script(_FIND_COMPOSE_JS, list(_COMPOSE_LABELS))
        if not found_compose:
            # 部分账号在 profile 页发帖；再试首页带 hash
            alt = square_url.rstrip("/") + "?tab=Home"
            if alt != square_url:
                publish_log(f"未找到发帖入口，尝试 {alt}")
                driver.get(alt)
                wait_body(driver)
                human_pause_after_nav()
                found_compose = driver.execute_script(_FIND_COMPOSE_JS, list(_COMPOSE_LABELS))

        if not found_compose:
            result.error = "未找到发帖/分享入口，请确认已登录且具有广场发帖权限"
            return result
        steps.append("compose_entry")

        if not _click_marked(driver, "compose", log="打开发帖编辑区"):
            result.error = "点击发帖入口失败"
            return result
        human_pause_after_nav(0.6, 1.4)

        deadline = time.time() + max(8.0, PUBLISH_WAIT_SEC)
        editor_ready = False
        while time.time() < deadline:
            if driver.execute_script(_FIND_EDITOR_JS):
                editor_ready = True
                break
            human_pause(0.35, 0.65)
        if not editor_ready:
            result.error = "未找到正文编辑区（contenteditable/textarea）"
            return result
        steps.append("editor")

        editor = driver.find_element(By.CSS_SELECTOR, '[data-auto-deal-eth-editor="1"]')
        if body:
            _type_into_editor(driver, editor, body)
            publish_log(f"已填入正文 {len(body)} 字")
            steps.append("text")
            human_pause(0.4, 0.9)

        if images:
            n = _upload_images(driver, images)
            result.image_count = n
            if n:
                steps.append(f"images:{n}")

        if not submit:
            result.ok = True
            result.submitted = False
            publish_log("未点击发布（submit=False / --dry-run）")
            steps.append("dry_run")
            return result

        found_submit = driver.execute_script(_FIND_SUBMIT_JS, list(_SUBMIT_LABELS))
        if not found_submit:
            result.error = "未找到「发布」按钮"
            return result
        steps.append("submit_button")

        if not _click_marked(driver, "submit", log="点击发布"):
            result.error = "点击发布按钮失败"
            return result

        human_pause_after_nav(1.2, 2.8)
        wait_driver_execution_context(driver, 12.0)

        # 尝试从当前 URL 或页面链接解析新帖地址
        post_url = ""
        try:
            cur = (driver.current_url or "").strip()
            if "/square/post/" in cur.lower():
                post_url = cur.split("#")[0]
        except Exception:
            pass
        if not post_url:
            try:
                hrefs = driver.execute_script(
                    """
                    const out = [];
                    for (const a of document.querySelectorAll('a[href*="/square/post/"]')) {
                      const h = a.href || '';
                      if (h) out.push(h.split('#')[0]);
                    }
                    return out.slice(0, 5);
                    """
                )
                if isinstance(hrefs, list) and hrefs:
                    post_url = str(hrefs[0])
            except Exception:
                pass

        result.ok = True
        result.submitted = True
        result.post_url = post_url
        steps.append("submitted")
        if post_url:
            publish_log(f"发布完成: {post_url}")
        else:
            publish_log("已点击发布，请在浏览器中确认是否成功（未能自动解析帖子 URL）")
        return result

    except Exception as e:
        result.error = str(e)
        publish_log(f"异常: {e}")
        return result
    finally:
        if own_driver and close_driver and driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _read_text_file(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    return p.read_text(encoding="utf-8").strip()


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="币安广场发帖（Selenium + 已登录 Chrome）")
    p.add_argument("--text", default="", help="正文")
    p.add_argument("--text-file", default="", help="从文件读取正文")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        help="图片路径，可多次指定",
    )
    p.add_argument(
        "--url",
        default=DEFAULT_SQUARE_URL,
        help="打开的 Square 首页",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="填入内容与图片，不点击发布",
    )
    p.add_argument(
        "--no-submit",
        action="store_true",
        help="同 --dry-run",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 打印结果",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    text = (args.text or "").strip()
    if args.text_file:
        text = _read_text_file(args.text_file)

    submit = not (args.dry_run or args.no_submit)
    result = publish_square_post(
        text,
        args.image,
        square_url=args.url,
        submit=submit,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        if result.ok:
            print("[OK] 流程完成")
            if result.post_url:
                print(f"     帖子: {result.post_url}")
            if not result.submitted:
                print("     未提交（dry-run）")
        else:
            print(f"[FAIL] {result.error or '未知错误'}")
        if result.steps:
            print(f"     步骤: {' → '.join(result.steps)}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
