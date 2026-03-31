#!/usr/bin/env python3
"""
使用 Selenium 抓取币安市场列表：
1) 自选/关注列表
2) 热榜
3) 涨幅榜
4) 跌幅榜

默认连接已开启远程调试的 Chrome（复用登录态）：
  Mac:
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222

运行示例：
  python3 binance_market_lists_selenium.py
  python3 binance_market_lists_selenium.py --out ./screenshots/binance_lists.json
  python3 binance_market_lists_selenium.py --url "https://www.binance.com/zh-CN/markets/overview"

说明：
  - 关注列表请使用币安 Square Following 页面（默认 .../square?tab=Following），需已登录。
  - 「谁在直播」：在 Following 页收集 `/square/profile/` 关注主页，再逐个打开（先 `?tab=live`）检测直播并给出 `live_url`。
  - 热榜/涨幅/跌幅若页面虚拟列表未解析到行，会自动回退到官方 /api/v3/ticker/24hr（无需 Key）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import requests  # 用于热榜/涨跌幅 API 回退
except ModuleNotFoundError:  # 允许你只用 DOM 抓 Square Following
    requests = None

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from browser_automation import init_browser


DEFAULT_URL = "https://www.binance.com/zh-CN/markets/overview"
DEFAULT_WATCHLIST_URL = "https://www.binance.com/zh-CN/square?tab=Following"
BINANCE_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"

# 从表格行文本里抠交易对（兼容 BTCUSDT / btcusdt / BTC/USDT）
_ROW_SYMBOL_RE = re.compile(
    r"\b([A-Za-z0-9]{2,20}(?:USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH|BNB|TRY|EUR)(?:\.P)?)\b"
    r"|([A-Za-z0-9]{2,15}/[A-Za-z0-9]{2,15})\b"
)


def _visible_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


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
        time.sleep(0.28)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.4)


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


def _extract_square_following(driver, max_items: int) -> Dict[str, List[Dict[str, str]]]:
    """
    抓币安 Square Following 页面：
    - lives：谁在直播（文本/按钮里出现“直播/LIVE/正在直播”）
    - latest_posts：最新文章/动态（其余非直播条目）

    由于币安 Square DOM 可能随版本变更，这里做宽松解析：基于卡片内文本+链接做去重。
    """
    # 兜底多滚动一下，确保虚拟列表渲染
    _scroll_page_load_lists(driver, scrolls=18)

    return driver.execute_script(
        """
const maxItems = arguments[0];
const out = { lives: [], latest_posts: [] };
const seen = new Set();

// 取所有疑似 Square 卡片链接（不严格依赖具体 class）
const anchors = Array.from(document.querySelectorAll('a[href*="/square/"]'));

const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
const splitLines = (t) => norm(t).split(' ').filter(Boolean);
const isLive = (t) => {
  const s = (t || '').toLowerCase();
  return s.includes('直播') || s.includes('live') || s.includes('正在直播');
};

const findTime = (t) => {
  if (!t) return '';
  const m = (t.match(/\\d{1,2}:\\d{2}/) || [])[0] || '';
  if (m) return m;
  const d = (t.match(/\\d{4}-\\d{2}-\\d{2}/) || [])[0] || '';
  return d;
};

for (const a of anchors) {
  if (out.lives.length >= maxItems && out.latest_posts.length >= maxItems) break;
  const href = a.href || '';
  if (!href) continue;
  // 去重：按 href
  if (seen.has(href)) continue;
  const text = (a.innerText || a.textContent || '').trim();
  if (!text || text.length < 6) continue;

  const live = isLive(text);
  // 标题尽量取前几段“第一行/前若干词”
  const clean = norm(text);
  const parts = clean.split(' ').filter(Boolean);
  const title = parts.slice(0, 16).join(' ');
  const time = findTime(clean);

  // 作者尽量在直播/动态卡片中第二段或包含“·”分隔处
  let author = '';
  const dotIdx = clean.indexOf('·');
  if (dotIdx > 0 && dotIdx < 80) author = clean.slice(0, dotIdx).trim();
  if (!author) {
    // 简单启发：取不包含关键字的短词
    for (const p of parts) {
      if (p.length >= 2 && p.length <= 18 && !isLive(p) && !/直播|live/i.test(p)) { author = p; break; }
    }
  }

  const item = { href, title, author, time, raw: clean };
  if (live) out.lives.push(item);
  else out.latest_posts.push(item);
  seen.add(href);
}

// 保底截断
out.lives = out.lives.slice(0, maxItems);
out.latest_posts = out.latest_posts.slice(0, maxItems);
return out;
        """,
        max_items,
    )


def _collect_following_profile_links(driver, max_profiles: int = 60) -> List[Dict[str, str]]:
    """在 Following 页面收集关注用户主页链接。"""
    _scroll_page_load_lists(driver, scrolls=14)
    profiles = driver.execute_script(
        """
const maxProfiles = arguments[0];
const out = [];
const seen = new Set();
const anchors = Array.from(document.querySelectorAll('a[href*="/square/profile/"]'));
for (const a of anchors) {
  const href = a.href || '';
  if (!href || seen.has(href)) continue;
  const name = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
  out.push({ name, href });
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
// 避免英文单词里误命中（如 deliver 含 live）
const hitCn = raw.includes('正在直播') || raw.includes('直播中');
const hitEn =
  /\\b(live\\s*now|is\\s+live|live\\s*stream|live\\s*broadcast|going\\s*live)\\b/i.test(raw);
const hit = hitCn || hitEn;

const links = [];
const seen = new Set();
for (const a of Array.from(document.querySelectorAll('a[href]'))) {
  const href = a.href || '';
  const t = (a.innerText || a.textContent || '') || '';
  if (!href) continue;
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
return { is_live: hit || links.length > 0, live_links: links.slice(0, 8) };
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
        try:
            sep = "&" if ("?" in href) else "?"
            driver.get(f"{href}{sep}tab=live")
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(1.4)
            status = _detect_live_on_current_square_page(driver)
            if not status.get("is_live"):
                driver.get(href)
                WebDriverWait(driver, 12).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(1.0)
                status = _detect_live_on_current_square_page(driver)
            if status.get("is_live"):
                links = status.get("live_links") or []
                live_url = links[0] if links else f"{href}{sep}tab=live"
                lives.append(
                    {
                        "author": name or href.rsplit("/", 1)[-1],
                        "profile": href,
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
            time.sleep(1.8)
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
    time.sleep(1.0)
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
    max_items: int = 30,
    watchlist_url: str = DEFAULT_WATCHLIST_URL,
    max_profiles_to_probe: int = 40,
    skip_profile_live_probe: bool = False,
) -> Dict[str, object]:
    # 热榜/涨跌幅 DOM 抓不到时才用 API 回退；你本地缺 requests 也不影响 Square Following 的解析
    try:
        api_rankings = fetch_rankings_from_binance_api(max_items)
    except Exception:
        api_rankings = {
            "hot_rank": [],
            "gainers": [],
            "losers": [],
        }
    driver = init_browser(use_remote_debugging=True)
    try:
        # 关注：打开 Square Following 页面并抽取“直播/最新文章”
        driver.get(watchlist_url)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3.0)
        square_data = _extract_square_following(driver, max_items=max_items)
        lives_feed = square_data.get("lives") or []
        posts = square_data.get("latest_posts") or []

        # 关注列表里「谁在直播」：从 Following 页收集 profile，再逐个打开检测（比 Feed 锚点更准）
        if skip_profile_live_probe:
            follow_profiles = []
            lives_probed = []
        else:
            follow_profiles = _collect_following_profile_links(
                driver, max_profiles=max(10, max_profiles_to_probe)
            )
            lives_probed = _probe_live_from_profiles(
                driver, follow_profiles, max_lives=max_items
            )
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

        watchlist: Dict[str, object] = {
            "section": "watchlist_following",
            "page_url": watchlist_url,
            "extraction_source": "dom_square"
            if (lives or posts or follow_profiles)
            else "empty",
            "note": ""
            if (lives or posts or follow_profiles)
            else "未解析到关注/文章：请确认已登录，且页面已加载完成或页面结构已变更。",
            "count_follow_profiles": len(follow_profiles),
            "count_lives": len(lives),
            "count_latest_posts": len(posts),
            "follow_profiles_sample": follow_profiles[:15],
            "lives": lives,
            "latest_posts": posts,
        }

        # 热榜 / 涨幅 / 跌幅：overview 上尝试 DOM，失败则用 24h API
        driver.get(url)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2.5)

        data = {
            "overview_url": url,
            "scraped_at": datetime.now().isoformat(timespec="seconds"),
            "watchlist": watchlist,
            "hot_rank": _collect_section(
                driver,
                "hot_rank",
                ["热榜", "热门", "Hot", "Trending", "成交额"],
                max_items,
                api_fallback=api_rankings["hot_rank"],
            ),
            "gainers": _collect_section(
                driver,
                "gainers",
                ["涨幅榜", "涨幅", "Gainers", "Top Gainers", "涨跌幅"],
                max_items,
                api_fallback=api_rankings["gainers"],
            ),
            "losers": _collect_section(
                driver,
                "losers",
                ["跌幅榜", "跌幅", "Losers", "Top Losers"],
                max_items,
                api_fallback=api_rankings["losers"],
            ),
        }

        # 只清洗榜单 items 的 raw 字段（watchlist 结构不同）
        for key in ("hot_rank", "gainers", "losers"):
            for item in data.get(key, {}).get("items", []):
                if isinstance(item, dict) and "raw" in item:
                    item["raw"] = _visible_text(str(item.get("raw", "")))
        return data
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(
        description="抓取币安关注（Square Following）、热榜、涨幅榜、跌幅榜（Selenium）"
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
        default=30,
        help="每个榜单最多提取条数（默认 30）",
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
    args = parser.parse_args()

    result = scrape_binance_lists(
        url=args.url,
        max_items=max(5, args.max_items),
        watchlist_url=args.watchlist_url,
        max_profiles_to_probe=max(5, args.max_profiles),
        skip_profile_live_probe=args.skip_profile_live_probe,
    )
    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] 已写入: {out_path}")


if __name__ == "__main__":
    main()
