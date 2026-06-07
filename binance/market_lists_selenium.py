#!/usr/bin/env python3
"""
使用 Selenium 抓取币安市场列表：
1) Square Following：可配置重点关注用户，仅巡检其是否直播、是否发文章
2) 涨幅榜 / 跌幅榜（各前 N，默认 10；DOM 失败时回退 24h API）
3) 可选：全局成交额热榜（--include-hot-rank）

默认连接已开启远程调试的 Chrome（复用登录态）：
  Mac:
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222

运行示例：
  python -m binance.market_lists_selenium
  python -m binance.market_lists_selenium --out ./screenshots/binance_lists.json
  python -m binance.market_lists_selenium --url "https://www.binance.com/zh-CN/markets/overview"

说明：
  - 关注列表请使用币安 Square Following 页面（默认 .../square?tab=Following），需已登录。
  - 重点关注用户在源码中 PRIORITY_FOLLOW_PROFILES 列表配置（完整 profile URL 或 slug）；
    仅对这些用户巡检「是否直播」与「是否发文章」；列表为空时仍巡检 Following 页收集到的全部主页。
  - 行情：默认只输出涨幅榜、跌幅榜各前 N（--market-top，默认 10）；全局热榜需加 --include-hot-rank。
  - 热榜/涨幅/跌幅若页面 DOM 抓不到，涨幅与跌幅会回退到官方 /api/v3/ticker/24hr（无需 Key）。
  - 关注流帖子默认合并 binance_posts_state.json：按发帖时间保留近 N 小时（默认 24，config.POST_RETENTION_HOURS 或环境变量 POST_RETENTION_HOURS），新帖终端提示并用 Gemini 判多空；
    可用 --skip-posts-state 仅输出本次快照。
  - 重点关注用户会额外打开其主页并深度下滚，合并时间线帖子（条数见 --max-items）；帖子卡片内图片可保存到 --square-images-dir。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import requests  # 用于热榜/涨跌幅 API 回退
except ModuleNotFoundError:  # 允许你只用 DOM 抓 Square Following
    requests = None

try:
    import pandas as pd  # 标准输出表格（与 getinfo/run_calendar 风格一致）
except ModuleNotFoundError:
    pd = None

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from browser_automation import init_browser

from binance.cdp_navigation import cdp_get, cdp_restore, cdp_worker_tab
from binance.posts_state import (
    DETAIL_FETCH_CACHE_VERSION,
    POST_RETENTION_HOURS,
    beijing_time_str,
    default_posts_state_path,
    detail_fetch_cache_entry_fresh,
    enrich_post_published_fields,
    filter_posts_by_published_age,
    load_posts_state,
    parse_published_to_dt,
    process_watchlist_posts,
    save_posts_state,
)


DEFAULT_URL = "https://www.binance.com/zh-CN/markets/overview"
DEFAULT_WATCHLIST_URL = "https://www.binance.com/zh-CN/square?tab=Following"
BINANCE_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"
# 官方多节点 + data-api（国内/网络不稳时依次尝试）
BINANCE_TICKER_24H_URLS: Tuple[str, ...] = (
    BINANCE_TICKER_24H,
    "https://api1.binance.com/api/v3/ticker/24hr",
    "https://api2.binance.com/api/v3/ticker/24hr",
    "https://api3.binance.com/api/v3/ticker/24hr",
    "https://data-api.binance.vision/api/v3/ticker/24hr",
)
# 行情页热榜 / 涨幅榜 / 跌幅榜默认只取前 N（与 Square 关注流的 --max-items 无关）
DEFAULT_MARKET_RANK_TOP_N = 10

# 重点关注用户：Square profile 完整 URL 或单独 slug（与下方顺序一致）；可随意增删。
# 为空列表时：直播/文章巡检范围仍为 Following 页收集到的全部主页。
PRIORITY_PROFILE_BASE = "https://www.binance.com/zh-CN/square/profile/"
PRIORITY_FOLLOW_PROFILES: List[str] = [
    f"{PRIORITY_PROFILE_BASE}yanchibit",
    f"{PRIORITY_PROFILE_BASE}aleng888888",
    f"{PRIORITY_PROFILE_BASE}sanmageshuai",
    f"{PRIORITY_PROFILE_BASE}square-creator-92912a51e",
    # f"{PRIORITY_PROFILE_BASE}square-creator-857dc547d",
    f"{PRIORITY_PROFILE_BASE}Square-Creator-1d148bbce7461",
    # f"{PRIORITY_PROFILE_BASE}square-creator-4bd102843",
    
    # f"{PRIORITY_PROFILE_BASE}square-creator-f69ded460", 烦死
    # f"{PRIORITY_PROFILE_BASE}sanmageshuai",
]

# 标准输出每个区块最多行数（0 表示全部）；与 getinfo/run_calendar 的 MAX_ROWS 用法类似
MAX_STDOUT_ROWS = 180

# 进入帖子正文页补充配图时，默认最多打开的帖子数（实际会受 --max-items 与过滤后条数约束）
MAX_POST_DETAIL_ENRICH_PAGES = 80
# 视频中心点击打开详情页后，是否保留新标签页（便于肉眼确认跳转）
KEEP_VIDEO_DETAIL_TAB = (
    os.getenv("KEEP_VIDEO_DETAIL_TAB", "false").strip().lower() == "true"
)
# 不保留标签页时，关闭前最少停留秒数（避免“看不到有打开过”）
VIDEO_DETAIL_TAB_VISIBLE_SEC = float(
    os.getenv("VIDEO_DETAIL_TAB_VISIBLE_SEC", "1.6").strip() or "1.6"
)
# 视频探测/回扫：用 Cmd/Ctrl+点击尽量在后台打开新标签（减少新页签抢焦点；依赖浏览器默认行为）
SQUARE_VIDEO_BACKGROUND_TAB_CLICK = (
    os.getenv("SQUARE_VIDEO_BACKGROUND_TAB_CLICK", "true").strip().lower() != "false"
)
# 打印 text-PrimaryText 后，对每个 aspect-video 矩形内随机点击并打印打开后的 URL
ASPECT_VIDEO_PROBE_CLICK_AFTER_TEXT = (
    os.getenv("ASPECT_VIDEO_PROBE_CLICK_AFTER_TEXT", "true").strip().lower() == "true"
)
# 视频回扫 / aspect 探测：卡片发帖时间早于「现在 − N 天」则跳过点击（无法解析时间的卡片仍点击，避免漏抓）
ASPECT_VIDEO_SCAN_MAX_PUBLISH_AGE_DAYS = float(
    (os.getenv("ASPECT_VIDEO_SCAN_MAX_PUBLISH_AGE_DAYS", "2") or "2").strip() or "2"
)

# 注入到币安 Square 页内的直播提示条（固定 id，便于下一轮未直播时移除）
SQUARE_LIVE_TOAST_ID = "auto-deal-eth-square-live-toast"

# /square/audio/replay 页：仅从 performance 网络资源筛 m3u8（不再读 DOM 标题 / video.src）
_AUDIO_REPLAY_M3U8_FROM_NETWORK_JS = r"""
const m3u8Set = new Set();
try {
  const perf = (performance && performance.getEntriesByType)
    ? performance.getEntriesByType('resource')
    : [];
  for (const e of perf || []) {
    const n = String((e && e.name) || '').trim();
    if (!n) continue;
    const low = n.toLowerCase();
    if (low.includes('.m3u8') || (low.includes('/static/live-ag/') && low.includes('m3u8'))) {
      m3u8Set.add(n.split('#')[0]);
    }
  }
} catch (_) {}
const m3u8Urls = Array.from(m3u8Set).slice(0, 8);
return { m3u8_url: m3u8Urls[0] || '' };
"""

# 点击 aspect-video 之前：从同卡片 text-PrimaryText 取标题（进入回播页前唯一标题来源）
_ASPECT_VIDEO_PRE_CLICK_TITLE_JS = r"""
const i = arguments[0];
const list = document.querySelectorAll('[class*="aspect-video"]');
const el = list[i];
if (!el) return '';
const root = el.closest('article') || el.closest('[class*="post"]')
  || el.closest('[class*="card"]') || el.closest('[role="button"]') || el.parentElement;
if (!root) return '';
const texts = [];
for (const e of root.querySelectorAll('[class*="text-PrimaryText"]')) {
  const t = String((e && (e.innerText || e.textContent)) || '')
    .replace(/\s+/g, ' ')
    .trim();
  if (t && !texts.includes(t)) texts.push(t);
}
return texts.join(' | ');
"""

# 点击前：从 aspect-video 同卡片取 /square/post/ 链接，用于把回播 m3u8 写回该帖（state 键即 post href）
_ASPECT_VIDEO_CARD_POST_HREF_JS = r"""
const i = arguments[0];
const list = document.querySelectorAll('[class*="aspect-video"]');
const el = list[i];
if (!el) return '';
let n = el;
for (let depth = 0; depth < 28 && n; depth++) {
  if (n.querySelectorAll) {
    for (const a of n.querySelectorAll('a[href*="/square/post/"]')) {
      const h = (a.href || '').split('#')[0];
      if ((h || '').toLowerCase().includes('/square/post/')) return h;
    }
  }
  n = n.parentElement;
}
return '';
"""

# 已进入 /square/audio/replay 页：用标题与候选 <a> 周围文案对齐，避免误取侧栏/推荐流第一个 post 链
_SQUARE_AUDIO_REPLAY_PAGE_RESOLVE_POST_HREF_JS = r"""
const titleHint = String(arguments[0] || '');
const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
const h = norm(titleHint);
const needles = [];
if (h.length >= 4) {
  if (h.length <= 100) needles.push(h);
  needles.push(h.slice(0, Math.min(48, h.length)));
  h.split(/[|｜\s?？!！，,]+/).forEach((p) => {
    const t = p.trim();
    if (t.length >= 4 && needles.indexOf(t) < 0) needles.push(t);
  });
}
const uniq = [];
for (const n of needles) {
  if (n && uniq.indexOf(n) < 0) uniq.push(n);
}
function contextForAnchor(a) {
  let n = a;
  let blob = '';
  for (let d = 0; d < 10 && n; d++) {
    blob += ' ' + ((n.innerText || n.textContent) || '');
    if (blob.length > 1000) break;
    n = n.parentElement;
  }
  return norm(blob).slice(0, 1400);
}
const list = Array.from(document.querySelectorAll('a[href*="/square/post/"]'));
let best = '';
let bestScore = -1;
for (const a of list) {
  const href = (a.href || '').split('#')[0];
  if (!href || href.toLowerCase().indexOf('/square/post/') < 0) continue;
  if (!h) {
    best = href;
    break;
  }
  const ctx = contextForAnchor(a);
  let sc = 0;
  for (const nd of uniq) {
    if (nd.length >= 4 && ctx.indexOf(nd) >= 0) sc += nd.length;
  }
  if (sc > bestScore) {
    bestScore = sc;
    best = href;
  }
}
if (h && bestScore <= 0) return '';
return best || '';
"""

# 从表格行文本里抠交易对（兼容 BTCUSDT / btcusdt / BTC/USDT）
_ROW_SYMBOL_RE = re.compile(
    r"\b([A-Za-z0-9]{2,20}(?:USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH|BNB|TRY|EUR)(?:\.P)?)\b"
    r"|([A-Za-z0-9]{2,15}/[A-Za-z0-9]{2,15})\b"
)

# 仅采集帖子链接下方的「附图」：排除头像/图标/小图（与 execute_script 内 _bn* 一致）
_SQUARE_ATTACHMENT_IMG_JS = r"""
function _bnNoiseImgUrl(src) {
  const s = (src || '').toLowerCase();
  if (!s || s.startsWith('data:')) return true;
  if (s.includes('avatar')) return true;
  if (s.includes('userpic')) return true;
  if (s.includes('/icon')) return true;
  if (s.includes('favicon')) return true;
  if (s.includes('emoji')) return true;
  if (s.includes('badge')) return true;
  if (s.includes('qrcode') || s.includes('qr-code')) return true;
  if (s.includes('sprite')) return true;
  if (s.includes('logo') && s.includes('binance')) return true;
  const wh = s.match(/\b(\d{1,3})x(\d{1,3})\b/);
  if (wh) {
    const w = parseInt(wh[1], 10), h = parseInt(wh[2], 10);
    if (w <= 96 && h <= 96) return true;
  }
  return false;
}

function _bnInAvatarOrHeader(im) {
  let n = im;
  for (let i = 0; i < 14 && n; i++) {
    const cls = String(n.className || '');
    const tag = (n.tagName || '').toLowerCase();
    if (/avatar|user-?pic|head-?portrait|author.?pic|profile.?pic/i.test(cls)) return true;
    if (tag === 'header' || tag === 'nav') return true;
    if (/sidebar|side-bar|leftnav|rightnav|global-nav/i.test(cls)) return true;
    n = n.parentElement;
  }
  return false;
}

function _bnCollectArticleImagesRelaxed(a) {
  const card = a.closest('article')
    || a.closest('[class*="article"]')
    || a.closest('[class*="Article"]')
    || a.closest('[class*="PostCard"]')
    || a.closest('[class*="post-card"]')
    || a.parentElement;
  if (!card) return [];
  const urls = [];
  const imgs = card.querySelectorAll('img[src]');
  for (const im of imgs) {
    if (!im || a.contains(im)) continue;
    if (_bnInAvatarOrHeader(im)) continue;
    let src = im.currentSrc || im.src
      || (im.getAttribute && (im.getAttribute('src') || im.getAttribute('data-src'))) || '';
    if (_bnNoiseImgUrl(src)) continue;
    const iw = im.naturalWidth || 0;
    const ih = im.naturalHeight || 0;
    const ir = im.getBoundingClientRect();
    if (iw > 0 && ih > 0) {
      if (iw < 64 || ih < 64) continue;
      if (iw * ih < 4096) continue;
    } else if (ir.width < 56 || ir.height < 56) {
      continue;
    }
    urls.push(src);
  }
  return [...new Set(urls)].slice(0, 16);
}

function _bnCollectVideoUrlFromCard(a) {
  const card = a.closest('article')
    || a.closest('[class*="article"]')
    || a.closest('[class*="Article"]')
    || a.closest('[class*="PostCard"]')
    || a.closest('[class*="post-card"]')
    || a.parentElement;
  if (!card) return '';
  const vids = Array.from(card.querySelectorAll('video, source'));
  for (const v of vids) {
    const src =
      (v.currentSrc || v.src
      || (v.getAttribute && (v.getAttribute('src') || v.getAttribute('data-src'))) || '').trim();
    if (!src) continue;
    const s = src.toLowerCase();
    if (s.startsWith('blob:') || s.startsWith('data:')) continue;
    if (s.includes('avatar') || s.includes('emoji') || s.includes('icon')) continue;
    return src;
  }
  return '';
}

function _bnReadCreateTimeFromNickContainer(root) {
  if (!root || !root.querySelector) return { publishedIso: '', timeLabel: '' };
  const nick = root.querySelector('[class*="avatar-nick-container"]');
  if (!nick) return { publishedIso: '', timeLabel: '' };
  const ct = nick.querySelector('[class*="create-time"]')
    || nick.querySelector('.create-time');
  if (!ct) return { publishedIso: '', timeLabel: '' };
  let publishedIso = '';
  let timeLabel = '';
  const te = ct.querySelector('time[datetime]');
  if (te) {
    publishedIso = te.getAttribute('datetime') || '';
    timeLabel = (te.innerText || '').trim();
  }
  if (!timeLabel) {
    timeLabel = (ct.innerText || ct.textContent || '').trim();
  }
  return { publishedIso, timeLabel };
}

function _bnPostTimeFromCard(a) {
  let publishedIso = '';
  let timeLabel = '';
  let isPinned = false;
  const card = a.closest('article')
    || a.closest('[class*="post"]')
    || a.closest('[class*="Article"]')
    || a.parentElement;
  let el = a;
  for (let depth = 0; depth < 24 && el; depth++) {
    const got = _bnReadCreateTimeFromNickContainer(el);
    if (got.timeLabel || got.publishedIso) {
      publishedIso = got.publishedIso;
      timeLabel = got.timeLabel;
      break;
    }
    el = el.parentElement;
  }
  if (!timeLabel && !publishedIso && card) {
    const got = _bnReadCreateTimeFromNickContainer(card);
    publishedIso = got.publishedIso;
    timeLabel = got.timeLabel;
  }
  if (!timeLabel && !publishedIso && card) {
    const te = card.querySelector('time[datetime]');
    if (te) {
      publishedIso = te.getAttribute('datetime') || '';
      timeLabel = (te.innerText || '').trim();
    }
  }
  if (!timeLabel && card) {
    const cand = card.querySelectorAll('span,div,time,p,label,small,em,i');
    for (const el2 of cand) {
      const tx = (el2.innerText || '').trim();
      if (tx.length > 80) continue;
      if (/^\d{4}-\d{2}-\d{2}/.test(tx) || /\d{1,2}:\d{2}/.test(tx)
          || /分钟前|小时前|天前|秒前|昨天|前天|刚刚/.test(tx)
          || /\d{1,2}\s*月\s*\d{1,2}\s*日/.test(tx)
          || /\d+\s*(?:小时|分钟|秒)(?:前)?$/.test(tx)
          || /\d+\s*(?:hours?|minutes?|seconds?|hrs?|mins?)\s*ago/i.test(tx)) {
        timeLabel = tx;
        break;
      }
    }
  }
  if (!timeLabel && card) {
    const blob = (card.innerText || '').replace(/\s+/g, ' ');
    const m = blob.match(
      /\d{1,2}\s*月\s*\d{1,2}\s*日|\d+\s*(?:小时|分钟|秒)(?:前)?(?=\s|$)|\d{4}-\d{2}-\d{2}[^\s]{0,20}|\d+\s*(?:hours?|minutes?|seconds?)\s*ago/i
    );
    if (m) timeLabel = m[0].trim();
  }
  if (card) {
    const head = (card.innerText || '').slice(0, 900);
    if (/置顶|pinned|🔝/i.test(head)) isPinned = true;
  }
  return { published_iso: publishedIso, time_label: timeLabel, is_pinned: isPinned };
}

function _bnDetailArticleImages() {
  const roots = [];
  const m = document.querySelector('main');
  if (m) roots.push(m);
  document.querySelectorAll('[class*="article"], [class*="Article"], [class*="detail"], [class*="Detail"], [class*="content"]').forEach((el) => {
    if (roots.length < 8) roots.push(el);
  });
  if (!roots.length) roots.push(document.body);
  const urls = [];
  const seen = new Set();
  for (const root of roots) {
    root.querySelectorAll('img[src]').forEach((im) => {
      let src = im.currentSrc || im.src
        || (im.getAttribute && (im.getAttribute('src') || im.getAttribute('data-src'))) || '';
      if (_bnNoiseImgUrl(src)) return;
      if (_bnInAvatarOrHeader(im)) return;
      const iw = im.naturalWidth || 0, ih = im.naturalHeight || 0;
      const ir = im.getBoundingClientRect();
      if (iw > 0 && ih > 0) {
        if (iw < 64 || ih < 64) return;
      } else if (ir.width < 56 || ir.height < 56) return;
      if (src && !seen.has(src)) {
        seen.add(src);
        urls.push(src);
      }
    });
  }
  return urls.slice(0, 20);
}

function _bnDetailVideoUrl() {
  const roots = [];
  const m = document.querySelector('main');
  if (m) roots.push(m);
  document.querySelectorAll('[class*="article"], [class*="Article"], [class*="detail"], [class*="Detail"], [class*="content"]').forEach((el) => {
    if (roots.length < 8) roots.push(el);
  });
  if (!roots.length) roots.push(document.body);
  for (const root of roots) {
    const els = root.querySelectorAll('video, source');
    for (const el of els) {
      const src = (el.currentSrc || el.src
        || (el.getAttribute && (el.getAttribute('src') || el.getAttribute('data-src'))) || '').trim();
      if (!src) continue;
      const s = src.toLowerCase();
      if (s.startsWith('blob:') || s.startsWith('data:')) continue;
      if (s.includes('avatar') || s.includes('emoji') || s.includes('icon')) continue;
      return src;
    }
  }
  return '';
}
"""


def _visible_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _square_noise_url(href: str) -> bool:
    """非「我关注的人」动态：话题、指数、泛入口等（Following 页侧栏/推荐里常见）。"""
    if not href:
        return True
    h = href.lower()
    noise = (
        "/square/hashtag/",
        "/square/hashtags/",
        "fear-and-greed",
        "/square/topics/",
        "/square/market",
        "/square/leaderboard",
        "/square/ranking",
    )
    return any(x in h for x in noise)


def _profile_slug(href: str) -> str:
    m = re.search(r"/square/profile/([^/?#]+)", href or "", re.I)
    return (m.group(1) or "").strip()


def _scrape_log(msg: str) -> None:
    """阶段性状态，便于观察当前执行到哪一步。"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[binance_market_lists {ts}] {msg}", flush=True)


def _human_pause(lo: float = 0.35, hi: float = 1.25) -> None:
    """随机短停顿，模拟用户操作间隔。"""
    time.sleep(random.uniform(lo, hi))


def _human_pause_after_nav(lo: float = 0.85, hi: float = 2.9) -> None:
    """进入新页面后等待渲染与扫视，随机停顿。"""
    time.sleep(random.uniform(lo, hi))


def _wait_driver_execution_context(driver, timeout_sec: float = 18.0) -> bool:
    """
    新开页 / 关窗 / history.back 后，Chrome 可能短暂处于「无 JS 执行上下文」状态，
    此时任何 execute_script 会报 frame does not have execution context。轮询直到可执行。
    """
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


def _recover_profile_tab(driver, profile_href: str, *, log: str = "") -> None:
    """探测失败后强制回到 profile，避免后续步骤在坏上下文里继续跑。"""
    base = (profile_href or "").split("#")[0].strip()
    if not base:
        return
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    nav = None
    try:
        nav = cdp_get(driver, base, page_load_timeout=28, log_prefix="square")
        WebDriverWait(driver, 28).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        if not _wait_driver_execution_context(driver, 22.0):
            if log:
                _scrape_log(f"{log} 恢复后等待执行上下文仍超时")
        _human_pause_after_nav(0.55, 1.15)
    except Exception as e:
        _scrape_log(f"恢复 profile 失败 {base!r}: {e}")
    finally:
        cdp_restore(driver, nav)


def _modifier_open_new_tab_key():
    """Chrome：Ctrl+点击（Win/Linux）或 Cmd+点击（macOS）通常后台打开新标签。"""
    return Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL


def _action_chains_click_in_element_box(
    driver,
    el,
    *,
    log_prefix: str,
    use_random_offset: bool = True,
    background_tab: bool = False,
) -> bool:
    """
    用 Selenium ActionChains 发真实指针序列（相对元素中心再随机偏移后 click），
    避免 JS 里 dispatchEvent(MouseEvent) 被 React 等直接忽略。
    失败时依次回退 element.click()、arguments[0].click()。
    background_tab=True 时先尝试修饰键+左键（尽量静默新开标签），再回退普通点击。
    """
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center'});", el
        )
        _human_pause(0.18, 0.42)
        rect = el.rect
        w = float((rect or {}).get("width") or 0)
        h = float((rect or {}).get("height") or 0)
        if w < 6 or h < 6:
            _scrape_log(f"{log_prefix} 元素过小 w={w:.0f} h={h:.0f}，跳过点击")
            return False
        half_w = int(w // 2)
        half_h = int(h // 2)
        mx = max(2, int(w * 0.1))
        my = max(2, int(h * 0.1))
        if use_random_offset and half_w > mx and half_h > my:
            dx = random.randint(-half_w + mx, half_w - mx)
            dy = random.randint(-half_h + my, half_h - my)
        else:
            dx, dy = 0, 0
        _scrape_log(
            f"{log_prefix} 实点点击 ActionChains（相对元素中心偏移 dx={dx}, dy={dy}）"
        )
        if background_tab and SQUARE_VIDEO_BACKGROUND_TAB_CLICK:
            mod = _modifier_open_new_tab_key()
            try:
                (
                    ActionChains(driver)
                    .move_to_element(el)
                    .move_by_offset(dx, dy)
                    .pause(0.07)
                    .key_down(mod)
                    .click()
                    .key_up(mod)
                    .pause(0.05)
                    .perform()
                )
                _scrape_log(
                    f"{log_prefix} 已使用修饰键+左键点击（尽量后台新标签，修饰键={mod!r}）"
                )
                return True
            except Exception as e_mod:
                _scrape_log(f"{log_prefix} 修饰键点击失败，回退普通左键: {e_mod}")
        (
            ActionChains(driver)
            .move_to_element(el)
            .move_by_offset(dx, dy)
            .pause(0.07)
            .click()
            .pause(0.05)
            .perform()
        )
        return True
    except Exception as e:
        _scrape_log(f"{log_prefix} ActionChains 异常，回退 element.click: {e}")
        try:
            el.click()
            _scrape_log(f"{log_prefix} 已用 element.click()")
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", el)
                _scrape_log(f"{log_prefix} 已用 JS arguments[0].click()")
                return True
            except Exception as e2:
                _scrape_log(f"{log_prefix} 点击全部失败: {e2}")
                return False


def _human_jitter_scroll_pause() -> None:
    """滚动时每一步间隔略随机。"""
    time.sleep(random.uniform(0.16, 0.38))


def _priority_slugs_ordered() -> List[str]:
    """从 PRIORITY_FOLLOW_PROFILES 解析 slug，保持列表顺序、去重。"""
    out: List[str] = []
    seen: Set[str] = set()
    for raw in PRIORITY_FOLLOW_PROFILES:
        s = (raw or "").strip()
        if not s:
            continue
        if "/square/profile/" in s:
            slug = _profile_slug(s).lower()
        else:
            slug = s.strip().strip("/").lower()
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _profile_live_tab_url(profile_href: str) -> str:
    base = (profile_href or "").split("#")[0].strip()
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}tab=live"


def _profile_href_key(href: str) -> str:
    """用于去重：同一人主页带不带 query 视为同一 profile。"""
    return (href or "").strip().split("#")[0].strip().rstrip("/")


def _merge_priority_profiles(
    collected: List[Dict[str, str]],
    priority_slugs_ordered: List[str],
) -> List[Dict[str, str]]:
    """对每个重点 slug（按配置顺序）：Following 页有则用之，否则拼 profile URL 仍做巡检。"""
    if not priority_slugs_ordered:
        return collected
    by_slug: Dict[str, Dict[str, str]] = {}
    for p in collected:
        sl = (p.get("slug") or _profile_slug(p.get("href") or "")).lower()
        if sl:
            by_slug[sl] = p
    out: List[Dict[str, str]] = []
    for slug in priority_slugs_ordered:
        if slug in by_slug:
            out.append(by_slug[slug])
        else:
            out.append(
                {
                    "name": slug,
                    "slug": slug,
                    "href": f"https://www.binance.com/zh-CN/square/profile/{slug}",
                }
            )
    return out


def _pick_live_url(profile_href: str, links: List[str]) -> str:
    """从页面链接中选「该用户」的直播入口，排除话题/帖子误匹配。"""
    slug = _profile_slug(profile_href).lower()
    if not slug:
        return _profile_live_tab_url(profile_href)
    good: List[str] = []
    for u in links or []:
        if not u or _square_noise_url(u):
            continue
        ul = u.lower()
        if "/square/post/" in ul:
            continue
        if "/square/hashtag/" in ul:
            continue
        good.append(u)
    prof_path = f"/square/profile/{slug}"
    for u in good:
        ul = u.lower()
        if prof_path in ul and ("tab=live" in ul or "/live" in ul or "broadcast" in ul):
            return u
    for u in good:
        if prof_path in ul:
            return u
    return _profile_live_tab_url(profile_href)


def _parse_symbol_from_row_text(txt: str) -> Optional[str]:
    if not txt:
        return None
    one_line = _visible_text(txt.replace("\n", " "))
    m = _ROW_SYMBOL_RE.search(one_line)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip()


def _scroll_page_load_lists(driver, scrolls: int = 14) -> None:
    """虚拟列表需要多次滚动才能把行渲染进 DOM。"""
    for _ in range(scrolls):
        driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.9));")
        _human_jitter_scroll_pause()
    driver.execute_script("window.scrollTo(0, 0);")
    _human_pause(0.28, 0.62)


def _scroll_feed_down_only(driver, scrolls: int, *, slow: bool = False) -> None:
    """只向下滚（不回到顶部），用于 profile 时间线加载更多帖子。"""
    for _ in range(scrolls):
        driver.execute_script(
            "window.scrollBy(0, Math.floor(window.innerHeight * 0.88));"
        )
        if slow:
            time.sleep(random.uniform(0.35, 0.78))
        else:
            _human_jitter_scroll_pause()


def _scroll_profile_feed_until_stable(driver, max_rounds: int = 40) -> None:
    """
    主页时间线下滚：若任意 create-time 出现「n月n日」则至少已超约一天，停止继续下滚；
    否则直到帖子链接数不再增长。
    """
    last = -1
    stable = 0
    for _ in range(max_rounds):
        _scroll_feed_down_only(driver, scrolls=5, slow=True)
        try:
            hit_month_day = driver.execute_script(
                r"""
const nodes = document.querySelectorAll('[class*="create-time"]');
for (const n of nodes) {
  const t = (n.innerText || n.textContent || '').replace(/\s+/g, ' ').trim();
  if (/\d{1,2}\s*月\s*\d{1,2}\s*日/.test(t)) return true;
}
return false;
"""
            )
            if hit_month_day:
                _scrape_log(
                    "时间线已出现「月日」形式日期（通常 ≥1 天前），停止继续下滚"
                )
                break
        except Exception:
            pass
        try:
            n = int(
                driver.execute_script(
                    r"""
const anchors = Array.from(document.querySelectorAll('a[href*="/square/"]'));
let cnt = 0;
for (const a of anchors) {
  const h = ((a.href || '').split('#')[0] || '').toLowerCase();
  if (!h) continue;
  if (h.includes('/square/post/') || h.includes('/square/audio/') || h.includes('/square/article/')) {
    cnt += 1;
  }
}
return cnt;
"""
                )
                or 0
            )
        except Exception:
            n = 0
        if n == last:
            stable += 1
            if stable >= 5 and n > 0:
                break
        else:
            stable = 0
        last = n
        _human_pause(0.5, 1.15)


def _merge_posts_by_href(*lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 href 去重合并；正文取更长者，image_urls 合并去重，并保留 video_url。"""
    by_href: Dict[str, Dict[str, Any]] = {}
    for lst in lists:
        for p in lst:
            if not isinstance(p, dict):
                continue
            h = (p.get("href") or "").strip()
            if not h:
                continue
            if h not in by_href:
                by_href[h] = dict(p)
                continue
            o = by_href[h]
            imgs = (o.get("image_urls") or []) + (p.get("image_urls") or [])
            o["image_urls"] = list(dict.fromkeys(imgs))[:24]
            if len(str(p.get("raw") or "")) > len(str(o.get("raw") or "")):
                o["raw"] = p.get("raw", "")
                o["title"] = p.get("title", o.get("title", ""))
                o["author"] = p.get("author", o.get("author", ""))
                o["time"] = p.get("time", o.get("time", ""))
            o["published_iso"] = (p.get("published_iso") or o.get("published_iso") or "")
            o["time_label"] = (p.get("time_label") or o.get("time_label") or "")
            o["is_pinned"] = bool(o.get("is_pinned") or p.get("is_pinned"))
            o["video_url"] = (p.get("video_url") or o.get("video_url") or "")
            o["audio_m3u8_url"] = (
                p.get("audio_m3u8_url")
                or p.get("m3u8_url")
                or o.get("audio_m3u8_url")
                or ""
            )
            o["square_audio_replay_url"] = (
                p.get("square_audio_replay_url") or o.get("square_audio_replay_url") or ""
            )
    return list(by_href.values())


def _timeline_post_href_key_for_patch(
    by_href: Dict[str, Dict[str, Any]], post_ph: str
) -> str:
    """时间线里 href 可能与卡片/回播页解析的 URL 不完全一致（域名、locale），用 post id 对齐。"""
    ph = (post_ph or "").strip().split("#")[0]
    if not ph or "/square/post/" not in ph.lower():
        return ""
    if ph in by_href:
        return ph
    m = re.search(r"/square/post/(\d+)", ph, re.I)
    if not m:
        return ""
    pid = m.group(1)
    for k in by_href:
        if "/square/post/" not in k.lower():
            continue
        m2 = re.search(r"/square/post/(\d+)", k, re.I)
        if m2 and m2.group(1) == pid:
            return k
    return ""


def _apply_audio_replay_patches_to_posts(
    posts: List[Dict[str, Any]],
    patches: List[Dict[str, Any]],
    profile_author_slug: str = "",
) -> None:
    """
    把回播页 URL + network m3u8 合并到对应 /square/post/... 帖子（与 binance_posts_state 键一致）。
    必须有 post_href；不再用 audio/replay 作为独立 state 键。
    """
    if not patches:
        return
    by_href: Dict[str, Dict[str, Any]] = {}
    for p in posts:
        if not isinstance(p, dict):
            continue
        h = (p.get("href") or "").strip().split("#")[0]
        if h:
            by_href[h] = p
    slug = (profile_author_slug or "").strip().lower()
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        post_ph = (patch.get("post_href") or "").strip().split("#")[0]
        replay = (
            (patch.get("replay_href") or patch.get("square_audio_replay_url") or "")
            .strip()
            .split("#")[0]
        )
        pslug = (patch.get("author_slug") or slug or "").strip().lower()
        t = (patch.get("title") or "").strip()
        m3 = (patch.get("audio_m3u8_url") or "").strip()
        rep = (patch.get("square_audio_replay_url") or replay or "").strip().split("#")[0]

        if not post_ph or "/square/post/" not in post_ph.lower():
            continue
        if not m3 and not (rep or replay):
            continue

        key = _timeline_post_href_key_for_patch(by_href, post_ph)
        if key:
            tgt = by_href[key]
            if m3:
                tgt["audio_m3u8_url"] = m3
            sq = ""
            if rep and "/square/audio/replay" in rep.lower():
                sq = rep
            elif replay and "/square/audio/replay" in replay.lower():
                sq = replay
            if sq:
                tgt["square_audio_replay_url"] = sq
            if t and not str(tgt.get("title") or "").strip():
                tgt["title"] = t
                tgt["raw"] = t
            continue

        sq_url = ""
        if rep and "/square/audio/replay" in rep.lower():
            sq_url = rep
        elif replay and "/square/audio/replay" in replay.lower():
            sq_url = replay
        stub: Dict[str, Any] = {
            "href": post_ph,
            "title": t or "",
            "raw": t or "",
            "author": pslug,
            "author_slug": pslug,
            "time": "",
            "published_iso": "",
            "time_label": "",
            "published_at": "",
            "is_pinned": False,
            "image_urls": [],
            "video_url": "",
            "audio_m3u8_url": m3,
            "square_audio_replay_url": sq_url,
        }
        posts.append(stub)
        by_href[post_ph] = stub


def _post_id_from_href(href: str) -> str:
    m = re.search(r"/square/post/(\d+)", href or "", re.I)
    if m:
        return m.group(1)
    m2 = re.search(r"/square/(?:video|article)/(\d+)", href or "", re.I)
    if m2:
        return m2.group(1)
    return re.sub(r"\W+", "_", (href or ""))[-48:]


def _is_noise_image_url(u: str) -> bool:
    """与页面端 _bnNoiseImgUrl 对齐，下载前再滤一层（含历史 JSON 里的脏链）。"""
    s = (u or "").lower()
    if not s or s.startswith("data:"):
        return True
    for k in (
        "avatar",
        "userpic",
        "/icon",
        "favicon",
        "emoji",
        "badge",
        "qrcode",
        "sprite",
    ):
        if k in s:
            return True
    if "logo" in s and "binance" in s:
        return True
    m = re.search(r"\b(\d{1,3})x(\d{1,3})\b", s)
    if m and int(m.group(1)) <= 96 and int(m.group(2)) <= 96:
        return True
    return False


def _square_image_dir_has_files(sub_dir: str) -> bool:
    """post_id 子目录下是否已有常见图片文件（用于详情缓存命中时跳过重复下载）。"""
    if not sub_dir or not os.path.isdir(sub_dir):
        return False
    try:
        for name in os.listdir(sub_dir):
            low = name.lower()
            if low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                if os.path.isfile(os.path.join(sub_dir, name)):
                    return True
    except OSError:
        pass
    return False


def _collect_image_paths_in_dir(sub_dir: str) -> List[str]:
    """列出子目录内图片文件的绝对路径，按文件名排序。"""
    out: List[str] = []
    if not sub_dir or not os.path.isdir(sub_dir):
        return out
    try:
        for name in sorted(os.listdir(sub_dir)):
            low = name.lower()
            if low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                fp = os.path.join(sub_dir, name)
                if os.path.isfile(fp):
                    out.append(os.path.abspath(fp))
    except OSError:
        pass
    return out


def _download_square_post_images(
    driver, posts: List[Dict[str, Any]], base_dir: str
) -> None:
    """下载列表与正文页合并后的 image_urls（已滤噪声链）。"""
    if requests is None:
        _scrape_log("未安装 requests，跳过图片下载")
        return
    root = os.path.abspath(base_dir)
    os.makedirs(root, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )
    try:
        for c in driver.get_cookies():
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"))
    except Exception:
        pass

    for p in posts:
        if not isinstance(p, dict):
            continue
        try:
            urls = [
                x for x in (p.get("image_urls") or []) if not _is_noise_image_url(str(x))
            ]
            if not urls:
                continue
            href = (p.get("href") or "").strip()
            pid = _post_id_from_href(href)
            sub = os.path.join(root, pid) if pid else root
            if p.get("_square_detail_cache_hit") and pid and _square_image_dir_has_files(
                sub
            ):
                if not (p.get("saved_image_paths") or []):
                    p["saved_image_paths"] = _collect_image_paths_in_dir(sub)
                _scrape_log(
                    f"跳过下载 post_id={pid}（详情缓存命中且本地目录已有配图）→ {sub}"
                )
                continue
            os.makedirs(sub, exist_ok=True)
            saved: List[str] = []
            for i, u in enumerate(urls[:12]):
                u = (u or "").strip()
                if not u or u.startswith("data:"):
                    continue
                try:
                    r = session.get(u, timeout=45)
                    r.raise_for_status()
                    ct = (r.headers.get("Content-Type") or "").lower()
                    ext = ".jpg"
                    if "png" in ct or u.lower().endswith(".png"):
                        ext = ".png"
                    elif "webp" in ct or u.lower().endswith(".webp"):
                        ext = ".webp"
                    elif "gif" in ct:
                        ext = ".gif"
                    fp = os.path.join(sub, f"img_{i}{ext}")
                    with open(fp, "wb") as f:
                        f.write(r.content)
                    saved.append(fp)
                except Exception as e:
                    _scrape_log(f"图片下载失败 ({i}): {u[:60]}… — {e}")
            if saved:
                p["saved_image_paths"] = saved
                _scrape_log(f"已保存 {len(saved)} 张图片 → {sub}")
        finally:
            if isinstance(p, dict):
                p.pop("_square_detail_cache_hit", None)


def _find_post_record_in_state_buckets(
    posts_buckets: Any, href: str
) -> Optional[Dict[str, Any]]:
    if not isinstance(posts_buckets, dict) or not href:
        return None
    for inner in posts_buckets.values():
        if isinstance(inner, dict) and href in inner:
            r = inner.get(href)
            return r if isinstance(r, dict) else None
    return None


def _merge_square_detail_from_record(p: Dict[str, Any], rec: Dict[str, Any]) -> None:
    """把 state 里已存的详情字段合并到本次内存帖子（缓存命中时用）。"""
    imgs = list(p.get("image_urls") or []) + list(rec.get("image_urls") or [])
    p["image_urls"] = list(dict.fromkeys(imgs))[:24]
    rv = str(rec.get("video_url") or "").strip()
    if rv and not str(p.get("video_url") or "").strip():
        p["video_url"] = rv
    sp = rec.get("saved_image_paths")
    if isinstance(sp, list) and sp and not (p.get("saved_image_paths") or []):
        p["saved_image_paths"] = list(sp)


def _enrich_post_images_from_detail_pages(
    driver,
    posts: List[Dict[str, Any]],
    max_pages: int = MAX_POST_DETAIL_ENRICH_PAGES,
    posts_state_path: Optional[str] = None,
) -> None:
    """进入 /square/post/ 等正文页抓取正文区域配图（与列表卡片合并去重）；逐项略慢打开减少漏载。
    若提供 posts_state_path 且其中 detail_fetch_cache 已记录该 post_id，则跳过打开详情页，
    并从 state.posts 合并已有 image_urls / video_url / saved_image_paths。
    """
    if not posts:
        return
    n = min(max(1, int(max_pages)), len(posts))
    state_for_cache: Optional[Dict[str, Any]] = None
    cache_mut: Dict[str, Any] = {}
    cache_dirty = False
    if posts_state_path and os.path.isfile(posts_state_path):
        try:
            state_for_cache = load_posts_state(posts_state_path)
            c = state_for_cache.setdefault("detail_fetch_cache", {})
            if isinstance(c, dict):
                cache_mut = c
            else:
                cache_mut = {}
                state_for_cache["detail_fetch_cache"] = cache_mut
        except Exception as e:
            _scrape_log(f"详情缓存：读取 state 失败，将不跳过详情页 — {e}")
            state_for_cache = None
            cache_mut = {}
    _scrape_log(f"打开帖子正文页补充配图（本轮最多 {n} 篇；详情缓存={'开' if state_for_cache else '关'}）…")
    for p in posts[:n]:
        if not isinstance(p, dict):
            continue
        href = (p.get("href") or "").strip()
        hl = href.lower()
        if not href or (
            "/square/post/" not in hl
            and "/square/video/" not in hl
            and "/square/article/" not in hl
        ):
            continue
        post_id = _post_id_from_href(href)
        if state_for_cache and post_id and detail_fetch_cache_entry_fresh(
            cache_mut.get(post_id)
        ):
            rec = _find_post_record_in_state_buckets(
                state_for_cache.get("posts"), href
            )
            if isinstance(rec, dict) and (
                rec.get("image_urls")
                or str(rec.get("video_url") or "").strip()
                or rec.get("saved_image_paths")
            ):
                _merge_square_detail_from_record(p, rec)
                p["_square_detail_cache_hit"] = True
                _scrape_log(
                    f"详情缓存命中 post_id={post_id}，跳过打开详情页（合并 state 内已存字段）"
                )
                continue
            if post_id in cache_mut:
                cache_mut.pop(post_id, None)
                cache_dirty = True
                _scrape_log(
                    f"详情缓存孤儿 post_id={post_id}（state 中无对应帖子），已清除缓存并重新抓取"
                )
        nav = None
        try:
            nav = cdp_get(driver, href, page_load_timeout=18, log_prefix="square")
            WebDriverWait(driver, 18).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause_after_nav(1.45, 3.1)
            _human_pause(0.4, 0.95)
            extra = driver.execute_script(
                _SQUARE_ATTACHMENT_IMG_JS + "\nreturn _bnDetailArticleImages();"
            )
            video_url = driver.execute_script(
                _SQUARE_ATTACHMENT_IMG_JS + "\nreturn _bnDetailVideoUrl();"
            )
            cur = [x for x in (p.get("image_urls") or []) if x]
            merged = list(dict.fromkeys(cur + list(extra or [])))[:24]
            p["image_urls"] = merged
            if video_url and not str(p.get("video_url") or "").strip():
                p["video_url"] = str(video_url).strip()
        except Exception:
            continue
        finally:
            cdp_restore(driver, nav)
        if state_for_cache is not None and post_id:
            cache_mut[post_id] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "v": DETAIL_FETCH_CACHE_VERSION,
            }
            cache_dirty = True
        _human_pause(0.55, 1.35)
    if state_for_cache is not None and cache_dirty and posts_state_path:
        try:
            save_posts_state(posts_state_path, state_for_cache)
            _scrape_log("详情缓存已写回 binance_posts_state.json（detail_fetch_cache）")
        except Exception as e:
            _scrape_log(f"详情缓存写回失败: {e}")


def _extract_rows_from_table_elements(driver, max_items: int) -> List[Dict[str, str]]:
    """优先用表格行 textContent（币安常用 bn-table-tbody）。"""
    selectors = (
        "tbody.bn-table-tbody tr",
        "table tbody tr",
        "[class*='table-tbody'] tr",
        "[class*='Table'] tbody tr",
        "div[role='row']",
    )
    seen: set[str] = set()
    out: List[Dict[str, str]] = []
    for sel in selectors:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue
        if len(rows) < 2:
            continue
        for el in rows:
            if len(out) >= max_items:
                break
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            except Exception:
                pass
            raw = (el.text or el.get_attribute("textContent") or "").strip()
            if len(raw) < 4:
                continue
            sym = _parse_symbol_from_row_text(raw)
            if not sym:
                continue
            key = sym.upper().replace("/", "")
            if key in seen:
                continue
            seen.add(key)
            pcts = re.findall(r"[-+]?\d+(?:\.\d+)?%", raw)
            prices = re.findall(
                r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", raw.replace(",", "")
            )
            change = pcts[-1] if pcts else ""
            price = ""
            for p in reversed(prices):
                if len(p) >= 2:
                    price = p
                    break
            out.append(
                {
                    "symbol": sym,
                    "price": price,
                    "change": change,
                    "raw": _visible_text(raw),
                }
            )
        if len(out) >= min(5, max_items):
            break
    return out[:max_items]


def _extract_rows_via_js(driver, max_items: int = 30) -> List[Dict[str, str]]:
    """
    兜底：用 JS 扫 tr/role=row，正则支持小写交易对。
    """
    return driver.execute_script(
        """
const maxItems = arguments[0];
const isVisible = (el) => {
  const style = window.getComputedStyle(el);
  if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
  const r = el.getBoundingClientRect();
  return r.width > 1 && r.height > 1;
};
const nodes = Array.from(document.querySelectorAll('tr, [role="row"], li'));
const out = [];
const seen = new Set();
const pairRe = /\\b([A-Za-z0-9]{2,20}(?:USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH|BNB|TRY|EUR)(?:\\.P)?)\\b/i;
const pairRe2 = /\\b([A-Za-z0-9]{2,15}\\/[A-Za-z0-9]{2,15})\\b/;
const pctRe = /[-+]?\\d+(?:\\.\\d+)?%/g;
const priceRe = /(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?/g;

for (const el of nodes) {
  if (!isVisible(el)) continue;
  const txt = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  if (!txt || txt.length < 4) continue;

  const m1 = txt.match(pairRe);
  const m2 = txt.match(pairRe2);
  let symbol = '';
  if (m1 && m1[1]) symbol = m1[1];
  else if (m2 && m2[1]) symbol = m2[1];
  else continue;

  const symKey = symbol.toUpperCase();
  if (seen.has(symKey)) continue;
  seen.add(symKey);
  const pcts = txt.match(pctRe) || [];
  const prices = txt.match(priceRe) || [];
  const change = pcts.length ? pcts[pcts.length - 1] : '';
  let price = '';
  if (prices.length) {
    for (let i = prices.length - 1; i >= 0; i--) {
      if ((prices[i] || '').length >= 2) { price = prices[i]; break; }
    }
  }

  out.push({ symbol, price, change, raw: txt });
  if (out.length >= maxItems) break;
}
return out;
        """,
        max_items,
    )


def _extract_rows_best_effort(driver, max_items: int) -> List[Dict[str, str]]:
    rows = _extract_rows_from_table_elements(driver, max_items)
    if len(rows) >= 3:
        return rows
    rows = _extract_rows_via_js(driver, max_items)
    return rows


def _extract_square_following(
    driver, max_items: int, priority_slugs: Optional[Set[str]] = None
) -> Dict[str, List[Dict[str, str]]]:
    """
    抓币安 Square Following 页（tab=Following）信息流：
    - latest_posts：仅保留 `/square/post/` 动态（代表关注流里的帖子/文章），排除话题/指数等泛链
    - lives：留空（谁在直播以 profile 巡检为准，避免把话题/帖子误当直播）

    说明：侧栏「热门话题」等也会出现 /square/ 链接，必须过滤。
    """
    # 兜底多滚动一下，确保虚拟列表渲染（略慢，减少漏帖）
    _scroll_page_load_lists(driver, scrolls=40)
    _human_pause(1.2, 2.5)

    priority_arg = (
        sorted(priority_slugs) if priority_slugs else []
    )
    return driver.execute_script(
        _SQUARE_ATTACHMENT_IMG_JS
        + """
const maxItems = arguments[0];
const prioritySlugs = new Set((arguments[1] || []).map((s) => String(s).toLowerCase()));
const out = { lives: [], latest_posts: [] };
const seen = new Set();

const isNoise = (href) => {
  const h = (href || '').toLowerCase();
  if (h.includes('/square/hashtag/')) return true;
  if (h.includes('/square/hashtags/')) return true;
  if (h.includes('fear-and-greed')) return true;
  if (h.includes('/square/topics/')) return true;
  if (h.includes('/square/market')) return true;
  if (h.includes('/square/leaderboard')) return true;
  return false;
};

// 帖子可能是 /square/post/、/square/video/、/square/article/，统一纳入
const anchors = Array.from(document.querySelectorAll('a[href*="/square/"]')).filter((a) => {
  const h = ((a.href || '').split('#')[0] || '').toLowerCase();
  return h.includes('/square/post/') || h.includes('/square/video/') || h.includes('/square/article/');
});

const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();

const findTime = (t) => {
  if (!t) return '';
  const m = (t.match(/\\d{1,2}:\\d{2}/) || [])[0] || '';
  if (m) return m;
  const d = (t.match(/\\d{4}-\\d{2}-\\d{2}/) || [])[0] || '';
  return d;
};

for (const a of anchors) {
  if (out.latest_posts.length >= maxItems) break;
  const href = a.href || '';
  if (!href || seen.has(href)) continue;
  if (isNoise(href)) continue;
  let authorSlug = '';
  let n = a;
  for (let i = 0; i < 18 && n; i++) {
    const prof = Array.from(n.querySelectorAll ? n.querySelectorAll('a[href*="/square/profile/"]') : []);
    for (const pa of prof) {
      const ph = (pa.href || '').split('#')[0];
      const m = ph.match(/\\/square\\/profile\\/([^\\/?#]+)/i);
      if (m && m[1]) { authorSlug = String(m[1]).toLowerCase(); break; }
    }
    if (authorSlug) break;
    n = n.parentElement;
  }
  if (prioritySlugs.size > 0) {
    if (!authorSlug || !prioritySlugs.has(authorSlug)) continue;
  }
  const text = (a.innerText || a.textContent || '').trim();
  const imageUrls = _bnCollectArticleImagesRelaxed(a);
  const videoUrl = _bnCollectVideoUrlFromCard(a);
  if ((!text || text.length < 4) && !videoUrl && imageUrls.length === 0) continue;

  const clean = norm(text);
  const parts = clean.split(' ').filter(Boolean);
  const title = parts.slice(0, 16).join(' ');
  const time = findTime(clean);

  let author = '';
  const dotIdx = clean.indexOf('·');
  if (dotIdx > 0 && dotIdx < 80) author = clean.slice(0, dotIdx).trim();
  if (!author) {
    for (const p of parts) {
      if (p.length >= 2 && p.length <= 24) { author = p; break; }
    }
  }

  const meta = _bnPostTimeFromCard(a);
  const item = {
    href,
    title: title || (videoUrl ? '视频帖' : title),
    author,
    author_slug: authorSlug,
    time: meta.time_label || findTime(clean),
    raw: clean,
    image_urls: imageUrls,
    video_url: videoUrl,
    published_iso: meta.published_iso,
    time_label: meta.time_label,
    is_pinned: meta.is_pinned,
  };
  out.latest_posts.push(item);
  seen.add(href);
}

out.latest_posts = out.latest_posts.slice(0, maxItems);
return out;
        """,
        max_items,
        priority_arg,
    )


def _extract_square_profile_posts(
    driver,
    profile_href: str,
    author_slug: str,
    max_items: int,
    *,
    probe_live: bool = False,
    author_display_name: str = "",
    view_all_url: str = DEFAULT_WATCHLIST_URL,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, str]], List[Dict[str, Any]]]:
    """
    打开用户 Square 主页，深度下滚加载虚拟列表，抓取该用户帖子（数量通常多于 Following 流首屏）。
    可选 probe_live：在同一轮访问内顺带做「是否在直播」检测，避免再次打开同一主页。
    第三项为视频回扫产生的 audio_replay_patches，供写入 watchlist 并由 process_watchlist_posts 合并到 state。
    """
    base = (profile_href or "").split("#")[0].strip()
    if not base:
        return [], None, []
    if probe_live:
        _scrape_log(f"打开主页拉取帖子并检测直播: {base}")
    else:
        _scrape_log(f"打开主页拉取帖子: {base}")
    with cdp_worker_tab(driver, base, page_load_timeout=25, log_prefix="square"):
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        _human_pause_after_nav(2.0, 4.2)
        _scroll_profile_feed_until_stable(driver)
        _human_pause(0.75, 1.65)
        slug_l = (author_slug or "").lower().strip()
        posts: List[Dict[str, str]] = (
            driver.execute_script(
            _SQUARE_ATTACHMENT_IMG_JS
            + """
const maxItems = arguments[0];
const authorSlug = String(arguments[1] || '').toLowerCase();
const out = [];
const seen = new Set();

const isNoise = (href) => {
  const h = (href || '').toLowerCase();
  if (h.includes('/square/hashtag/')) return true;
  if (h.includes('/square/hashtags/')) return true;
  if (h.includes('fear-and-greed')) return true;
  if (h.includes('/square/topics/')) return true;
  if (h.includes('/square/market')) return true;
  if (h.includes('/square/leaderboard')) return true;
  return false;
};

const anchors = Array.from(document.querySelectorAll('a[href*="/square/"]')).filter((a) => {
  const h = ((a.href || '').split('#')[0] || '').toLowerCase();
  return h.includes('/square/post/') || h.includes('/square/video/') || h.includes('/square/article/');
});
const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();

const findTime = (t) => {
  if (!t) return '';
  const m = (t.match(/\\d{1,2}:\\d{2}/) || [])[0] || '';
  if (m) return m;
  const d = (t.match(/\\d{4}-\\d{2}-\\d{2}/) || [])[0] || '';
  return d;
};

for (const a of anchors) {
  if (out.length >= maxItems) break;
  const href = (a.href || '').split('#')[0];
  if (!href || seen.has(href)) continue;
  if (isNoise(href)) continue;
  const text = (a.innerText || a.textContent || '').trim();
  const imageUrls = _bnCollectArticleImagesRelaxed(a);
  const videoUrl = _bnCollectVideoUrlFromCard(a);
  if ((!text || text.length < 4) && !videoUrl && imageUrls.length === 0) continue;

  const clean = norm(text);
  const parts = clean.split(' ').filter(Boolean);
  const title = parts.slice(0, 20).join(' ');

  let author = authorSlug;
  const dotIdx = clean.indexOf('·');
  if (dotIdx > 0 && dotIdx < 80) author = clean.slice(0, dotIdx).trim() || authorSlug;

  const meta = _bnPostTimeFromCard(a);
  out.push({
    href,
    title: title || (videoUrl ? '视频帖' : title),
    author,
    author_slug: authorSlug,
    time: meta.time_label || findTime(clean),
    raw: clean,
    image_urls: imageUrls,
    video_url: videoUrl,
    published_iso: meta.published_iso,
    time_label: meta.time_label,
    is_pinned: meta.is_pinned,
  });
  seen.add(href);
}
return out;
            """,
                max_items,
                slug_l,
            )
            or []
        )
        # 视频帖经常需要点中间播放区才会进入详情，补跑一轮中心点点击回扫。
        existing_hrefs = {(p.get("href") or "").strip() for p in posts if isinstance(p, dict)}
        video_scan_quota = min(max(12, max_items), 80)
        profile_audio_patches: List[Dict[str, Any]] = []
        if video_scan_quota > 0:
            extra_video, audio_replay_patches = _extract_profile_video_posts_by_center_click(
                driver, base, slug_l, existing_hrefs, max_items=video_scan_quota
            )
            profile_audio_patches = list(audio_replay_patches or [])
            if extra_video:
                posts = _merge_posts_by_href(extra_video, posts)
            if audio_replay_patches:
                _apply_audio_replay_patches_to_posts(posts, audio_replay_patches, slug_l)
            posts = posts[:max_items]
        live_hit: Optional[Dict[str, str]] = None
        if probe_live:
            _human_pause(0.55, 1.25)
            hint = (author_display_name or "").strip() or author_slug
            vu = (view_all_url or DEFAULT_WATCHLIST_URL).strip() or DEFAULT_WATCHLIST_URL
            status_home = _detect_live_on_current_square_page(driver)
            if status_home.get("is_live"):
                links = status_home.get("live_links") or []
                live_url = _pick_live_url(base, links)
                author_disp = hint or author_slug or slug_l
                live_hit = {
                    "author": author_disp,
                    "profile": base.split("#")[0],
                    "live_url": live_url,
                    "raw": "profile_home_probe",
                }
                _show_square_live_toast(
                    driver,
                    author=author_disp,
                    live_url=live_url,
                    view_all_url=vu,
                )
            else:
                _remove_square_live_toast(driver)
                live_hit = _probe_single_profile_live(
                    driver,
                    base,
                    author_hint=hint,
                    log_visit=False,
                    view_all_url=vu,
                )
        return posts, live_hit, profile_audio_patches


def _aspect_video_probe_random_click_and_log_opened_url(
    driver,
    profile_href: str,
    av_index: int,
    label_idx: int,
    patches_out: Optional[List[Dict[str, Any]]] = None,
    *,
    author_slug: str = "",
) -> None:
    """
    对页面内第 av_index 个 class 含 aspect-video 的元素，在矩形中部随机区域点击，
    打印打开后的 URL（新标签或同页跳转），并尽量回到 profile 页。
    若打开 /square/audio/replay：从卡片解析 /square/post/ 为 post_href；
    标题取点击前 text-PrimaryText；m3u8 仅从 performance 网络筛出；一并写入 patches 供合并到该帖。
    label_idx 为日志用 1-based 序号。
    """
    base = (profile_href or "").split("#")[0].strip()
    try:
        before_handles = list(driver.window_handles)
        before_url = (driver.current_url or "").split("#")[0]
    except WebDriverException as e:
        _scrape_log(f"aspect-video[{label_idx}] 探测: 取窗口状态失败 {e}")
        return
    if not _wait_driver_execution_context(driver, 14.0):
        _scrape_log(
            f"aspect-video[{label_idx}] 探测: 执行上下文未就绪，跳过（可稍后重试）"
        )
        return
    try:
        els = driver.find_elements(By.CSS_SELECTOR, '[class*="aspect-video"]')
    except WebDriverException:
        els = []
    except Exception:
        els = []
    if av_index >= len(els):
        _scrape_log(
            f"aspect-video[{label_idx}] 探测点击: 跳过（当前页仅 {len(els)} 个 aspect-video，索引 {av_index}）"
        )
        return
    el = els[av_index]
    post_href = ""
    try:
        post_href = str(
            driver.execute_script(_ASPECT_VIDEO_CARD_POST_HREF_JS, av_index) or ""
        ).strip().split("#")[0]
    except Exception:
        post_href = ""
    pre_click_title = ""
    try:
        pre_click_title = str(
            driver.execute_script(_ASPECT_VIDEO_PRE_CLICK_TITLE_JS, av_index) or ""
        ).strip()[:2000]
    except Exception:
        pre_click_title = ""
    _scrape_log(
        f"aspect-video[{label_idx}] 探测点击: 对第 {av_index + 1}/{len(els)} 个节点使用 Selenium 指针（非 JS 合成事件）"
    )
    opened_click = _action_chains_click_in_element_box(
        driver,
        el,
        log_prefix=f"aspect-video[{label_idx}]",
        use_random_offset=True,
        background_tab=True,
    )
    if not opened_click:
        return
    time.sleep(0.55)
    _human_pause_after_nav(0.45, 1.0)
    switched_new_tab = False
    opened_url = ""
    for _ in range(32):
        try:
            now_handles = list(driver.window_handles)
            if len(now_handles) > len(before_handles):
                new_handle = next(
                    (h for h in now_handles if h not in before_handles), None
                )
                if new_handle:
                    driver.switch_to.window(new_handle)
                    switched_new_tab = True
                    time.sleep(0.4)
                    _wait_driver_execution_context(driver, 12.0)
                    opened_url = (driver.current_url or "").split("#")[0]
                    break
            cur_u = (driver.current_url or "").split("#")[0]
            if cur_u and cur_u != before_url:
                opened_url = cur_u
                break
        except WebDriverException:
            time.sleep(0.35)
        time.sleep(0.22)
    try:
        if not opened_url:
            opened_url = (driver.current_url or "").split("#")[0]
    except WebDriverException:
        opened_url = ""
    if opened_url == before_url and not switched_new_tab:
        _scrape_log(f"aspect-video[{label_idx}] 打开后 URL: (无跳转)")
    else:
        _scrape_log(f"aspect-video[{label_idx}] 打开后 URL: {opened_url}")
    audio_m3u8 = ""
    is_audio_replay = bool(
        opened_url
        and opened_url != before_url
        and "/square/audio/replay" in opened_url.lower()
    )
    if is_audio_replay:
        time.sleep(1.0)
        _wait_driver_execution_context(driver, 18.0)
        for attempt in range(1, 10):
            try:
                snap = driver.execute_script(_AUDIO_REPLAY_M3U8_FROM_NETWORK_JS) or {}
                audio_m3u8 = str(snap.get("m3u8_url") or "").strip()
            except Exception as ex:
                _scrape_log(
                    f"aspect-video[{label_idx}] 回播页 network 筛 m3u8 失败(第{attempt}次): {ex}"
                )
            if audio_m3u8:
                break
            time.sleep(0.7)
        if (not post_href) or "/square/post/" not in (post_href or "").lower():
            try:
                ph2 = str(
                    driver.execute_script(
                        _SQUARE_AUDIO_REPLAY_PAGE_RESOLVE_POST_HREF_JS,
                        pre_click_title,
                    )
                    or ""
                ).strip().split("#")[0]
                if ph2 and "/square/post/" in ph2.lower():
                    post_href = ph2
            except Exception:
                pass
        replay_canon = opened_url.split("#")[0]
        if patches_out is not None and post_href and (audio_m3u8 or replay_canon):
            patches_out.append(
                {
                    "post_href": post_href,
                    "replay_href": replay_canon,
                    "square_audio_replay_url": replay_canon,
                    "title": pre_click_title,
                    "audio_m3u8_url": audio_m3u8,
                    "author_slug": (author_slug or "").strip().lower(),
                }
            )
            _scrape_log(
                f"aspect-video[{label_idx}] enrich → post={post_href[:72]}… "
                f"replay={'Y' if replay_canon else 'n'} m3u8={'Y' if audio_m3u8 else 'n'}"
            )
        elif patches_out is not None and not post_href:
            _scrape_log(
                f"aspect-video[{label_idx}] 未解析到 /square/post/ 链接，"
                "跳过写入 state（无合并目标）"
            )
    if switched_new_tab:
        # 不抢焦点：仅在保留新标签时在「新标签」上停留；否则先关/切回原页再 sleep
        if KEEP_VIDEO_DETAIL_TAB:
            if VIDEO_DETAIL_TAB_VISIBLE_SEC > 0:
                time.sleep(min(VIDEO_DETAIL_TAB_VISIBLE_SEC, 8.0))
            _scrape_log("保留视频详情新标签页（探测，KEEP_VIDEO_DETAIL_TAB=true）")
        else:
            try:
                driver.close()
            except Exception:
                pass
        try:
            if before_handles:
                driver.switch_to.window(before_handles[0])
        except Exception:
            pass
        if (not KEEP_VIDEO_DETAIL_TAB) and VIDEO_DETAIL_TAB_VISIBLE_SEC > 0:
            time.sleep(min(VIDEO_DETAIL_TAB_VISIBLE_SEC, 8.0))
        time.sleep(0.55)
        if not _wait_driver_execution_context(driver, 20.0):
            _scrape_log(
                f"aspect-video[{label_idx}] 关窗后执行上下文超时，强制打开 profile"
            )
            _recover_profile_tab(driver, base, log=f"aspect-video[{label_idx}]")
    try:
        cur = (driver.current_url or "").split("#")[0]
    except WebDriverException:
        cur = ""
    if base and cur and cur != base:
        try:
            driver.back()
            WebDriverWait(driver, 18).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause(0.85, 1.65)
        except Exception:
            driver.get(base)
            WebDriverWait(driver, 24).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause_after_nav(1.1, 2.1)
        if not _wait_driver_execution_context(driver, 18.0):
            _recover_profile_tab(driver, base, log=f"aspect-video[{label_idx}]_back")
    else:
        if not switched_new_tab:
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
                _human_pause(0.25, 0.55)
            except Exception:
                pass
    if not _wait_driver_execution_context(driver, 12.0):
        _recover_profile_tab(driver, base, log=f"aspect-video[{label_idx}]_收尾")


def _fetch_aspect_video_card_time_meta(driver, av_index: int) -> Dict[str, Any]:
    """当前 profile 页第 av_index 个 aspect-video 所在卡片的发帖时间（与 _bnPostTimeFromCard 一致）。"""
    try:
        r = driver.execute_script(
            _SQUARE_ATTACHMENT_IMG_JS
            + r"""
const i = arguments[0];
const list = document.querySelectorAll('[class*="aspect-video"]');
const el = list[i];
if (!el) return { published_iso: '', time_label: '', is_pinned: false };
return _bnPostTimeFromCard(el);
""",
            av_index,
        )
        return r if isinstance(r, dict) else {}
    except Exception:
        return {}


def _aspect_video_publish_time_should_skip(
    meta: Optional[Dict[str, Any]],
    ref_now: datetime,
    *,
    max_age_days: float,
) -> bool:
    """发帖时间早于 ref_now−max_age_days 则跳过；解析不到时间则 false（不跳过）。"""
    if not isinstance(meta, dict) or max_age_days <= 0:
        return False
    stub: Dict[str, Any] = {
        "published_iso": (meta.get("published_iso") or "").strip(),
        "time_label": (meta.get("time_label") or "").strip(),
        "time": (meta.get("time_label") or meta.get("time") or "").strip(),
    }
    dt = parse_published_to_dt(stub, ref_now)
    if dt is None:
        return False
    ref_u = ref_now if ref_now.tzinfo else ref_now.replace(tzinfo=timezone.utc)
    ref_u = ref_u.astimezone(timezone.utc)
    pub_u = dt.astimezone(timezone.utc)
    cutoff = ref_u - timedelta(days=float(max_age_days))
    return pub_u < cutoff


def _extract_profile_video_posts_by_center_click(
    driver,
    profile_href: str,
    author_slug: str,
    existing_hrefs: Set[str],
    max_items: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    视频帖有时只有中间播放区可点，a[href] 不稳定。
    这里通过「中心点点击」回扫视频卡片，进入详情后补抓帖子链接与时间信息。
    返回 (extra_posts, audio_replay_patches)；后者供合并 square/audio/replay 与 m3u8。
    """
    if max_items <= 0:
        return [], []
    ref_now = datetime.now(timezone.utc)
    base = (profile_href or "").split("#")[0].strip()
    slug_l = (author_slug or "").lower().strip()
    out: List[Dict[str, Any]] = []
    audio_replay_patches: List[Dict[str, Any]] = []
    seen = {(_profile_href_key(h) if "/square/" in (h or "") else (h or "")) for h in existing_hrefs}
    max_scan = min(max(8, max_items * 4), 120)
    _scrape_log(f"视频卡片中心点击回扫开始（最多扫描 {max_scan} 个候选）")
    try:
        aspect_video_count = int(
            driver.execute_script(
                "return document.querySelectorAll('[class*=\"aspect-video\"]').length;"
            )
            or 0
        )
    except Exception:
        aspect_video_count = 0
    _scrape_log(f"aspect-video 元素数量：{aspect_video_count}")
    try:
        aspect_primary_texts = driver.execute_script(
            r"""
const cardRoot = (el) => el && (el.closest('article')
  || el.closest('[class*="post"]')
  || el.closest('[class*="card"]')
  || el.closest('[role="button"]')
  || el.parentElement);
const roots = Array.from(document.querySelectorAll('[class*="aspect-video"]'));
const out = [];
for (const av of roots) {
  const root = cardRoot(av);
  if (!root) {
    out.push('');
    continue;
  }
  const els = root.querySelectorAll('[class*="text-PrimaryText"]');
  const texts = [];
  for (const e of els) {
    const t = String((e && (e.innerText || e.textContent)) || '')
      .replace(/\s+/g, ' ')
      .trim();
    if (t && !texts.includes(t)) texts.push(t);
  }
  out.push(texts.join(' | '));
}
return out;
"""
        )
    except Exception:
        aspect_primary_texts = None
    if isinstance(aspect_primary_texts, list):
        for i, txt in enumerate(aspect_primary_texts):
            s = (txt or "").strip()
            if s:
                _scrape_log(
                    f"aspect-video[{i + 1}] text-PrimaryText: {s[:500]}"
                    + ("…" if len(s) > 500 else "")
                )
            else:
                _scrape_log(f"aspect-video[{i + 1}] text-PrimaryText: (无)")
    if ASPECT_VIDEO_PROBE_CLICK_AFTER_TEXT and aspect_video_count > 0:
        _scrape_log(
            f"aspect-video：已打印 text-PrimaryText，随后在元素矩形内随机点击（共 {aspect_video_count} 个）…"
        )
        for av_i in range(aspect_video_count):
            try:
                tmeta = _fetch_aspect_video_card_time_meta(driver, av_i)
                if _aspect_video_publish_time_should_skip(
                    tmeta,
                    ref_now,
                    max_age_days=ASPECT_VIDEO_SCAN_MAX_PUBLISH_AGE_DAYS,
                ):
                    _scrape_log(
                        f"aspect-video[{av_i + 1}] 发帖超过 "
                        f"{ASPECT_VIDEO_SCAN_MAX_PUBLISH_AGE_DAYS:g} 天，跳过探测点击"
                    )
                    continue
                before_n = len(audio_replay_patches)
                _aspect_video_probe_random_click_and_log_opened_url(
                    driver,
                    base,
                    av_i,
                    av_i + 1,
                    audio_replay_patches,
                    author_slug=slug_l,
                )
                # 只保留第一种获取方式：拿到首条回播结果后即停止后续 aspect-video 点击。
                if len(audio_replay_patches) > before_n:
                    _scrape_log(
                        "aspect-video 探测已获取首条回播 URL，停止继续点击其余节点"
                    )
                    break
            except Exception as ex:
                _scrape_log(f"aspect-video[{av_i + 1}] 探测点击异常: {ex}")
                _recover_profile_tab(driver, base, log=f"aspect-video[{av_i + 1}]")
    click_opened = 0
    detail_with_href = 0
    clicked_from_aspect = 0
    detail_urls_seen: List[str] = []

    for idx in range(max_scan):
        if len(out) >= max_items:
            break
        try:
            candidate = driver.execute_script(
                _SQUARE_ATTACHMENT_IMG_JS
                + r"""
const i = arguments[0];
const cards = [];
const pushCard = (el) => {
  if (!el) return;
  let c = el.closest('article')
    || el.closest('[class*="post"]')
    || el.closest('[class*="card"]')
    || el.closest('[role="button"]')
    || el.parentElement;
  if (!c) return;
  cards.push(c);
};
document.querySelectorAll('[class*="aspect-video"]').forEach(pushCard);
document.querySelectorAll('video, [class*="video-player"], [class*="VideoPlayer"], [class*="play-btn"], [class*="playButton"]').forEach(pushCard);
const uniq = [];
const seen = new Set();
for (const c of cards) {
  if (!c) continue;
  const r = c.getBoundingClientRect();
  if (r.width < 120 || r.height < 80) continue;
  const key = [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)].join(':');
  if (seen.has(key)) continue;
  seen.add(key);
  uniq.push(c);
}
const picked = uniq[i] || null;
if (!picked) return null;
const cls = String(picked.className || '');
const fromAspect = cls.includes('aspect-video') || !!picked.querySelector('[class*="aspect-video"]');
let anchorHref = '';
const a = picked.closest('a[href]') || picked.querySelector('a[href]');
if (a && a.href) anchorHref = String(a.href).split('#')[0];
let postHref = '';
for (const pa of picked.querySelectorAll('a[href*="/square/post/"]')) {
  const h = (pa.href || '').split('#')[0];
  if ((h || '').toLowerCase().includes('/square/post/')) { postHref = h; break; }
}
let timeMeta = { published_iso: '', time_label: '', is_pinned: false };
if (fromAspect) {
  let avEl = null;
  if (cls.includes('aspect-video')) avEl = picked;
  if (!avEl) avEl = picked.querySelector('[class*="aspect-video"]');
  if (avEl) timeMeta = _bnPostTimeFromCard(avEl);
}
return { el: picked, from_aspect: fromAspect, anchor_href: anchorHref, post_href: postHref, time_meta: timeMeta };
""",
                idx,
            )
            if candidate is None:
                break
            from_aspect = bool(candidate.get("from_aspect")) if isinstance(candidate, dict) else False
            card_post_href = ""
            if isinstance(candidate, dict):
                card_post_href = (candidate.get("post_href") or "").strip().split("#")[0]
            if from_aspect and _aspect_video_publish_time_should_skip(
                candidate.get("time_meta") if isinstance(candidate, dict) else None,
                ref_now,
                max_age_days=ASPECT_VIDEO_SCAN_MAX_PUBLISH_AGE_DAYS,
            ):
                _scrape_log(
                    f"视频回扫[i={idx}] aspect 发帖超过 "
                    f"{ASPECT_VIDEO_SCAN_MAX_PUBLISH_AGE_DAYS:g} 天，跳过点击"
                )
                continue
            before_handles = list(driver.window_handles)
            before_url = (driver.current_url or "").split("#")[0]
            target_el = (
                candidate.get("el") if isinstance(candidate, dict) else candidate
            )
            opened = _action_chains_click_in_element_box(
                driver,
                target_el,
                log_prefix=f"视频回扫[i={idx}]",
                use_random_offset=True,
                background_tab=True,
            )
            if not opened:
                continue
            click_opened += 1
            if from_aspect:
                clicked_from_aspect += 1
            anchor_href = ""
            if isinstance(candidate, dict):
                anchor_href = (candidate.get("anchor_href") or "").strip()
            _human_pause_after_nav(0.5, 1.1)
            switched_new_tab = False
            for _ in range(18):
                now_handles = list(driver.window_handles)
                if len(now_handles) > len(before_handles):
                    new_handle = next((h for h in now_handles if h not in before_handles), None)
                    if new_handle:
                        driver.switch_to.window(new_handle)
                        switched_new_tab = True
                        break
                cur_url = (driver.current_url or "").split("#")[0]
                if cur_url and cur_url != before_url:
                    break
                time.sleep(0.2)
            # 视频页通常在打开后才发起 m3u8 请求，额外等待片刻再读取 performance 资源。
            time.sleep(0.9)
            _human_pause_after_nav(0.65, 1.35)
            detail = driver.execute_script(
                _SQUARE_ATTACHMENT_IMG_JS
                + r"""
const pageUrl = (location.href || '').split('#')[0];
const isPostUrl = (h) => {
  const x = (h || '').toLowerCase();
  return x.includes('/square/post/') || x.includes('/square/video/') || x.includes('/square/article/');
};
let href = isPostUrl(pageUrl) ? pageUrl : '';
if (!href) {
  const as = Array.from(document.querySelectorAll('a[href*="/square/"]'));
  for (const a of as) {
    const h = (a.href || '').split('#')[0];
    if (isPostUrl(h)) { href = h; break; }
  }
}
const h1 = document.querySelector('h1, h2, [class*="title"], [class*="Title"]');
const title = ((h1 && (h1.innerText || h1.textContent)) || '').replace(/\s+/g, ' ').trim();
let publishedIso = '';
let timeLabel = '';
const te = document.querySelector('time[datetime]');
if (te) {
  publishedIso = te.getAttribute('datetime') || '';
  timeLabel = (te.innerText || '').trim();
}
if (!timeLabel) {
  const ct = document.querySelector('[class*="create-time"], .create-time');
  if (ct) timeLabel = (ct.innerText || ct.textContent || '').replace(/\s+/g, ' ').trim();
}
const raw = ((document.querySelector('main') || document.body || {}).innerText || '')
  .replace(/\s+/g, ' ')
  .trim()
  .slice(0, 400);
const m3u8Set = new Set();
try {
  const perf = (performance && performance.getEntriesByType)
    ? performance.getEntriesByType('resource')
    : [];
  for (const e of perf || []) {
    const n = String((e && e.name) || '').trim();
    if (!n) continue;
    const low = n.toLowerCase();
    if (low.includes('.m3u8') || (low.includes('/static/live-ag/') && low.includes('m3u8'))) {
      m3u8Set.add(n.split('#')[0]);
    }
  }
} catch (_) {}
for (const m of document.querySelectorAll('video[src], source[src]')) {
  const s = String(m.getAttribute('src') || m.src || '').trim();
  if (!s) continue;
  if (s.toLowerCase().includes('.m3u8')) m3u8Set.add(s.split('#')[0]);
}
const m3u8Urls = Array.from(m3u8Set).slice(0, 8);
return {
  page_url: pageUrl,
  href,
  title,
  raw,
  published_iso: publishedIso,
  time_label: timeLabel,
  image_urls: _bnDetailArticleImages(),
  video_url: _bnDetailVideoUrl(),
  m3u8_urls: m3u8Urls,
  m3u8_url: m3u8Urls[0] || '',
};
""",
            ) or {}
            page_url = (detail.get("page_url") or "").strip()
            href = (detail.get("href") or "").strip() or page_url or anchor_href
            if "/square/audio/replay" in (page_url or "").lower() and card_post_href:
                href = card_post_href
            replay_page = "/square/audio/replay" in (page_url or "").lower()
            if replay_page and (
                not card_post_href or "/square/post/" not in (card_post_href or "").lower()
            ):
                try:
                    title_for_match = (detail.get("title") or "").strip()
                    ph_dom = str(
                        driver.execute_script(
                            _SQUARE_AUDIO_REPLAY_PAGE_RESOLVE_POST_HREF_JS,
                            title_for_match,
                        )
                        or ""
                    ).strip().split("#")[0]
                    if ph_dom and "/square/post/" in ph_dom.lower():
                        card_post_href = ph_dom
                        href = card_post_href
                except Exception:
                    pass
            m3u8_one = (detail.get("m3u8_url") or "").strip()
            if replay_page and card_post_href and (m3u8_one or page_url):
                audio_replay_patches.append(
                    {
                        "post_href": card_post_href,
                        "replay_href": page_url.split("#")[0],
                        "square_audio_replay_url": page_url.split("#")[0],
                        "title": "",
                        "audio_m3u8_url": m3u8_one,
                        "author_slug": slug_l,
                    }
                )
            if href:
                detail_with_href += 1
                if href not in detail_urls_seen:
                    detail_urls_seen.append(href)
            key = _profile_href_key(href) if "/square/" in href else href
            hl = (href or "").lower()
            replay_only_href = "/square/audio/replay" in hl and "/square/post/" not in hl
            if (
                href
                and key
                and key not in seen
                and not _square_noise_url(href)
                and not replay_only_href
            ):
                seen.add(key)
                out.append(
                    {
                        "href": href,
                        "clicked_page_url": page_url or href,
                        "title": (detail.get("title") or "视频帖").strip(),
                        "author": slug_l,
                        "author_slug": slug_l,
                        "time": (detail.get("time_label") or "").strip(),
                        "raw": (detail.get("raw") or "").strip(),
                        "image_urls": detail.get("image_urls") or [],
                        "video_url": (detail.get("video_url") or "").strip(),
                        "m3u8_urls": detail.get("m3u8_urls") or [],
                        "m3u8_url": (detail.get("m3u8_url") or "").strip(),
                        "audio_m3u8_url": m3u8_one,
                        "square_audio_replay_url": (
                            page_url.split("#")[0] if replay_page else ""
                        ),
                        "published_iso": (detail.get("published_iso") or "").strip(),
                        "time_label": (detail.get("time_label") or "").strip(),
                        "is_pinned": False,
                    }
                )
                m3u8_url = (detail.get("m3u8_url") or "").strip()
                if m3u8_url:
                    _scrape_log(f"视频流 m3u8: {m3u8_url}")
            cur = (driver.current_url or "").split("#")[0]
            if switched_new_tab:
                if KEEP_VIDEO_DETAIL_TAB:
                    if VIDEO_DETAIL_TAB_VISIBLE_SEC > 0:
                        time.sleep(min(VIDEO_DETAIL_TAB_VISIBLE_SEC, 8.0))
                    _scrape_log("保留视频详情新标签页（KEEP_VIDEO_DETAIL_TAB=true）")
                else:
                    try:
                        driver.close()
                    except Exception:
                        pass
                try:
                    if before_handles:
                        driver.switch_to.window(before_handles[0])
                except Exception:
                    pass
                if (not KEEP_VIDEO_DETAIL_TAB) and VIDEO_DETAIL_TAB_VISIBLE_SEC > 0:
                    time.sleep(min(VIDEO_DETAIL_TAB_VISIBLE_SEC, 8.0))
                cur = (driver.current_url or "").split("#")[0]
            if base and cur and cur != base:
                try:
                    driver.back()
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    _human_pause(0.7, 1.5)
                except Exception:
                    driver.get(base)
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    _human_pause_after_nav(1.1, 2.1)
            else:
                try:
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ESCAPE)
                    _human_pause(0.2, 0.5)
                except Exception:
                    pass
        except Exception:
            continue
    summary = (
        f"视频回扫统计：aspect-video={aspect_video_count}，其中点击 {clicked_from_aspect} 次；"
        f"总点击成功 {click_opened} 次，拿到详情链接 {detail_with_href} 次，新增 {len(out)} 条"
    )
    _scrape_log(summary)
    if detail_urls_seen:
        joined = " | ".join(detail_urls_seen)
        if len(joined) <= 2400:
            _scrape_log(f"视频回扫详情链接（共 {len(detail_urls_seen)} 条）：{joined}")
        else:
            _scrape_log(f"视频回扫详情链接（共 {len(detail_urls_seen)} 条，分行）：")
            for i, u in enumerate(detail_urls_seen, start=1):
                _scrape_log(f"  [{i}] {u}")
    elif detail_with_href:
        _scrape_log("视频回扫详情链接：未收集到 URL 列表（与统计不一致，可忽略）")
    else:
        _scrape_log("视频回扫详情链接：（无）")
    return out, audio_replay_patches


def _collect_following_profile_links(driver, max_profiles: int = 60) -> List[Dict[str, str]]:
    """在 Following 页主内容区收集「当前账号关注」的 profile 链接，排除侧栏/导航。"""
    _scroll_page_load_lists(driver, scrolls=14)
    profiles = driver.execute_script(
        """
const maxProfiles = arguments[0];
const out = [];
const seen = new Set();

function isInChrome(el) {
  let n = el;
  for (let i = 0; i < 12 && n; i++) {
    const role = n.getAttribute && n.getAttribute('role');
    const tag = (n.tagName || '').toLowerCase();
    const cls = String(n.className || '');
    if (role === 'navigation' || role === 'banner' || role === 'contentinfo') return true;
    if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
    if (/sidebar|side-bar|leftnav|rightnav|global-nav/i.test(cls)) return true;
    n = n.parentElement;
  }
  return false;
}

let anchors = Array.from(
  document.querySelectorAll('main a[href*="/square/profile/"], [role="main"] a[href*="/square/profile/"]')
);
if (anchors.length < 2) {
  anchors = Array.from(document.querySelectorAll('a[href*="/square/profile/"]')).filter(
    (a) => !isInChrome(a)
  );
}

for (const a of anchors) {
  const href = (a.href || '').split('#')[0];
  if (!href || seen.has(href)) continue;
  const name = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
  const parts = href.split('/').filter(Boolean);
  const slug = (parts[parts.length - 1] || '').split('?')[0] || '';
  const displayName = name || slug;
  out.push({ name: displayName, slug, href });
  seen.add(href);
  if (out.length >= maxProfiles) break;
}
return out;
        """,
        max_profiles,
    )
    return profiles or []


def _remove_square_live_toast(driver) -> None:
    """移除本脚本注入的直播提示条（下一轮巡检未在直播时调用）。"""
    try:
        driver.execute_script(
            """
const n = document.getElementById(arguments[0]);
if (n) n.remove();
            """,
            SQUARE_LIVE_TOAST_ID,
        )
    except Exception:
        pass


def _show_square_live_toast(
    driver,
    *,
    author: str,
    live_url: str,
    view_all_url: str,
) -> None:
    """
    在当前 Square 页注入右上角提示条：可关闭；「查看直播」「查看全部」新开标签。
    """
    try:
        ja = json.dumps(author, ensure_ascii=False)
        jl = json.dumps(live_url, ensure_ascii=False)
        jv = json.dumps(view_all_url, ensure_ascii=False)
        jid = json.dumps(SQUARE_LIVE_TOAST_ID)
        driver.execute_script(
            f"""
(function() {{
  const rid = {jid};
  const old = document.getElementById(rid);
  if (old) old.remove();
  const author = {ja};
  const liveUrl = {jl};
  const viewAllUrl = {jv};
  const root = document.createElement('div');
  root.id = rid;
  root.setAttribute('data-auto-deal-live-toast', '1');
  root.style.cssText = [
    'position:fixed','top:20px','right:20px','max-width:min(420px,92vw)','z-index:2147483647',
    'font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif',
    'background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%)','color:#f8fafc',
    'border:1px solid rgba(148,163,184,0.35)','border-radius:12px',
    'box-shadow:0 12px 40px rgba(0,0,0,.45)','padding:14px 16px','font-size:14px',
    'line-height:1.45','pointer-events:auto'
  ].join(';');
  const title = document.createElement('div');
  title.style.cssText = 'font-weight:600;margin-bottom:8px;font-size:15px';
  title.textContent = '直播中 · ' + author;
  const sub = document.createElement('div');
  sub.style.cssText = 'opacity:0.88;font-size:13px;margin-bottom:12px';
  sub.textContent = '主页或直播页检测到 LIVE 徽章或直播信号';
  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;align-items:center';
  const btnBase = 'cursor:pointer;border-radius:8px;padding:6px 12px;font-size:13px;font-weight:500';
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.textContent = '关闭';
  closeBtn.style.cssText = btnBase + ';border:1px solid rgba(148,163,184,0.45);background:transparent;color:#e2e8f0';
  closeBtn.addEventListener('click', function() {{ root.remove(); }});
  const openBtn = document.createElement('button');
  openBtn.type = 'button';
  openBtn.textContent = '查看直播';
  openBtn.style.cssText = btnBase + ';border:none;background:#22c55e;color:#052e16;font-weight:600';
  openBtn.addEventListener('click', function() {{
    try {{ window.open(liveUrl, '_blank', 'noopener,noreferrer'); }} catch (e) {{}}
  }});
  const allBtn = document.createElement('button');
  allBtn.type = 'button';
  allBtn.textContent = '查看全部';
  allBtn.style.cssText = closeBtn.style.cssText;
  allBtn.addEventListener('click', function() {{
    try {{ window.open(viewAllUrl, '_blank', 'noopener,noreferrer'); }} catch (e) {{}}
  }});
  btnRow.appendChild(closeBtn);
  btnRow.appendChild(openBtn);
  btnRow.appendChild(allBtn);
  root.appendChild(title);
  root.appendChild(sub);
  root.appendChild(btnRow);
  document.body.appendChild(root);
}})();
            """
        )
    except Exception:
        pass


def _detect_live_on_current_square_page(driver) -> Dict[str, Any]:
    """
    检查当前 Square 页面是否存在直播信号，并提取直播链接。
    含主页常见 LIVE 角标：span.live-tag（如 <span class="live-tag">LIVE</span>）。
    """
    return driver.execute_script(
        """
const raw = (document.body && document.body.innerText) || '';
const hitCn = raw.includes('正在直播') || raw.includes('直播中');
const hitEn =
  /\\b(live\\s*now|is\\s+live|live\\s*stream|live\\s*broadcast|going\\s*live)\\b/i.test(raw);
const hitText = hitCn || hitEn;

let liveTagHit = false;
for (const el of Array.from(document.querySelectorAll('span.live-tag, .live-tag'))) {
  const t = String((el && (el.innerText || el.textContent)) || '')
    .replace(/\\s+/g, ' ')
    .trim()
    .toUpperCase();
  if (t === 'LIVE' || (t && t.includes('LIVE'))) {
    liveTagHit = true;
    break;
  }
}

const bad = (href) => {
  const h = (href || '').toLowerCase();
  if (h.includes('/square/hashtag/')) return true;
  if (h.includes('fear-and-greed')) return true;
  if (h.includes('/square/post/')) return true;
  return false;
};

const links = [];
const seen = new Set();
for (const a of Array.from(document.querySelectorAll('a[href]'))) {
  const href = (a.href || '').split('#')[0];
  const t = (a.innerText || a.textContent || '') || '';
  if (!href || bad(href)) continue;
  const hl = href.toLowerCase();
  if (
    hl.includes('/live') ||
    hl.includes('tab=live') ||
    hl.includes('/broadcast') ||
    /直播/.test(t) ||
    /\\b(live\\s*now|is\\s+live|live\\s*stream)\\b/i.test(t)
  ) {
    if (!seen.has(href)) {
      links.push(href);
      seen.add(href);
    }
  }
}
const isLive = hitText || links.length > 0 || liveTagHit;
return { is_live: isLive, live_links: links.slice(0, 8), live_tag_hit: liveTagHit };
        """
    )


def _probe_single_profile_live(
    driver,
    profile_href: str,
    *,
    author_hint: str = "",
    log_visit: bool = True,
    view_all_url: str = DEFAULT_WATCHLIST_URL,
) -> Optional[Dict[str, str]]:
    """打开 profile 的直播 tab（必要时回主页）检测一次；命中则返回 lives 条目。"""
    href = (profile_href or "").strip().split("#")[0].strip()
    if not href:
        return None
    name = _visible_text(author_hint or "")
    slug = (_profile_slug(href) or "").strip()
    vu = (view_all_url or DEFAULT_WATCHLIST_URL).strip() or DEFAULT_WATCHLIST_URL
    if log_visit:
        _scrape_log(f"巡检是否在直播 → {name or slug} ({href})")
    try:
        sep = "&" if ("?" in href) else "?"
        driver.get(f"{href}{sep}tab=live")
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        _human_pause_after_nav(1.15, 2.55)
        status = _detect_live_on_current_square_page(driver)
        if not status.get("is_live"):
            driver.get(href)
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause_after_nav(0.9, 2.15)
            status = _detect_live_on_current_square_page(driver)
        if status.get("is_live"):
            links = status.get("live_links") or []
            live_url = _pick_live_url(href, links)
            author_disp = name or slug or href.rsplit("/", 1)[-1].split("?")[0]
            _show_square_live_toast(
                driver,
                author=author_disp,
                live_url=live_url,
                view_all_url=vu,
            )
            return {
                "author": author_disp,
                "profile": href.split("#")[0],
                "live_url": live_url,
                "raw": "profile_live_probe",
            }
        _remove_square_live_toast(driver)
    except Exception:
        _remove_square_live_toast(driver)
    return None


def _probe_live_from_profiles(
    driver,
    profiles: List[Dict[str, str]],
    max_lives: int = 20,
    skip_hrefs: Optional[Set[str]] = None,
    *,
    view_all_url: str = DEFAULT_WATCHLIST_URL,
) -> List[Dict[str, str]]:
    """
    进入关注用户个人页逐个探测是否在直播，返回直播中的用户和链接。
    skip_hrefs：已在「主页拉帖」同次访问内检测过的 profile，避免重复打开。
    """
    lives: List[Dict[str, str]] = []
    skip = skip_hrefs or set()
    for p in profiles:
        if len(lives) >= max_lives:
            break
        href = (p.get("href") or "").strip()
        if not href:
            continue
        key = _profile_href_key(href)
        if key and key in skip:
            continue
        name = _visible_text(p.get("name") or "")
        hit = _probe_single_profile_live(
            driver,
            href,
            author_hint=name,
            log_visit=True,
            view_all_url=view_all_url,
        )
        if hit:
            lives.append(hit)
    return lives


def fetch_rankings_from_binance_api(
    max_items: int,
    *,
    timeout: float = 45,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    官方现货 24h ticker（无需 API Key）。
    热榜：按 quoteVolume；涨幅/跌幅：按 priceChangePercent。
    仅保留常见 USDT 现货对（排除部分杠杆代币可按需再过滤）。
    """
    if requests is None:
        raise RuntimeError("缺少依赖 requests：无法使用 API 回退（热榜/涨幅/跌幅）。")

    trust_env = os.getenv("BINANCE_API_TRUST_ENV", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    max_retries = max(1, int(os.getenv("BINANCE_API_RETRIES", "3") or "3"))
    retry_delay = float(os.getenv("BINANCE_API_RETRY_DELAY_SEC", "2") or "2")

    session = requests.Session()
    session.trust_env = trust_env

    last_err: BaseException | None = None
    tickers: List[Dict[str, Any]] | None = None
    used_url = ""

    for url in BINANCE_TICKER_24H_URLS:
        for attempt in range(max_retries):
            try:
                r = session.get(url, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, list) or not data:
                    raise ValueError(f"unexpected ticker payload from {url}")
                tickers = data
                used_url = url
                break
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    wait = retry_delay * (attempt + 1)
                    _scrape_log(
                        f"API {url} 失败 ({e!s})，{wait:.0f}s 后重试 "
                        f"({attempt + 1}/{max_retries})…"
                    )
                    time.sleep(wait)
        if tickers is not None:
            break

    if tickers is None:
        raise RuntimeError(
            f"Binance 24h ticker 全部节点失败（已试 {len(BINANCE_TICKER_24H_URLS)} 个 URL）: {last_err}"
        ) from last_err

    if used_url and used_url != BINANCE_TICKER_24H:
        _scrape_log(f"24h ticker 使用备用节点: {used_url}")

    usdt = [
        t
        for t in tickers
        if isinstance(t, dict)
        and str(t.get("symbol", "")).endswith("USDT")
        and "UPUSDT" not in str(t.get("symbol"))
        and "DOWNUSDT" not in str(t.get("symbol"))
    ]

    def row(t: Dict[str, Any]) -> Dict[str, Any]:
        sym = str(t.get("symbol", ""))
        last = str(t.get("lastPrice", ""))
        pct = str(t.get("priceChangePercent", ""))
        qv = str(t.get("quoteVolume", ""))
        return {
            "symbol": sym,
            "price": last,
            "change": f"{pct}%",
            "quoteVolume": qv,
            "raw": f"{sym} {last} {pct}%",
        }

    by_vol = sorted(
        usdt, key=lambda x: float(x.get("quoteVolume") or 0), reverse=True
    )[:max_items]
    by_up = sorted(
        usdt, key=lambda x: float(x.get("priceChangePercent") or 0), reverse=True
    )[:max_items]
    by_dn = sorted(usdt, key=lambda x: float(x.get("priceChangePercent") or 0))[:max_items]

    return {
        "hot_rank": [row(t) for t in by_vol],
        "gainers": [row(t) for t in by_up],
        "losers": [row(t) for t in by_dn],
    }


def _click_first_text(driver, texts: List[str], timeout_sec: int = 8) -> bool:
    for t in texts:
        xpath = (
            f"//*[self::button or self::a or @role='tab']"
            f"[contains(normalize-space(.), '{t}')]"
        )
        try:
            elem = WebDriverWait(driver, timeout_sec).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].click();", elem)
            _human_pause(1.15, 2.55)
            return True
        except Exception:
            continue
    return False


def _collect_section(
    driver,
    section_name: str,
    tab_text_candidates: List[str],
    max_items: int,
    api_fallback: Optional[List[Dict[str, Any]]] = None,
    *,
    api_fallback_key: Optional[str] = None,
    api_fallback_timeout: float = 10,
) -> Dict[str, object]:
    clicked = _click_first_text(driver, tab_text_candidates)
    _scroll_page_load_lists(driver)
    _human_pause(0.65, 1.45)
    try:
        WebDriverWait(driver, 18).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "tbody tr, [role='row'], table")
            )
        )
    except Exception:
        pass
    rows = _extract_rows_best_effort(driver, max_items=max_items)
    source = "dom"
    note = ""
    if len(rows) < 2:
        fb = api_fallback
        if not fb and api_fallback_key:
            try:
                _scrape_log(
                    f"{section_name} 页面行数不足，尝试 API 回退 ({api_fallback_key})…"
                )
                api = fetch_rankings_from_binance_api(
                    max_items, timeout=api_fallback_timeout
                )
                fb = api.get(api_fallback_key, [])
            except Exception as e:
                note = f"API 回退失败: {e}"
                _scrape_log(f"警告：{section_name} {note}")
        if fb:
            rows = fb[:max_items]
            source = "api_24h"
            if not note:
                note = (
                    "页面未解析到足够表格行（常见于虚拟列表/反爬/类名变更），"
                    "已改用官方 GET /api/v3/ticker/24hr 排序结果"
                )
    return {
        "section": section_name,
        "clicked_tab": clicked,
        "tab_text_candidates": tab_text_candidates,
        "extraction_source": source,
        "note": note,
        "count": len(rows),
        "items": rows,
    }


def _dedupe_audio_replay_patches(
    patches: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """同一 post_href + replay URL 只保留一条，供 watchlist 与 state 合并。"""
    seen: Set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for p in patches:
        if not isinstance(p, dict):
            continue
        ph = (p.get("post_href") or "").strip().split("#")[0]
        rh = (
            (p.get("square_audio_replay_url") or p.get("replay_href") or "")
            .strip()
            .split("#")[0]
        )
        key = (ph, rh)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def scrape_binance_lists(
    url: str,
    max_items: int = 120,
    watchlist_url: str = DEFAULT_WATCHLIST_URL,
    max_profiles_to_probe: int = 40,
    skip_profile_live_probe: bool = False,
    market_rank_top_n: int = DEFAULT_MARKET_RANK_TOP_N,
    include_hot_rank: bool = False,
    square_images_dir: Optional[str] = "square_post_images",
    skip_square_images: bool = False,
    posts_state_path_for_detail_cache: Optional[str] = None,
) -> Dict[str, object]:
    priority_order = _priority_slugs_ordered()
    priority_slugs: Set[str] = set(priority_order)
    has_priority = bool(priority_slugs)
    top_n = max(1, min(100, int(market_rank_top_n)))
    _scrape_log("开始抓取")
    if has_priority:
        _scrape_log(f"重点关注用户（共 {len(priority_order)} 个，顺序与源码一致）: {priority_order}")
    else:
        _scrape_log(
            "PRIORITY_FOLLOW_PROFILES 为空：文章/直播将按 Following 页收集到的全部主页处理"
        )
    # 仅在 include_hot_rank 时处理行情榜单（热榜/涨幅/跌幅）
    if include_hot_rank:
        _scrape_log("预取 Binance 24h ticker（作榜单 DOM 失败时的回退）…")
        try:
            api_rankings = fetch_rankings_from_binance_api(top_n, timeout=8)
            _scrape_log("24h ticker 回退数据已就绪")
        except Exception:
            api_rankings = {
                "hot_rank": [],
                "gainers": [],
                "losers": [],
            }
            _scrape_log("警告：24h ticker 预取失败，榜单将仅依赖页面 DOM")
    else:
        api_rankings = {
            "hot_rank": [],
            "gainers": [],
            "losers": [],
        }
        _scrape_log("未加 --include-hot-rank：已跳过热榜/涨幅榜/跌幅榜全部处理")
    _scrape_log("正在连接浏览器（远程调试 Chrome）…")
    driver = init_browser(use_remote_debugging=True)
    try:
        # 不再打开 Following 页面：只按 PRIORITY_FOLLOW_PROFILES 逐个主页处理
        _scrape_log("已按要求跳过 Following 页面，不打开关注列表")
        lives_feed: List[Dict[str, str]] = []
        posts: List[Dict[str, Any]] = []
        watchlist_audio_replay_patches: List[Dict[str, Any]] = []
        if has_priority:
            follow_profiles = _merge_priority_profiles([], priority_order)
            _scrape_log(f"将按重点关注主页逐个抓取（共 {len(follow_profiles)} 个）")
        else:
            follow_profiles = []
            _scrape_log("未配置重点关注用户：本轮不采集关注文章/直播（且不打开 Following）")

        lives_from_profile_merge: List[Dict[str, str]] = []
        profile_hrefs_live_done: Set[str] = set()
        if has_priority and follow_profiles:
            _scrape_log(
                "从各重点关注用户主页深度滚动合并帖子（补齐时间线中更多篇）…"
            )
            probe_live_with_posts = not skip_profile_live_probe
            for fp in follow_profiles:
                ph = (fp.get("href") or "").strip()
                slug = (fp.get("slug") or _profile_slug(ph)).lower()
                if not ph or not slug:
                    continue
                extra, live_one, prof_audio_patches = _extract_square_profile_posts(
                    driver,
                    ph,
                    slug,
                    max_items=max_items,
                    probe_live=probe_live_with_posts,
                    author_display_name=(fp.get("name") or "").strip(),
                    view_all_url=watchlist_url,
                )
                if prof_audio_patches:
                    watchlist_audio_replay_patches.extend(prof_audio_patches)
                if probe_live_with_posts:
                    k = _profile_href_key(ph)
                    if k:
                        profile_hrefs_live_done.add(k)
                if live_one:
                    lives_from_profile_merge.append(live_one)
                if extra:
                    posts = _merge_posts_by_href(posts, extra)
                _human_pause(0.45, 1.05)
            _scrape_log(f"合并主页帖子后共 {len(posts)} 条")

        ref_now = datetime.now(timezone.utc)
        # 视频帖经常拿不到 create-time；若完全缺时间字段，给一个兜底时间避免被 24h 过滤误杀。
        video_time_fallback = 0
        for p in posts:
            if not isinstance(p, dict):
                continue
            has_video = bool(str(p.get("video_url") or "").strip()) or "/square/video/" in str(
                p.get("href") or ""
            ).lower()
            if not has_video:
                continue
            has_any_time = bool(
                str(p.get("published_iso") or "").strip()
                or str(p.get("time_label") or "").strip()
                or str(p.get("time") or "").strip()
                or str(p.get("published_at") or "").strip()
            )
            if has_any_time:
                continue
            p["published_iso"] = ref_now.isoformat()
            p["time_label"] = "刚刚"
            video_time_fallback += 1
        if video_time_fallback:
            _scrape_log(f"视频帖时间兜底已应用 {video_time_fallback} 条")
        for p in posts:
            if isinstance(p, dict):
                enrich_post_published_fields(p, ref_now)
        before_f = len(posts)
        posts = filter_posts_by_published_age(posts, POST_RETENTION_HOURS, ref_now)
        _scrape_log(
            f"按发帖时间在近 {POST_RETENTION_HOURS} 小时内过滤："
            f"{before_f} → {len(posts)} 条（无法解析时间或超期/久远置顶已丢弃）"
        )

        if not skip_square_images and posts and square_images_dir:
            _enrich_post_images_from_detail_pages(
                driver,
                posts,
                max_pages=max_items,
                posts_state_path=posts_state_path_for_detail_cache,
            )
            _scrape_log("下载帖子配图到本地…")
            _download_square_post_images(driver, posts, square_images_dir)

        # 关注列表里「谁在直播」：逐个 profile 打开检测
        if skip_profile_live_probe:
            _scrape_log("已跳过直播巡检（--skip-profile-live-probe）")
            lives_probed = []
        else:
            _scrape_log(
                f"开始逐个 profile 巡检是否在直播（共 {len(follow_profiles)} 个）…"
            )
            lives_probed = _probe_live_from_profiles(
                driver,
                follow_profiles,
                max_lives=max_items,
                skip_hrefs=profile_hrefs_live_done,
                view_all_url=watchlist_url,
            )
            _scrape_log(f"直播巡检结束（命中 {len(lives_probed)} 条）")
        # 合并：主页拉帖时顺带命中的直播 + 其余 profile 巡检 + Feed（按 live_url 去重）
        lives = []
        seen_live_urls: Set[str] = set()
        for x in lives_from_profile_merge + lives_probed:
            lu = (x.get("live_url") or x.get("href") or "").strip()
            if lu and lu in seen_live_urls:
                continue
            if lu:
                seen_live_urls.add(lu)
            lives.append(x)
        seen_hrefs = set(seen_live_urls)
        for it in lives_feed:
            h = (it.get("href") or "").strip()
            if h and h not in seen_hrefs:
                lives.append(it)
                seen_hrefs.add(h)

        wl_note = ""
        if not (lives or posts or follow_profiles):
            wl_note = "未解析到关注/文章：请确认已登录，且页面已加载完成或页面结构已变更。"
        elif has_priority and not (lives or posts):
            wl_note = (
                "已配置重点关注用户，但本次未解析到其直播或文章（可能未关注、"
                "Feed 中暂无其帖子或 DOM 结构变更）。"
            )
        watchlist: Dict[str, object] = {
            "section": "watchlist_following",
            "page_url": watchlist_url,
            "priority_follow_slugs": list(priority_order),
            "extraction_source": "dom_square"
            if (lives or posts or follow_profiles)
            else "empty",
            "note": wl_note,
            "count_follow_profiles": len(follow_profiles),
            "count_lives": len(lives),
            "count_latest_posts": len(posts),
            "follow_profiles_sample": follow_profiles[:15],
            "lives": lives,
            "latest_posts": posts,
            "audio_replay_patches": _dedupe_audio_replay_patches(
                watchlist_audio_replay_patches
            ),
        }

        data: Dict[str, object] = {
            "overview_url": url,
            "scraped_at": beijing_time_str(),
            "watchlist": watchlist,
        }
        if include_hot_rank:
            # 热榜 / 涨幅 / 跌幅：overview 上尝试 DOM，失败则用 24h API
            _scrape_log(f"打开行情总览页（榜单）: {url}")
            with cdp_worker_tab(driver, url, page_load_timeout=25, log_prefix="markets"):
                WebDriverWait(driver, 25).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                _human_pause_after_nav(1.7, 3.5)

                _scrape_log(f"处理涨幅榜（取前 {top_n}）…")
                sec_gainers = _collect_section(
                    driver,
                    "gainers",
                    ["涨幅榜", "涨幅", "Gainers", "Top Gainers", "涨跌幅"],
                    top_n,
                    api_fallback=api_rankings["gainers"],
                )
                _scrape_log(
                    f"涨幅榜完成（{sec_gainers.get('count', 0)} 条，来源 {sec_gainers.get('extraction_source', '')}）"
                )

                _scrape_log(f"处理跌幅榜（取前 {top_n}）…")
                sec_losers = _collect_section(
                    driver,
                    "losers",
                    ["跌幅榜", "跌幅", "Losers", "Top Losers"],
                    top_n,
                    api_fallback=api_rankings["losers"],
                )
                _scrape_log(
                    f"跌幅榜完成（{sec_losers.get('count', 0)} 条，来源 {sec_losers.get('extraction_source', '')}）"
                )
                data["gainers"] = sec_gainers
                data["losers"] = sec_losers

                _scrape_log(f"处理全局热榜（取前 {top_n}）…")
                data["hot_rank"] = _collect_section(
                    driver,
                    "hot_rank",
                    ["热榜", "热门", "Hot", "Trending", "成交额"],
                    top_n,
                    api_fallback=api_rankings["hot_rank"],
                )
                hr = data["hot_rank"]
                _scrape_log(
                    f"热榜完成（{hr.get('count', 0)} 条，来源 {hr.get('extraction_source', '')}）"
                )
        else:
            _scrape_log("已跳过热榜/涨幅榜/跌幅榜（未加 --include-hot-rank）")

        # 只清洗榜单 items 的 raw 字段（watchlist 结构不同）
        for key in ("hot_rank", "gainers", "losers"):
            sec = data.get(key)
            if not isinstance(sec, dict):
                continue
            for item in sec.get("items", []) or []:
                if isinstance(item, dict) and "raw" in item:
                    item["raw"] = _visible_text(str(item.get("raw", "")))
        _scrape_log("全部步骤完成，关闭浏览器")
        return data
    finally:
        driver.quit()


def _print_items_table(
    label: str,
    items: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    max_rows: int = MAX_STDOUT_ROWS,
) -> None:
    """将列表字典打印为表格；风格对齐 getinfo/run_calendar（to_string + 截断提示）。"""
    if label:
        print(f"\n【{label}】")
    if not items:
        print("(无)")
        return
    limit = max_rows if max_rows > 0 else None

    if pd is None:
        keys = columns or list(items[0].keys())
        rows_out = items if limit is None else items[:limit]
        for i, row in enumerate(rows_out, 1):
            if isinstance(row, dict):
                parts = [f"{k}={row.get(k, '')}" for k in keys if k in row]
                print(f"  {i}  " + "  ".join(parts))
            else:
                print(f"  {i}  {row}")
        total = len(items)
        if limit is not None and total > limit:
            print(f"\n... 共 {total} 条，仅显示前 {limit} 条。")
        elif total:
            print(f"\n共 {total} 条。")
        return

    df = pd.DataFrame(items)
    if columns:
        use = [c for c in columns if c in df.columns]
        if use:
            df = df[use]
    n = len(df)
    if limit is not None and n > limit:
        print(df.head(limit).to_string())
        print(f"\n... 共 {n} 条，仅显示前 {limit} 条。")
    else:
        print(df.to_string())
        if n:
            print(f"\n共 {n} 条。")


def scrape_liquidity_gainers_snapshot(
    *,
    liquidity_top: int = 30,
    gainers_top: int = 20,
    url: str = DEFAULT_URL,
    use_cdp: bool = True,
) -> Dict[str, object]:
    """
    一次抓取：24h 流动性（USDT 成交额）前 N + 涨幅榜前 M。

    - liquidity：按 quoteVolume 排序（与页面「热榜/成交额」一致）
    - gainers：按 priceChangePercent 排序
  - use_cdp=False 时仅用官方 GET /api/v3/ticker/24hr
    """
    liq_n = max(0, min(100, int(liquidity_top)))
    gain_n = max(0, min(100, int(gainers_top)))
    if liq_n <= 0 and gain_n <= 0:
        raise ValueError("liquidity_top 与 gainers_top 至少一个大于 0")

    api_max = max(liq_n, gain_n, 1)

    if not use_cdp:
        api = fetch_rankings_from_binance_api(api_max)
        api_liq = api["hot_rank"][:liq_n] if liq_n else []
        api_gain = api["gainers"][:gain_n] if gain_n else []

        def _api_section(name: str, items: List[Dict[str, Any]]) -> Dict[str, object]:
            return {
                "section": name,
                "extraction_source": "api_24h",
                "count": len(items),
                "items": items,
            }

        out: Dict[str, object] = {
            "overview_url": url,
            "scraped_at": beijing_time_str(),
        }
        if liq_n:
            out["liquidity"] = _api_section("liquidity", api_liq)
        if gain_n:
            out["gainers"] = _api_section("gainers", api_gain)
        return out

    _scrape_log(
        f"行情榜单：流动性 TOP{liq_n or '-'} + 涨幅 TOP{gain_n or '-'}，连接 CDP Chrome…"
    )
    driver = init_browser(use_remote_debugging=True)
    try:
        _scrape_log(f"打开行情页: {url}")
        with cdp_worker_tab(driver, url, page_load_timeout=25, log_prefix="markets"):
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause_after_nav(1.7, 3.5)

            out = {
                "overview_url": url,
                "scraped_at": beijing_time_str(),
            }
            if liq_n:
                _scrape_log(f"处理流动性/成交额榜（取前 {liq_n}）…")
                sec_liq = _collect_section(
                    driver,
                    "liquidity",
                    ["热榜", "热门", "Hot", "Trending", "成交额", "流动性", "24h成交额"],
                    liq_n,
                    api_fallback_key="hot_rank",
                )
                for item in sec_liq.get("items", []) or []:
                    if isinstance(item, dict) and "raw" in item:
                        item["raw"] = _visible_text(str(item.get("raw", "")))
                out["liquidity"] = sec_liq
                _scrape_log(
                    f"流动性榜完成（{sec_liq.get('count', 0)} 条，"
                    f"来源 {sec_liq.get('extraction_source', '')}）"
                )

            if gain_n:
                _scrape_log(f"处理涨幅榜（取前 {gain_n}）…")
                sec_gain = _collect_section(
                    driver,
                    "gainers",
                    ["涨幅榜", "涨幅", "Gainers", "Top Gainers", "涨跌幅"],
                    gain_n,
                    api_fallback_key="gainers",
                )
                for item in sec_gain.get("items", []) or []:
                    if isinstance(item, dict) and "raw" in item:
                        item["raw"] = _visible_text(str(item.get("raw", "")))
                out["gainers"] = sec_gain
                _scrape_log(
                    f"涨幅榜完成（{sec_gain.get('count', 0)} 条，"
                    f"来源 {sec_gain.get('extraction_source', '')}）"
                )
            return out
    finally:
        driver.quit()


def scrape_gainers_top_n(
    top_n: int = 20,
    url: str = DEFAULT_URL,
    *,
    use_cdp: bool = True,
) -> Dict[str, object]:
    """兼容：仅抓涨幅榜（见 scrape_liquidity_gainers_snapshot）。"""
    snap = scrape_liquidity_gainers_snapshot(
        liquidity_top=0,
        gainers_top=top_n,
        url=url,
        use_cdp=use_cdp,
    )
    return {
        "overview_url": snap.get("overview_url"),
        "scraped_at": snap.get("scraped_at"),
        "gainers": snap.get("gainers"),
    }


def _format_quote_volume_short(raw: str) -> str:
    try:
        v = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return (raw or "").strip()
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.2f}K"
    return f"{v:.0f}"


def _format_rank_section_lines(
    items: List[Any],
    *,
    top_n: int,
    show_volume: bool = False,
) -> List[str]:
    lines: List[str] = []
    for i, row in enumerate(items[:top_n], 1):
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("name") or "").strip()
        base = sym.replace("USDT", "") if sym else "?"
        ch = str(row.get("change") or "").strip()
        price = str(row.get("price") or "").strip()
        qv = _format_quote_volume_short(str(row.get("quoteVolume") or ""))
        if show_volume and qv:
            tail = f"  ·  24h额 {qv} USDT"
            if ch:
                tail += f"  ·  {ch}"
            lines.append(f"{i}. {base}{tail}")
        elif price and ch:
            lines.append(f"{i}. {base}  {ch}  ·  {price}")
        elif ch:
            lines.append(f"{i}. {base}  {ch}")
        else:
            lines.append(f"{i}. {str(row.get('raw') or sym).strip()}")
    return lines


def format_liquidity_gainers_square_brief(
    payload: Dict[str, object],
    *,
    liquidity_top: int = 30,
    gainers_top: int = 20,
) -> str:
    """流动性 TOP + 涨幅 TOP 合并为广场短文。"""
    scraped = str(payload.get("scraped_at") or "").strip()
    lines: List[str] = ["📊 币安现货榜单速览"]
    if scraped:
        lines.append(f"更新：{scraped}")
    lines.append("")

    liq_sec = payload.get("liquidity")
    if isinstance(liq_sec, dict) and liquidity_top > 0:
        liq_items = liq_sec.get("items") or []
        n = max(1, min(int(liquidity_top), len(liq_items) or int(liquidity_top)))
        src = str(liq_sec.get("extraction_source") or "unknown")
        lines.append(f"💧 24h 流动性 TOP{n}（USDT 成交额）")
        lines.extend(
            _format_rank_section_lines(liq_items, top_n=n, show_volume=True)
        )
        lines.append("")
        lines.append(f"（流动性来源: {src}）")
        lines.append("")

    gain_sec = payload.get("gainers")
    if isinstance(gain_sec, dict) and gainers_top > 0:
        gain_items = gain_sec.get("items") or []
        n = max(1, min(int(gainers_top), len(gain_items) or int(gainers_top)))
        src = str(gain_sec.get("extraction_source") or "unknown")
        lines.append(f"📈 涨幅榜 TOP{n}")
        lines.extend(_format_rank_section_lines(gain_items, top_n=n, show_volume=False))
        lines.append("")
        lines.append(f"（涨幅来源: {src}）")

    lines.append("")
    lines.append("#Binance #流动性 #涨幅榜")
    return "\n".join(lines).strip()


def format_gainers_square_brief(
    gainers_payload: Dict[str, object],
    *,
    top_n: int = 20,
    title: str | None = None,
) -> str:
    """将 scrape_gainers_top_n 结果格式化为广场短文（仅涨幅段）。"""
    if gainers_payload.get("liquidity"):
        return format_liquidity_gainers_square_brief(
            gainers_payload, liquidity_top=0, gainers_top=top_n
        )
    sec = gainers_payload.get("gainers")
    if not isinstance(sec, dict):
        sec = {}
    items = sec.get("items") or []
    if not isinstance(items, list):
        items = []
    n = max(1, min(int(top_n), len(items) or int(top_n)))
    scraped = str(gainers_payload.get("scraped_at") or "").strip()
    src = str(sec.get("extraction_source") or "unknown").strip()
    head = title or f"📈 币安现货涨幅榜 TOP{n}"
    lines = [head]
    if scraped:
        lines.append(f"更新：{scraped}")
    lines.append("")
    lines.extend(_format_rank_section_lines(items, top_n=n, show_volume=False))
    lines.append("")
    lines.append(f"#涨幅榜 #Binance  （来源: {src}）")
    return "\n".join(lines).strip()


def print_liquidity_gainers_stdout(
    payload: Dict[str, object],
    *,
    liquidity_top: int = 30,
    gainers_top: int = 20,
) -> None:
    """终端打印流动性 + 涨幅两个榜单。"""
    print(f"[binance_ranks] scraped_at={payload.get('scraped_at', '')}")
    ranking_cols = ["symbol", "price", "change", "quoteVolume"]
    for title, key, n in (
        ("24h 流动性", "liquidity", liquidity_top),
        ("涨幅榜", "gainers", gainers_top),
    ):
        sec = payload.get(key)
        if not isinstance(sec, dict):
            continue
        items = sec.get("items") or []
        src = sec.get("extraction_source", "")
        note = (sec.get("note") or "").strip()
        print(f"\n【{title} TOP{n}】  extraction_source={src}")
        if note:
            print(f"  note: {note}")
        _print_items_table("", items, columns=ranking_cols, max_rows=n)


def print_result_to_stdout(result: Dict[str, Any], max_rows: int = MAX_STDOUT_ROWS) -> None:
    script_key = "binance_market_lists"
    wl = result.get("watchlist") or {}
    lives = wl.get("lives") or []
    posts = wl.get("latest_posts") or []
    profiles = wl.get("follow_profiles_sample") or []
    hot_sec = result.get("hot_rank")
    hot = (hot_sec or {}).get("items") or [] if hot_sec is not None else []
    gain = (result.get("gainers") or {}).get("items") or []
    lose = (result.get("losers") or {}).get("items") or []

    print(f"[{script_key}] 数据抓取完成，scraped_at={result.get('scraped_at', '')}")
    summary = (
        f"  关注直播={len(lives)}，最新动态={len(posts)}，"
        f"关注主页样本={len(profiles)}，"
    )
    if hot_sec is not None:
        summary += f"热榜={len(hot)}，"
    summary += f"涨幅={len(gain)}，跌幅={len(lose)}"
    print(summary)

    _print_items_table(
        "关注 · 谁在直播",
        lives,
        columns=["author", "profile", "live_url", "title", "href", "time"],
        max_rows=max_rows,
    )
    _print_items_table(
        "关注 · 最新动态",
        posts,
        columns=[
            "title",
            "author",
            "author_slug",
            "published_at",
            "is_pinned",
            "gemini_bias_zh",
            "time",
            "href",
        ],
        max_rows=max_rows,
    )
    if profiles:
        _print_items_table(
            "关注 · 主页样本（巡检用）",
            profiles,
            columns=["name", "href"],
            max_rows=max_rows,
        )

    ranking_cols = ["symbol", "price", "change", "quoteVolume"]
    sections = [("涨幅榜", "gainers"), ("跌幅榜", "losers")]
    if hot_sec is not None:
        sections.insert(0, ("热榜", "hot_rank"))
    for title, key in sections:
        sec = result.get(key) or {}
        items = sec.get("items") or []
        src = sec.get("extraction_source", "")
        note = (sec.get("note") or "").strip()
        print(f"\n【{title}】  extraction_source={src}")
        if note:
            print(f"  note: {note}")
        _print_items_table("", items, columns=ranking_cols, max_rows=max_rows)


def main():
    parser = argparse.ArgumentParser(
        description="抓取币安关注（Square Following）、涨幅/跌幅榜；可选全局热榜（Selenium）"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="行情总览页 URL（热榜/涨跌尝试）")
    parser.add_argument(
        "--watchlist-url",
        default=DEFAULT_WATCHLIST_URL,
        help="Square Following URL（默认 .../square?tab=Following）",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=120,
        help="Square 帖子条数上限（Following + 各主页时间线；默认 120）；涨跌榜见 --market-top",
    )
    parser.add_argument(
        "--market-top",
        type=int,
        default=DEFAULT_MARKET_RANK_TOP_N,
        help=f"启用 --include-hot-rank 时，热榜/涨幅榜/跌幅榜各取前 N（默认 {DEFAULT_MARKET_RANK_TOP_N}）",
    )
    parser.add_argument(
        "--include-hot-rank",
        action="store_true",
        help="启用行情榜单抓取（热榜+涨幅榜+跌幅榜）；默认不处理任何行情榜单",
    )
    parser.add_argument(
        "--out",
        default="binance_market_lists.json",
        help="输出 JSON 文件路径（默认: binance_market_lists.json）",
    )
    parser.add_argument(
        "--max-profiles",
        type=int,
        default=40,
        help="在 Following 页最多收集多少个关注主页用于「是否直播中」巡检（默认 40）",
    )
    parser.add_argument(
        "--skip-profile-live-probe",
        action="store_true",
        help="不逐个打开关注主页检测直播（更快，但 lives 可能为空）",
    )
    parser.add_argument(
        "--max-print-rows",
        type=int,
        default=MAX_STDOUT_ROWS,
        help=f"标准输出每个区块最多显示行数（0 表示全部，默认 {MAX_STDOUT_ROWS}）",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="在表格之后仍将完整 JSON 打印到标准输出（默认仅写文件，终端为可读表格）",
    )
    parser.add_argument(
        "--skip-posts-state",
        action="store_true",
        help="不合并 binance_posts_state（帖子保留窗口见 POST_RETENTION_HOURS）与 Gemini（写入的 JSON 仅为本次抓取快照）",
    )
    parser.add_argument(
        "--posts-state",
        default=None,
        help="帖子状态文件路径（默认与 --out 同目录的 binance_posts_state.json）",
    )
    parser.add_argument(
        "--skip-posts-gemini",
        action="store_true",
        help="仍合并 12h 状态但不对新帖调用 Gemini",
    )
    parser.add_argument(
        "--square-images-dir",
        default="square_post_images",
        help="帖子卡片内图片保存目录（默认 square_post_images）",
    )
    parser.add_argument(
        "--skip-square-images",
        action="store_true",
        help="不下载帖子中的图片",
    )
    args = parser.parse_args()

    out_path = os.path.abspath(args.out)
    posts_state_for_cache: Optional[str] = None
    if not args.skip_posts_state:
        posts_state_for_cache = args.posts_state or default_posts_state_path(out_path)
    result = scrape_binance_lists(
        url=args.url,
        max_items=max(5, args.max_items),
        watchlist_url=args.watchlist_url,
        max_profiles_to_probe=max(5, args.max_profiles),
        skip_profile_live_probe=args.skip_profile_live_probe,
        market_rank_top_n=max(1, args.market_top),
        include_hot_rank=args.include_hot_rank,
        square_images_dir=None if args.skip_square_images else args.square_images_dir,
        skip_square_images=args.skip_square_images,
        posts_state_path_for_detail_cache=posts_state_for_cache,
    )
    if not args.skip_posts_state:
        process_watchlist_posts(
            result,
            out_path,
            state_path=args.posts_state,
            skip_gemini=args.skip_posts_gemini,
        )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print_result_to_stdout(result, max_rows=args.max_print_rows)
    if args.print_json:
        print("\n" + "=" * 60 + "\n完整 JSON（--print-json）\n" + "=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] 已写入: {out_path}")


if __name__ == "__main__":
    main()
