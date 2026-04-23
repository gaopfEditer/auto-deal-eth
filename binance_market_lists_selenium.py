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
  python3 binance_market_lists_selenium.py
  python3 binance_market_lists_selenium.py --out ./screenshots/binance_lists.json
  python3 binance_market_lists_selenium.py --url "https://www.binance.com/zh-CN/markets/overview"

说明：
  - 关注列表请使用币安 Square Following 页面（默认 .../square?tab=Following），需已登录。
  - 重点关注用户在源码中 PRIORITY_FOLLOW_PROFILES 列表配置（完整 profile URL 或 slug）；
    仅对这些用户巡检「是否直播」与「是否发文章」；列表为空时仍巡检 Following 页收集到的全部主页。
  - 行情：默认只输出涨幅榜、跌幅榜各前 N（--market-top，默认 10）；全局热榜需加 --include-hot-rank。
  - 热榜/涨幅/跌幅若页面 DOM 抓不到，涨幅与跌幅会回退到官方 /api/v3/ticker/24hr（无需 Key）。
  - 关注流帖子默认合并 binance_posts_state.json：保留 24 小时内文章，新帖终端提示并用 Gemini 判多空；
    可用 --skip-posts-state 仅输出本次快照。
  - 重点关注用户会额外打开其主页并深度下滚，合并时间线帖子（条数见 --max-items）；帖子卡片内图片可保存到 --square-images-dir。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

try:
    import requests  # 用于热榜/涨跌幅 API 回退
except ModuleNotFoundError:  # 允许你只用 DOM 抓 Square Following
    requests = None

try:
    import pandas as pd  # 标准输出表格（与 getinfo/run_calendar 风格一致）
except ModuleNotFoundError:
    pd = None

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from browser_automation import init_browser

from binance_posts_state import (
    POST_RETENTION_HOURS,
    beijing_time_str,
    enrich_post_published_fields,
    filter_posts_by_published_age,
    process_watchlist_posts,
)


DEFAULT_URL = "https://www.binance.com/zh-CN/markets/overview"
DEFAULT_WATCHLIST_URL = "https://www.binance.com/zh-CN/square?tab=Following"
BINANCE_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"
# 行情页热榜 / 涨幅榜 / 跌幅榜默认只取前 N（与 Square 关注流的 --max-items 无关）
DEFAULT_MARKET_RANK_TOP_N = 10

# 重点关注用户：Square profile 完整 URL 或单独 slug（与下方顺序一致）；可随意增删。
# 为空列表时：直播/文章巡检范围仍为 Following 页收集到的全部主页。
PRIORITY_PROFILE_BASE = "https://www.binance.com/zh-CN/square/profile/"
PRIORITY_FOLLOW_PROFILES: List[str] = [
    f"{PRIORITY_PROFILE_BASE}yanchibit",
    # f"{PRIORITY_PROFILE_BASE}aleng888888",
    # f"{PRIORITY_PROFILE_BASE}carrywang55688",
    # f"{PRIORITY_PROFILE_BASE}square-creator-857dc547d",
    # f"{PRIORITY_PROFILE_BASE}sanmageshuai",
    # f"{PRIORITY_PROFILE_BASE}haoge666",
    # f"{PRIORITY_PROFILE_BASE}square-creator-4bd102843",
    
    # f"{PRIORITY_PROFILE_BASE}square-creator-f69ded460", 烦死
    # f"{PRIORITY_PROFILE_BASE}sanmageshuai",
]

# 标准输出每个区块最多行数（0 表示全部）；与 getinfo/run_calendar 的 MAX_ROWS 用法类似
MAX_STDOUT_ROWS = 180

# 进入帖子正文页补充配图时，最多打开的帖子数（避免耗时过长）
MAX_POST_DETAIL_ENRICH_PAGES = 15

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


def _scroll_feed_down_only(driver, scrolls: int) -> None:
    """只向下滚（不回到顶部），用于 profile 时间线加载更多帖子。"""
    for _ in range(scrolls):
        driver.execute_script(
            "window.scrollBy(0, Math.floor(window.innerHeight * 0.88));"
        )
        _human_jitter_scroll_pause()


def _scroll_profile_feed_until_stable(driver, max_rounds: int = 32) -> None:
    """
    主页时间线下滚：若任意 create-time 出现「n月n日」则至少已超约一天，停止继续下滚；
    否则直到帖子链接数不再增长。
    """
    last = -1
    stable = 0
    for _ in range(max_rounds):
        _scroll_feed_down_only(driver, scrolls=5)
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
                    'return document.querySelectorAll(\'a[href*="/square/post/"]\').length'
                )
                or 0
            )
        except Exception:
            n = 0
        if n == last:
            stable += 1
            if stable >= 4 and n > 0:
                break
        else:
            stable = 0
        last = n
        _human_pause(0.08, 0.32)


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
    return list(by_href.values())


def _post_id_from_href(href: str) -> str:
    m = re.search(r"/square/post/(\d+)", href or "", re.I)
    if m:
        return m.group(1)
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
        urls = [x for x in (p.get("image_urls") or []) if not _is_noise_image_url(str(x))]
        if not urls:
            continue
        href = (p.get("href") or "").strip()
        pid = _post_id_from_href(href)
        sub = os.path.join(root, pid)
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


def _enrich_post_images_from_detail_pages(
    driver,
    posts: List[Dict[str, Any]],
    max_pages: int = MAX_POST_DETAIL_ENRICH_PAGES,
) -> None:
    """进入 /square/post/ 正文页抓取正文区域配图（与列表卡片合并去重）。"""
    if not posts:
        return
    n = min(MAX_POST_DETAIL_ENRICH_PAGES, max_pages, len(posts))
    _scrape_log(f"打开帖子正文页补充配图（最多 {n} 篇）…")
    for p in posts[:n]:
        if not isinstance(p, dict):
            continue
        href = (p.get("href") or "").strip()
        if not href or "/square/post/" not in href.lower():
            continue
        try:
            driver.get(href)
            WebDriverWait(driver, 18).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause_after_nav(1.0, 2.6)
            _human_pause(0.12, 0.45)
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
    # 兜底多滚动一下，确保虚拟列表渲染
    _scroll_page_load_lists(driver, scrolls=28)

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

// 只从「帖子」链接抓文章；关注流里帖子一般为 /square/post/{id}
const anchors = Array.from(document.querySelectorAll('a[href*="/square/post/"]'));

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
  if (!text || text.length < 4) continue;

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
  const imageUrls = _bnCollectArticleImagesRelaxed(a);
  const videoUrl = _bnCollectVideoUrlFromCard(a);
  const item = {
    href,
    title,
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
) -> List[Dict[str, str]]:
    """
    打开用户 Square 主页，深度下滚加载虚拟列表，抓取该用户帖子（数量通常多于 Following 流首屏）。
    """
    base = (profile_href or "").split("#")[0].strip()
    if not base:
        return []
    _scrape_log(f"打开主页拉取帖子: {base}")
    driver.get(base)
    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    _human_pause_after_nav(1.5, 3.2)
    _scroll_profile_feed_until_stable(driver)
    _human_pause(0.35, 0.95)
    slug_l = (author_slug or "").lower().strip()
    return driver.execute_script(
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

const anchors = Array.from(document.querySelectorAll('a[href*="/square/post/"]'));
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
  if (!text || text.length < 4) continue;

  const clean = norm(text);
  const parts = clean.split(' ').filter(Boolean);
  const title = parts.slice(0, 20).join(' ');

  let author = authorSlug;
  const dotIdx = clean.indexOf('·');
  if (dotIdx > 0 && dotIdx < 80) author = clean.slice(0, dotIdx).trim() || authorSlug;

  const meta = _bnPostTimeFromCard(a);
  const imageUrls = _bnCollectArticleImagesRelaxed(a);
  const videoUrl = _bnCollectVideoUrlFromCard(a);
  out.push({
    href,
    title,
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
    ) or []


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


def _detect_live_on_current_square_page(driver) -> Dict[str, Any]:
    """
    检查当前 Square 页面是否存在直播信号，并提取直播链接。
    """
    return driver.execute_script(
        """
const raw = (document.body && document.body.innerText) || '';
const hitCn = raw.includes('正在直播') || raw.includes('直播中');
const hitEn =
  /\\b(live\\s*now|is\\s+live|live\\s*stream|live\\s*broadcast|going\\s*live)\\b/i.test(raw);
const hitText = hitCn || hitEn;

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
const isLive = hitText || links.length > 0;
return { is_live: isLive, live_links: links.slice(0, 8) };
        """
    )


def _probe_live_from_profiles(
    driver, profiles: List[Dict[str, str]], max_lives: int = 20
) -> List[Dict[str, str]]:
    """
    进入关注用户个人页逐个探测是否在直播，返回直播中的用户和链接。
    """
    lives: List[Dict[str, str]] = []
    for p in profiles:
        if len(lives) >= max_lives:
            break
        href = (p.get("href") or "").strip()
        name = _visible_text(p.get("name") or "")
        if not href:
            continue
        slug = (p.get("slug") or _profile_slug(href) or "").strip()
        _scrape_log(f"巡检是否在直播 → {name or slug} ({href})")
        try:
            sep = "&" if ("?" in href) else "?"
            driver.get(f"{href}{sep}tab=live")
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            _human_pause_after_nav(1.0, 2.3)
            status = _detect_live_on_current_square_page(driver)
            if not status.get("is_live"):
                driver.get(href)
                WebDriverWait(driver, 12).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                _human_pause_after_nav(0.75, 1.9)
                status = _detect_live_on_current_square_page(driver)
            if status.get("is_live"):
                links = status.get("live_links") or []
                live_url = _pick_live_url(href, links)
                lives.append(
                    {
                        "author": name
                        or _profile_slug(href)
                        or href.rsplit("/", 1)[-1].split("?")[0],
                        "profile": href.split("#")[0],
                        "live_url": live_url,
                        "raw": "profile_live_probe",
                    }
                )
        except Exception:
            continue
    return lives


def fetch_rankings_from_binance_api(max_items: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    官方现货 24h ticker（无需 API Key）。
    热榜：按 quoteVolume；涨幅/跌幅：按 priceChangePercent。
    仅保留常见 USDT 现货对（排除部分杠杆代币可按需再过滤）。
    """
    if requests is None:
        raise RuntimeError("缺少依赖 requests：无法使用 API 回退（热榜/涨幅/跌幅）。")

    r = requests.get(BINANCE_TICKER_24H, timeout=45)
    r.raise_for_status()
    tickers: List[Dict[str, Any]] = r.json()
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
    if len(rows) < 2 and api_fallback:
        rows = api_fallback[:max_items]
        source = "api_24h"
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
            api_rankings = fetch_rankings_from_binance_api(top_n)
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
        # 关注：打开 Square Following 页面并抽取“直播/最新文章”
        _scrape_log(f"打开关注列表（Square Following）: {watchlist_url}")
        driver.get(watchlist_url)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        _human_pause_after_nav(2.0, 4.0)
        _scrape_log(
            "解析 Following 信息流中的帖子"
            + ("（仅保留重点关注用户）" if has_priority else "")
            + "…"
        )
        square_data = _extract_square_following(
            driver,
            max_items=max_items,
            priority_slugs=priority_slugs if has_priority else None,
        )
        lives_feed = square_data.get("lives") or []
        posts = [
            p
            for p in (square_data.get("latest_posts") or [])
            if isinstance(p, dict)
            and "/square/post/" in (p.get("href") or "").lower()
            and not _square_noise_url(p.get("href") or "")
        ]
        _scrape_log(f"Following 帖子解析完成（符合条件 {len(posts)} 条）")

        _scrape_log("从 Following 页收集 profile 链接…")
        collected = _collect_following_profile_links(
            driver, max_profiles=max(10, max_profiles_to_probe)
        )
        follow_profiles = (
            _merge_priority_profiles(collected, priority_order)
            if has_priority
            else collected
        )

        if has_priority and follow_profiles:
            _scrape_log(
                "从各重点关注用户主页深度滚动合并帖子（补齐时间线中更多篇）…"
            )
            for fp in follow_profiles:
                ph = (fp.get("href") or "").strip()
                slug = (fp.get("slug") or _profile_slug(ph)).lower()
                if not ph or not slug:
                    continue
                extra = _extract_square_profile_posts(
                    driver, ph, slug, max_items=max_items
                )
                if extra:
                    posts = _merge_posts_by_href(posts, extra)
            _scrape_log(f"合并 Following + 主页后帖子共 {len(posts)} 条")

        ref_now = datetime.now(timezone.utc)
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
            _enrich_post_images_from_detail_pages(driver, posts)
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
                driver, follow_profiles, max_lives=max_items
            )
            _scrape_log(f"直播巡检结束（命中 {len(lives_probed)} 条）")
        # 合并：以 profile 探测为准，再补上 Feed 里命中的直播链（按 href 去重）
        lives = list(lives_probed)
        seen_hrefs = {
            (x.get("live_url") or x.get("href") or "").strip() for x in lives
        }
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
        }

        data: Dict[str, object] = {
            "overview_url": url,
            "scraped_at": beijing_time_str(),
            "watchlist": watchlist,
        }
        if include_hot_rank:
            # 热榜 / 涨幅 / 跌幅：overview 上尝试 DOM，失败则用 24h API
            _scrape_log(f"打开行情总览页（榜单）: {url}")
            driver.get(url)
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
        help="不合并 24 小时帖子状态与 Gemini（写入的 JSON 仅为本次抓取快照）",
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
    )
    out_path = os.path.abspath(args.out)
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
