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
  BINANCE_SQUARE_IMAGE_UPLOAD_WAIT  选图后等待上传秒数，默认 20
  BINANCE_SQUARE_SKIP_GOTO     1/true 时不 driver.get，使用当前已打开的 Square 页
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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
from selenium.webdriver.common.action_chains import ActionChains
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
    os.getenv("BINANCE_SQUARE_IMAGE_UPLOAD_WAIT", "20") or "20"
)
SKIP_GOTO = os.getenv("BINANCE_SQUARE_SKIP_GOTO", "").strip().lower() in (
    "1",
    "true",
    "yes",
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
    "发文",
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
  if (r.width < 24 || r.height < 12) return false;
  const st = window.getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) < 0.05) return false;
  return true;
}
function markEditor(ed, root) {
  ed.setAttribute('data-auto-deal-eth-editor', '1');
  if (root) root.setAttribute('data-auto-deal-eth-editor-root', '1');
  return true;
}
function pickEditable(root) {
  if (!root || !visible(root)) return null;
  if (root.isContentEditable || root.getAttribute('contenteditable') === 'true') return root;
  return root.querySelector(
    '[contenteditable="true"], [role="textbox"], textarea, .ProseMirror, .ql-editor'
  );
}
const shortRoots = [];
for (const sel of [
  '.short-editor-editor',
  '[class*="short-editor-editor"]',
  '[class*="shortEditor-editor"]',
  '[class*="short-editor"]',
]) {
  document.querySelectorAll(sel).forEach(el => shortRoots.push(el));
}
for (const root of shortRoots) {
  const ed = pickEditable(root);
  if (ed && visible(ed)) return markEditor(ed, root);
}
const selectors = [
  'div[contenteditable="true"][role="textbox"]',
  'motion.div[contenteditable="true"]',
  'div[contenteditable="true"]',
  'textarea',
  '[role="textbox"]',
];
for (const sel of selectors) {
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    if (el.closest('[contenteditable="false"]')) continue;
    const root = el.closest('[class*="short-editor"]') || el.closest('.short-editor-editor');
    return markEditor(el, root);
  }
}
return false;
"""

_ACTIVATE_SHORT_EDITOR_JS = r"""
function visible(el) {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 24 || r.height < 12) return false;
  const st = window.getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none') return false;
  return true;
}
const roots = document.querySelectorAll(
  '.short-editor-editor, [class*="short-editor-editor"], [class*="short-editor"]'
);
for (const root of roots) {
  if (!visible(root)) continue;
  try { root.click(); } catch (_) {}
  const ed = root.querySelector('[contenteditable="true"], [role="textbox"], textarea')
    || (root.isContentEditable ? root : null);
  if (ed && visible(ed)) {
    try { ed.click(); ed.focus(); return true; } catch (_) {}
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
  el.focus();
  try {
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
  } catch (_) {
    el.innerText = text;
  }
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
function findIn(scope) {
  const nodes = Array.from(scope.querySelectorAll(
    'button, [role="button"], a, [class*="btn"], [class*="button"]'
  ));
  let best = null, bestSc = 0;
  for (const el of nodes) {
    if (!visible(el) || disabled(el)) continue;
    const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
    const cls = String(el.className || '') + ' ' + (el.getAttribute('class') || '');
    const blob = (t + ' ' + cls).toLowerCase();
    if (!t && !blob) continue;
    for (let i = 0; i < labels.length; i++) {
      if (t === labels[i] || t.includes(labels[i]) || blob.includes(labels[i].toLowerCase())) {
        const sc = 90 - i;
        if (sc > bestSc) { bestSc = sc; best = el; }
      }
    }
  }
  return best;
}
function submitSearchScopes() {
  const scopes = [];
  const seen = new Set();
  function add(el) {
    if (!el || seen.has(el)) return;
    seen.add(el);
    scopes.push(el);
  }
  const toolbarSel = '.editor-toolbar-container, [class*="editor-toolbar-container"]';
  const root = document.querySelector('[data-auto-deal-eth-editor-root="1"]')
    || document.querySelector('[class*="short-editor"]');
  const toolbars = [];
  if (root) {
    root.querySelectorAll(toolbarSel).forEach(el => toolbars.push(el));
  }
  document.querySelectorAll(toolbarSel).forEach(el => {
    if (!toolbars.includes(el)) toolbars.push(el);
  });
  for (const tb of toolbars) {
    const sib = tb.nextElementSibling;
    if (sib) add(sib);
    if (tb.parentElement) add(tb.parentElement);
    add(tb);
  }
  if (root) add(root);
  return scopes;
}
const scopes = submitSearchScopes();
if (!scopes.length) return null;
let best = null, bestSc = 0;
for (const scope of scopes) {
  const hit = findIn(scope);
  if (!hit) continue;
  const t = (hit.innerText || hit.textContent || '').trim();
  let sc = 0;
  for (let i = 0; i < labels.length; i++) {
    if (t === labels[i] || t.includes(labels[i])) { sc = 90 - i; break; }
  }
  if (sc > bestSc) { bestSc = sc; best = hit; }
}
if (!best) return null;
best.setAttribute('data-auto-deal-eth-submit', '1');
return true;
"""

_SCROLL_SUBMIT_JS = r"""
const toolbarSel = '.editor-toolbar-container, [class*="editor-toolbar-container"]';
const tb = document.querySelector(toolbarSel)
  || document.querySelector('[class*="editor-toolbar-container"]');
const target = (tb && tb.nextElementSibling) ? tb.nextElementSibling : tb;
if (target) {
  try { target.scrollIntoView({block:'center', inline:'center'}); return true; } catch (_) {}
}
return false;
"""

_CLICK_SUBMIT_JS = r"""
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
function findIn(scope) {
  const nodes = Array.from(scope.querySelectorAll(
    'button, [role="button"], a, [class*="btn"], [class*="button"]'
  ));
  let best = null, bestSc = 0;
  for (const el of nodes) {
    if (!visible(el) || disabled(el)) continue;
    const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
    const cls = String(el.className || '') + ' ' + (el.getAttribute('class') || '');
    const blob = (t + ' ' + cls).toLowerCase();
    if (!t && !blob) continue;
    for (let i = 0; i < labels.length; i++) {
      if (t === labels[i] || t.includes(labels[i]) || blob.includes(labels[i].toLowerCase())) {
        const sc = 90 - i;
        if (sc > bestSc) { bestSc = sc; best = el; }
      }
    }
  }
  return best;
}
function submitSearchScopes() {
  const scopes = [];
  const seen = new Set();
  function add(el) {
    if (!el || seen.has(el)) return;
    seen.add(el);
    scopes.push(el);
  }
  const toolbarSel = '.editor-toolbar-container, [class*="editor-toolbar-container"]';
  const root = document.querySelector('[data-auto-deal-eth-editor-root="1"]')
    || document.querySelector('[class*="short-editor"]');
  const toolbars = [];
  if (root) {
    root.querySelectorAll(toolbarSel).forEach(el => toolbars.push(el));
  }
  document.querySelectorAll(toolbarSel).forEach(el => {
    if (!toolbars.includes(el)) toolbars.push(el);
  });
  for (const tb of toolbars) {
    const sib = tb.nextElementSibling;
    if (sib) add(sib);
    if (tb.parentElement) add(tb.parentElement);
    add(tb);
  }
  if (root) add(root);
  return scopes;
}
const scopes = submitSearchScopes();
if (!scopes.length) return false;
let best = null, bestSc = 0;
for (const scope of scopes) {
  const hit = findIn(scope);
  if (!hit) continue;
  const t = (hit.innerText || hit.textContent || '').trim();
  let sc = 0;
  for (let i = 0; i < labels.length; i++) {
    if (t === labels[i] || t.includes(labels[i])) { sc = 90 - i; break; }
  }
  if (sc > bestSc) { bestSc = sc; best = hit; }
}
if (!best) return false;
try {
  best.scrollIntoView({block:'center', inline:'center'});
  best.click();
  return true;
} catch (_) {
  return false;
}
"""

_CLICK_IMAGE_BUTTON_JS = r"""
const words = ['图片', '图像', '添加图片', '上传图片', 'Photo', 'Image', '相册', 'Add image', 'media', 'attach'];
const hints = ['image', 'photo', 'picture', 'upload', 'media', 'attach', 'album'];
function visible(el) {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return false;
  const st = window.getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none') return false;
  return true;
}
function tryClick(el) {
  try { el.click(); return true; } catch (_) { return false; }
}
function matchBtn(el) {
  const t = (el.innerText || el.textContent || '').trim();
  const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
  const cls = String(el.className || '') + ' ' + (el.getAttribute('class') || '');
  const blob = (t + ' ' + label + ' ' + cls).toLowerCase();
  if (words.some(w => t.includes(w) || label.includes(w))) return true;
  return hints.some(h => blob.includes(h));
}
const root = document.querySelector('[data-auto-deal-eth-editor-root="1"]')
  || document.querySelector('[class*="short-editor"]');
const scopes = root ? [root, document] : [document];
for (const scope of scopes) {
  const nodes = scope.querySelectorAll('button, [role="button"], label');
  for (const el of nodes) {
    if (!visible(el)) continue;
    if (matchBtn(el) && tryClick(el)) return true;
  }
}
if (root) {
  for (const el of root.querySelectorAll('button, [role="button"]')) {
    if (!visible(el)) continue;
    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
    const t = (el.innerText || el.textContent || '').trim();
    const cls = String(el.className || '').toLowerCase();
    const blob = (t + ' ' + label + ' ' + cls);
    const isImageBtn = words.some(w => blob.includes(w))
      || hints.some(h => blob.toLowerCase().includes(h));
    if (isImageBtn && el.querySelector('svg') && tryClick(el)) return true;
  }
}
return false;
"""

_COUNT_UPLOADED_IMAGES_JS = r"""
(function() {
  const root = document.querySelector('[data-auto-deal-eth-editor-root="1"]')
    || document.querySelector('[class*="short-editor"]');
  const scope = root || document;

  function inToolbar(el) {
    return !!el.closest(
      '.editor-toolbar-container, [class*="editor-toolbar"], [class*="toolbar-container"]'
    );
  }
  function visible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 20) return false;
    const st = window.getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) < 0.05) return false;
    return true;
  }

  const seen = new Set();
  let n = 0;

  function addKey(key) {
    if (!key || seen.has(key)) return false;
    seen.add(key);
    n++;
    return true;
  }

  for (const img of scope.querySelectorAll('img')) {
    if (inToolbar(img) || !visible(img)) continue;
    const src = (img.src || img.getAttribute('src') || '').trim();
    if (!src || src.endsWith('.svg') || src.includes('data:image/svg')) continue;
    addKey('img|' + src);
  }

  const mediaSels = [
    '[class*="upload"]', '[class*="preview"]', '[class*="media"]',
    '[class*="attachment"]', '[class*="photo"]', '[class*="thumbnail"]',
    '[class*="image"]', '[class*="picture"]',
  ];
  for (const sel of mediaSels) {
    for (const el of scope.querySelectorAll(sel)) {
      if (inToolbar(el) || !visible(el)) continue;
      const bg = window.getComputedStyle(el).backgroundImage || '';
      if (bg && bg !== 'none' && bg.includes('url(')) {
        addKey('bg|' + bg.slice(0, 120));
      }
      for (const img of el.querySelectorAll('img')) {
        if (inToolbar(img) || !visible(img)) continue;
        const src = (img.src || '').trim();
        if (src && !src.endsWith('.svg')) addKey('img|' + src);
      }
    }
  }

  for (const inp of scope.querySelectorAll('input[type="file"]')) {
    if (inp.files && inp.files.length > 0) {
      n = Math.max(n, inp.files.length);
    }
  }

  return n;
})();
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


def _is_stale_error(exc: BaseException) -> bool:
    return "stale element" in str(exc).lower()


def _click_marked(
    driver,
    attr: str,
    *,
    log: str,
    rematch: bool = False,
) -> bool:
    sel = f'[data-auto-deal-eth-{attr}="1"]'
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            if rematch and attr == "submit":
                driver.execute_script(_FIND_SUBMIT_JS, list(_SUBMIT_LABELS))
            clicked = driver.execute_script(
                """
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return false;
                el.scrollIntoView({block:'center', inline:'center'});
                el.click();
                return true;
                """,
                sel,
            )
            if clicked:
                publish_log(log)
                return True
            if attr == "submit" and driver.execute_script(
                _CLICK_SUBMIT_JS, list(_SUBMIT_LABELS)
            ):
                publish_log(log)
                return True
        except Exception as e:
            last_err = e
            if _is_stale_error(e) and attempt < 3:
                human_pause(0.35, 0.75)
                continue
            break
        human_pause(0.25, 0.55)
    publish_log(f"{log} 失败: {last_err or '元素未找到'}")
    return False


def _type_into_editor(driver, text: str) -> None:
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            if not driver.execute_script(_FIND_EDITOR_JS):
                human_pause(0.35, 0.65)
                continue
            if driver.execute_script(_SET_EDITOR_TEXT_JS, text):
                return
            editor = driver.find_element(
                By.CSS_SELECTOR, '[data-auto-deal-eth-editor="1"]'
            )
            try:
                driver.execute_script("arguments[0].click();", editor)
            except Exception:
                pass
            human_pause(0.15, 0.35)
            editor.send_keys(text)
            return
        except Exception as e:
            last_err = e
            if _is_stale_error(e) and attempt < 3:
                human_pause(0.35, 0.75)
                continue
            break
    raise RuntimeError(f"无法写入正文编辑区: {last_err or 'unknown'}")


def _open_square_page(driver, square_url: str, *, force: bool = False) -> None:
    cur = (driver.current_url or "").strip().lower()
    base = square_url.rstrip("/").split("?")[0].lower()
    if not force and "/square" in cur and base in cur:
        publish_log(f"已在 Square 页，跳过重复打开: {driver.current_url}")
        wait_body(driver)
        human_pause(0.4, 0.8)
        try:
            driver.execute_script(_DISMISS_COOKIE_JS)
        except Exception:
            pass
        try:
            driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass
        return
    publish_log(f"打开 {square_url}")
    driver.get(square_url)
    wait_body(driver)
    human_pause_after_nav(1.0, 2.0)
    try:
        WebDriverWait(driver, 20).until(
            lambda d: "/square" in (d.current_url or "").lower()
        )
    except TimeoutException:
        publish_log(f"当前 URL: {driver.current_url or '(空)'}")
    try:
        driver.execute_script(_DISMISS_COOKIE_JS)
    except Exception:
        pass
    try:
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass
    human_pause(0.5, 1.0)


def _wait_for_editor(driver, timeout: float) -> bool:
    deadline = time.time() + max(6.0, timeout)
    while time.time() < deadline:
        if driver.execute_script(_FIND_EDITOR_JS):
            return True
        try:
            driver.execute_script(_ACTIVATE_SHORT_EDITOR_JS)
        except Exception:
            pass
        try:
            driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass
        human_pause(0.35, 0.65)
    return False


def _collect_file_inputs(driver) -> List[WebElement]:
    scoped: List[WebElement] = []
    try:
        root = driver.find_element(
            By.CSS_SELECTOR, '[data-auto-deal-eth-editor-root="1"]'
        )
        scoped.extend(root.find_elements(By.CSS_SELECTOR, 'input[type="file"]'))
    except Exception:
        pass
    for inp in driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]'):
        if inp in scoped:
            continue
        try:
            accept = (inp.get_attribute("accept") or "").lower()
            if accept and "image" not in accept and "*" not in accept:
                if "video" in accept or "audio" in accept:
                    continue
            scoped.append(inp)
        except Exception:
            continue
    return scoped


def _copy_image_to_clipboard(path: str) -> bool:
    if sys.platform != "darwin":
        return False
    ext = Path(path).suffix.lower()
    if ext == ".png":
        fmt = "«class PNGf»"
    elif ext in (".jpg", ".jpeg"):
        fmt = "JPEG picture"
    elif ext == ".gif":
        fmt = "GIF picture"
    else:
        fmt = "«class PNGf»"
    script = f'set the clipboard to (read (POSIX file "{path}") as {fmt})'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except Exception as e:
        publish_log(f"写入剪贴板失败: {e}")
        return False


def _paste_into_editor(driver) -> None:
    if not driver.execute_script(_FIND_EDITOR_JS):
        raise RuntimeError("粘贴图片前无法定位编辑器")
    editor = driver.find_element(By.CSS_SELECTOR, '[data-auto-deal-eth-editor="1"]')
    mod = modifier_open_new_tab_key()
    try:
        driver.execute_script("arguments[0].click(); arguments[0].focus();", editor)
    except Exception:
        pass
    human_pause(0.15, 0.35)
    ActionChains(driver).key_down(mod).send_keys("v").key_up(mod).perform()


def _count_uploaded_images(driver) -> int:
    try:
        n = driver.execute_script(_COUNT_UPLOADED_IMAGES_JS)
        return int(n) if n is not None else 0
    except Exception:
        return 0


def _wait_for_image_count(
    driver,
    *,
    baseline: int,
    target: int,
    timeout: float,
    poll: float = 0.6,
) -> int:
    """轮询直到编辑器内图片数 >= target 或超时。返回当前总数。"""
    deadline = time.monotonic() + max(0.5, timeout)
    last = baseline
    while time.monotonic() < deadline:
        last = _count_uploaded_images(driver)
        if last >= target:
            return last
        time.sleep(poll)
    return _count_uploaded_images(driver)


def _collect_post_urls(driver) -> set[str]:
    try:
        hrefs = driver.execute_script(
            """
            const out = new Set();
            for (const a of document.querySelectorAll('a[href*="/square/post/"]')) {
              const h = (a.href || '').split('#')[0];
              if (h) out.add(h);
            }
            try {
              const cur = location.href || '';
              if (cur.toLowerCase().includes('/square/post/')) {
                out.add(cur.split('#')[0]);
              }
            } catch (_) {}
            return Array.from(out);
            """
        )
        if isinstance(hrefs, list):
            return {str(h) for h in hrefs if h}
    except Exception:
        pass
    return set()


def _paste_one_image_via_clipboard(driver, image_path: str) -> bool:
    if sys.platform != "darwin":
        return False
    if not _copy_image_to_clipboard(image_path):
        return False
    human_pause(0.2, 0.4)
    before = _count_uploaded_images(driver)
    try:
        _paste_into_editor(driver)
    except Exception as e:
        publish_log(f"剪贴板粘贴失败: {e}")
        return False
    human_pause(1.0, 1.6)
    return _count_uploaded_images(driver) > before


def _upload_images(driver, image_paths: List[str]) -> int:
    """每种路径最多上传一次；禁止 file+剪贴板双通道重复传。"""
    if not image_paths:
        return 0

    before = _count_uploaded_images(driver)
    need = len(image_paths)
    if before >= need:
        publish_log(f"编辑器已有 {before} 张预览，跳过上传")
        return min(before, need)

    upload_wait = max(2.0, IMAGE_UPLOAD_WAIT_SEC)
    added = 0
    for ap in image_paths:
        target_total = before + added + 1
        if _count_uploaded_images(driver) >= before + need:
            break

        inputs = _collect_file_inputs(driver)
        if not inputs:
            driver.execute_script(_CLICK_IMAGE_BUTTON_JS)
            human_pause(0.5, 1.0)
            inputs = _collect_file_inputs(driver)

        sent_file = False
        if inputs:
            try:
                inputs[0].send_keys(ap)
                sent_file = True
                publish_log(f"file input 已选择: {ap}")
            except Exception as e:
                publish_log(f"file input send_keys 失败: {e}")

            publish_log(f"等待图片预览/上传（最多 {upload_wait:.0f}s）…")
            after = _wait_for_image_count(
                driver,
                baseline=before + added,
                target=target_total,
                timeout=upload_wait,
            )
            delta = after - (before + added)
            if delta > 0:
                added += delta
                publish_log(f"检测到 {delta} 张新预览（共 {after} 张）")
                continue

            if sent_file:
                # send_keys 成功但 DOM 检测未命中：仍等待上传完成，避免过早点发布
                publish_log(
                    "file 已发送但预览选择器未命中，额外等待上传完成（避免无图发布）"
                )
                time.sleep(upload_wait)
                after = _count_uploaded_images(driver)
                delta = after - (before + added)
                if delta > 0:
                    added += delta
                    publish_log(f"延迟检测到 {delta} 张预览")
                    continue
                added += 1
                publish_log("仍无预览计数，按 file 已发送计 1 张并继续")
                continue

        publish_log("无 file input，尝试剪贴板粘贴（一次）…")
        if _paste_one_image_via_clipboard(driver, ap):
            added = _count_uploaded_images(driver) - before

    if added <= 0:
        publish_log("图片未能写入编辑器，已跳过")
        return 0

    publish_log(f"已上传 {added} 张图片")
    return added


def publish_square_post(
    text: str,
    image_paths: Optional[Sequence[str]] = None,
    *,
    square_url: str = DEFAULT_SQUARE_URL,
    submit: bool = True,
    skip_goto: bool = False,
    allow_alt_url: bool = True,
    force_square_goto: bool = False,
    driver=None,
    close_driver: bool = True,
) -> PublishResult:
    """
    发布一条广场动态（文字 + 可选多图）。

    :param submit: False 时只填写/选图，不点击「发布」
    :param skip_goto: True 时不 driver.get，使用当前已打开的 Square 页
    :param allow_alt_url: False 时不尝试 ?tab=Home 二次打开
    :param force_square_goto: True 时始终 driver.get(square)，避免复用旧编辑区
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
        use_skip = skip_goto or SKIP_GOTO
        if use_skip:
            publish_log("跳过 driver.get，使用当前已打开的页面")
            wait_body(driver)
            human_pause(0.4, 0.8)
            try:
                driver.execute_script(_DISMISS_COOKIE_JS)
            except Exception:
                pass
        else:
            _open_square_page(
                driver,
                square_url,
                force=force_square_goto,
            )

        editor_ready = _wait_for_editor(driver, PUBLISH_WAIT_SEC)
        if editor_ready:
            steps.append("short_editor")
        else:
            if allow_alt_url and not use_skip:
                alt = square_url.rstrip("/").split("?")[0] + "?tab=Home"
                publish_log(f"未找到 short-editor，尝试 {alt}")
                _open_square_page(driver, alt, force=True)
                editor_ready = _wait_for_editor(driver, PUBLISH_WAIT_SEC)
                if editor_ready:
                    steps.append("short_editor")

            if not editor_ready:
                found_compose = driver.execute_script(
                    _FIND_COMPOSE_JS, list(_COMPOSE_LABELS)
                )
                if not editor_ready and found_compose:
                    steps.append("compose_entry")
                    if not _click_marked(driver, "compose", log="打开发帖编辑区"):
                        result.error = "点击发帖入口失败"
                        return result
                    human_pause_after_nav(0.6, 1.4)
                    editor_ready = _wait_for_editor(driver, PUBLISH_WAIT_SEC)

        if not editor_ready:
            result.error = (
                f"未在 {square_url} 找到 short-editor-editor 正文编辑区，"
                "请确认已登录且具有广场发帖权限"
            )
            return result
        steps.append("editor")

        if body:
            _type_into_editor(driver, body)
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

        human_pause(0.5, 1.0)
        try:
            driver.execute_script(_SCROLL_SUBMIT_JS)
        except Exception:
            pass
        driver.execute_script(_FIND_EDITOR_JS)
        urls_before = _collect_post_urls(driver)
        clicked_submit = False
        for attempt in range(4):
            if driver.execute_script(_CLICK_SUBMIT_JS, list(_SUBMIT_LABELS)):
                clicked_submit = True
                publish_log("点击发布/发文（JS 直接点击）")
                break
            if _click_marked(driver, "submit", log="点击发布/发文", rematch=True):
                clicked_submit = True
                break
            human_pause(0.4, 0.8)
        if not clicked_submit:
            result.error = (
                "未在 editor-toolbar-container 或其相邻兄弟节点中找到「发布/发文」按钮"
            )
            return result
        steps.append("submit_button")

        human_pause_after_nav(1.2, 2.8)
        wait_driver_execution_context(driver, 12.0)

        post_url = ""
        try:
            cur = (driver.current_url or "").strip()
            if "/square/post/" in cur.lower():
                post_url = cur.split("#")[0]
        except Exception:
            pass
        if not post_url:
            urls_after = _collect_post_urls(driver)
            new_urls = sorted(urls_after - urls_before)
            if new_urls:
                post_url = new_urls[-1]
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
                    publish_log(
                        "未能确认新帖 URL（页面上的链接可能是旧帖），请在浏览器中核对"
                    )
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
        "--skip-goto",
        action="store_true",
        help="不跳转 URL，使用 Chrome 当前已打开的 Square 页",
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
        skip_goto=args.skip_goto,
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
