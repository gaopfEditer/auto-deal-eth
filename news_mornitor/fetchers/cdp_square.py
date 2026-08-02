"""
CDP 回退：HTTP/bapi 失败时，经 Chrome 9222 **纯 WebSocket CDP** 后台开页抓取。

绝不使用 Selenium / switch_to / activateTarget —— 那些会抢 macOS 焦点。
实现见 cdp_raw.SilentCdpBrowser（Target.createTarget background + Runtime.evaluate）。

前置：
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
  （建议已登录各交易所，页内 fetch 才不易 401/风控）

环境变量：
  CRYPTO_PULSE_CDP_FALLBACK   默认 1；设 0 关闭
  CHROME_DEBUG_PORT           默认 9222
  CRYPTO_PULSE_CDP_WAIT_SEC   打开页面后等待秒数，默认 4
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from news_mornitor.fetchers.cdp_raw import SilentCdpError, silent_background_page
from news_mornitor.fetchers.common import parse_generic_feed
from news_mornitor.models import Platform, RawFetchItem, utc_now_iso

logger = logging.getLogger("CryptoPulse.CDP")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_CONTENT_ID_RE = {
    Platform.BINANCE: re.compile(r"/square/post/(\d+)", re.I),
    Platform.BITGET: re.compile(r"/insights/posts/([A-Za-z0-9_-]+)", re.I),
    Platform.OKX: re.compile(r"/community/(?:post|topic)/([A-Za-z0-9_-]+)", re.I),
    Platform.BYBIT: re.compile(r"/(?:feed|announcement|community)/([A-Za-z0-9_-]+)", re.I),
}

_PLATFORM_HOME: dict[Platform, str] = {
    Platform.BINANCE: "https://www.binance.com/zh-CN/square",
    Platform.BITGET: "https://www.bitget.com/zh-CN/insights",
    Platform.OKX: "https://www.okx.com/zh-hans/community",
    Platform.BYBIT: "https://www.bybit.com/en/square",
}

_INPAGE_FETCH: dict[Platform, list[tuple[str, dict[str, Any]]]] = {
    Platform.BINANCE: [
        (
            "https://www.binance.com/bapi/composite/v1/friendly/pgc/content/home/squareList"
            "?page=1&rows=40",
            {"clienttype": "web", "lang": "zh-CN"},
        ),
        (
            "https://www.binance.com/bapi/composite/v1/public/pgc/content/home/squareList"
            "?page=1&rows=40",
            {"clienttype": "web", "lang": "zh-CN"},
        ),
        (
            "https://www.binance.com/bapi/composite/v1/friendly/pgc/content/square/list"
            "?page=1&pageSize=40&contentType=ALL",
            {"clienttype": "web", "lang": "zh-CN"},
        ),
    ],
    Platform.BITGET: [
        (
            "https://www.bitget.com/v1/spa/content/square/hot?pageNo=1&pageSize=40&type=hot",
            {},
        ),
        (
            "https://www.bitget.com/v1/spa/content/square/list?pageNo=1&pageSize=40",
            {},
        ),
    ],
    Platform.OKX: [
        (
            "https://www.okx.com/priapi/v5/eco/community/feed/hot?page=1&size=40&sort=hot",
            {},
        ),
        (
            "https://www.okx.com/priapi/v5/eco/community/feed/list?page=1&size=40",
            {},
        ),
    ],
    Platform.BYBIT: [
        (
            "https://api2.bybit.com/spot/api/web/content/feed/list?page=1&limit=40",
            {},
        ),
        (
            "https://api2.bybit.com/spot/api/web/community/feed/list?page=1&limit=40",
            {},
        ),
    ],
}

_URL_BUILDERS: dict[Platform, Callable[[str], str]] = {
    Platform.BINANCE: lambda eid: f"https://www.binance.com/zh-CN/square/post/{eid}",
    Platform.BITGET: lambda eid: f"https://www.bitget.com/zh-CN/insights/posts/{eid}",
    Platform.OKX: lambda eid: f"https://www.okx.com/zh-hans/community/post/{eid}",
    Platform.BYBIT: lambda eid: f"https://www.bybit.com/trade/spot/feed/{eid}",
}

_DOM_HREF_SUBSTR: dict[Platform, str] = {
    Platform.BINANCE: "/square/post/",
    Platform.BITGET: "/insights/posts/",
    Platform.OKX: "/community/",
    Platform.BYBIT: "/square/",
}

_driver_lock = asyncio.Lock()

# 供 Runtime.evaluate：arguments 由 cdp_raw.evaluate_fn 注入
_INPAGE_FETCH_BODY = """
const url = arguments[0];
const extraHeaders = arguments[1] || {};
try {
  const headers = Object.assign({
    'Accept': 'application/json, text/plain, */*',
  }, extraHeaders);
  const resp = await fetch(url, { method: 'GET', credentials: 'include', headers });
  const text = await resp.text();
  return { ok: resp.ok, status: resp.status, text: text.slice(0, 2000000) };
} catch (e) {
  return { ok: false, status: 0, text: String(e) };
}
"""

_DOM_SCRAPE_BODY = """
const hrefSub = arguments[0];
const maxN = arguments[1] || 40;
const out = [];
const seen = new Set();
const links = Array.from(document.querySelectorAll('a[href]'));
function parseCount(s) {
  if (!s) return 0;
  s = String(s).trim().replace(/,/g, '');
  const m = s.match(/([\\d.]+)\\s*([万wW千kK]?)/);
  if (!m) return 0;
  let n = parseFloat(m[1]);
  if (!isFinite(n)) return 0;
  const u = (m[2] || '').toLowerCase();
  if (u === '万' || u === 'w') n *= 10000;
  if (u === '千' || u === 'k') n *= 1000;
  return Math.round(n);
}
for (const a of links) {
  const href = a.href || '';
  if (!href || href.indexOf(hrefSub) < 0) continue;
  if (seen.has(href)) continue;
  seen.add(href);
  const card = a.closest('article')
    || a.closest('[class*="feed"]')
    || a.closest('[class*="post"]')
    || a.closest('[class*="card"]')
    || a.parentElement;
  const text = ((card && card.innerText) || a.innerText || '').trim();
  if (text.length < 4) continue;
  const lines = text.split(/\\n+/).map(x => x.trim()).filter(Boolean);
  const title = (lines[0] || a.getAttribute('title') || '').slice(0, 200);
  let likes = 0, comments = 0;
  for (const line of lines.slice(0, 12)) {
    if (/赞|like|❤|♥/i.test(line)) likes = Math.max(likes, parseCount(line));
    if (/评|comment|reply|回复/i.test(line)) comments = Math.max(comments, parseCount(line));
  }
  const nums = text.match(/\\b\\d{1,3}(?:\\.\\d+)?[万wWkK千]?\\b/g) || [];
  if (!likes && nums.length >= 1) likes = parseCount(nums[nums.length - 2] || nums[0]);
  if (!comments && nums.length >= 2) comments = parseCount(nums[nums.length - 1]);
  out.push({
    href,
    title,
    content: text.slice(0, 2000),
    author: (lines[1] || '').slice(0, 80),
    likes,
    comments,
  });
  if (out.length >= maxN) break;
}
return out;
"""

_REDDIT_HOT_BODY = """
const maxN = arguments[0] || 40;
const out = [];
const seen = new Set();
const anchors = Array.from(document.querySelectorAll('a[href*="/comments/"]'));
function parseCount(s) {
  if (!s) return 0;
  s = String(s).replace(/,/g, '').trim();
  const m = s.match(/([\\d.]+)\\s*([kKmMbB万]?)/);
  if (!m) return 0;
  let n = parseFloat(m[1]);
  const u = (m[2] || '').toLowerCase();
  if (u === 'k') n *= 1000;
  if (u === 'm') n *= 1e6;
  if (u === '万') n *= 10000;
  return Math.round(n);
}
for (const a of anchors) {
  let href = a.href || '';
  if (!href || href.indexOf('/comments/') < 0) continue;
  href = href.split('?')[0];
  if (seen.has(href)) continue;
  const m = href.match(/\\/comments\\/([a-z0-9]+)\\//i);
  if (!m) continue;
  seen.add(href);
  const card = a.closest('article') || a.closest('[data-testid="post-container"]') || a.closest('shreddit-post') || a.parentElement;
  const title = (a.innerText || a.getAttribute('title') || '').trim().slice(0, 200);
  if (title.length < 4) continue;
  let likes = 0, comments = 0, author = '';
  try {
    if (card && card.tagName && card.tagName.toLowerCase() === 'shreddit-post') {
      likes = parseCount(card.getAttribute('score') || card.getAttribute('upvote-count') || '0');
      comments = parseCount(card.getAttribute('comment-count') || '0');
      author = (card.getAttribute('author') || '').trim();
    }
  } catch (e) {}
  const text = (card && card.innerText) || title;
  if (!likes) {
    const sm = text.match(/(\\d+(?:\\.\\d+)?[kKmM]?)\\s*(?:upvotes|points?|分)/i);
    if (sm) likes = parseCount(sm[1]);
  }
  if (!comments) {
    const cm = text.match(/(\\d+(?:\\.\\d+)?[kKmM]?)\\s*(?:comments?|评论)/i);
    if (cm) comments = parseCount(cm[1]);
  }
  out.push({ eid: m[1], href, title, content: text.slice(0, 2000), author, likes, comments });
  if (out.length >= maxN) break;
}
return out;
"""

_BITGET_INSIGHTS_BODY = r"""
const maxN = arguments[0] || 40;
const byId = new Map();
function parseCount(s) {
  if (!s) return 0;
  s = String(s).replace(/,/g, '').trim();
  const m = s.match(/^([\d.]+)\s*([万wWkK千]?)$/);
  if (!m) return 0;
  let n = parseFloat(m[1]);
  if (!isFinite(n)) return 0;
  const u = (m[2] || '').toLowerCase();
  if (u === '万' || u === 'w') n *= 10000;
  if (u === 'k' || u === '千') n *= 1000;
  return Math.round(n);
}
const junk = new Set(['关注','看涨','看跌','推荐','发布','登录','注册','查看原文']);
const timeRe = /\d+\s*(分钟前|小时前|天前|秒前)|刚刚/;
for (const a of document.querySelectorAll('a[href*="/insights/posts/"]')) {
  const href = (a.href || '').split('?')[0];
  const m = href.match(/\/insights\/posts\/([A-Za-z0-9_-]+)/);
  if (!m) continue;
  const eid = m[1];
  let card = a;
  for (let i = 0; i < 8 && card; i++) {
    card = card.parentElement;
    if (!card) break;
    const t = (card.innerText || '').trim();
    if (t.length > 80 && card.querySelectorAll('a[href*="/insights/posts/' + eid + '"]').length > 0) break;
  }
  const text = ((card && card.innerText) || a.innerText || '').trim();
  const prev = byId.get(eid);
  if (prev && prev.content.length >= text.length) continue;
  const lines = text.split(/\n+/).map(x => x.trim()).filter(Boolean);
  let author = '';
  for (const l of lines.slice(0, 5)) {
    if (l.length >= 2 && l.length <= 30 && !junk.has(l) && !timeRe.test(l) && !/^\$/.test(l) && !/^\d+(\.\d+)?%?$/.test(l)) {
      author = l; break;
    }
  }
  let title = '';
  let body = '';
  for (const l of lines) {
    if (junk.has(l) || timeRe.test(l) || l === author) continue;
    if (/^\$[A-Z0-9._-]+$/.test(l)) continue;
    if (/^\d+(\.\d+)?%?$/.test(l) && l.length <= 8) continue;
    if (/^\+?\d+$/.test(l)) continue;
    if (l.length >= 12 && l.length > title.length && l.length < 140) title = l;
    if (l.length > 50 && l.length > body.length) body = l;
  }
  if (!title) title = (body || author || eid).slice(0, 200);
  let likes = 0, comments = 0;
  const numIdx = [];
  lines.forEach((l, i) => {
    const n = parseCount(l);
    if (n > 0 && /^[\d.万wWkK千]+$/.test(l) && l.length <= 10) numIdx.push([i, n]);
  });
  if (numIdx.length >= 2) { likes = numIdx[numIdx.length - 2][1]; comments = numIdx[numIdx.length - 1][1]; }
  else if (numIdx.length === 1) likes = numIdx[0][1];
  byId.set(eid, {
    eid, href, author,
    title: title.slice(0, 200),
    content: (body || title).slice(0, 2000),
    likes, comments,
    len: text.length,
  });
}
return [...byId.values()].sort((a, b) => (b.likes + b.comments * 3) - (a.likes + a.comments * 3) || b.len - a.len).slice(0, maxN);
"""


def cdp_fallback_enabled() -> bool:
    return os.getenv("CRYPTO_PULSE_CDP_FALLBACK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def chrome_debug_port() -> int:
    try:
        return int(os.getenv("CHROME_DEBUG_PORT", "9222"))
    except ValueError:
        return 9222


def cdp_wait_sec() -> float:
    try:
        return float(os.getenv("CRYPTO_PULSE_CDP_WAIT_SEC", "4"))
    except ValueError:
        return 4.0


def chrome_cdp_alive(port: Optional[int] = None) -> bool:
    port = port or chrome_debug_port()
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _parse_inpage_json(text: str, platform: Platform) -> list[RawFetchItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    builder = _URL_BUILDERS.get(platform, lambda eid: eid)
    return parse_generic_feed(data, platform=platform, url_builder=builder)


def _dom_rows_to_items(
    rows: list[dict[str, Any]],
    *,
    platform: Platform,
    limit: int,
) -> list[RawFetchItem]:
    pat = _CONTENT_ID_RE.get(platform)
    builder = _URL_BUILDERS.get(platform, lambda eid: eid)
    out: list[RawFetchItem] = []
    seen: set[str] = set()
    for row in rows:
        href = str(row.get("href") or "").strip()
        title = str(row.get("title") or "").strip()
        content = str(row.get("content") or title).strip()
        if not href or not title:
            continue
        eid = ""
        if pat:
            m = pat.search(href)
            if m:
                eid = m.group(1)
        if not eid:
            eid = re.sub(r"\W+", "", href)[-24:] or href[-24:]
        if eid in seen:
            continue
        seen.add(eid)
        likes = int(row.get("likes") or 0)
        comments = int(row.get("comments") or 0)
        out.append(
            RawFetchItem(
                external_id=eid,
                platform=platform,
                author=str(row.get("author") or platform.value.lower())[:80],
                title=title[:200],
                content=content[:4000],
                like_count=likes,
                comment_count=comments,
                share_count=0,
                published_at=utc_now_iso(),
                source_url=href if href.startswith("http") else builder(eid),
            )
        )
        if len(out) >= limit:
            break
    return out


def _inpage_fetch(browser: Any, sid: str, api_url: str, headers: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        result = browser.evaluate_fn(
            sid, _INPAGE_FETCH_BODY, api_url, headers, await_promise=True
        )
    except Exception as e:
        logger.debug("[cdp] 页内 fetch 异常 %s: %s", api_url[:60], e)
        return None
    return result if isinstance(result, dict) else None


def _scrape_platform_sync(platform: Platform, *, limit: int = 40) -> list[RawFetchItem]:
    if not chrome_cdp_alive():
        logger.warning(
            "[cdp] Chrome 9222 未就绪（平台=%s）。请先: Chrome --remote-debugging-port=%s",
            platform.value,
            chrome_debug_port(),
        )
        return []

    home = _PLATFORM_HOME.get(platform)
    if not home:
        return []

    port = chrome_debug_port()
    try:
        with silent_background_page(
            port, home, wait_sec=cdp_wait_sec(), page_load_timeout=28
        ) as (browser, sid):
            for api_url, headers in _INPAGE_FETCH.get(platform, []):
                result = _inpage_fetch(browser, sid, api_url, headers)
                if not result or not result.get("ok"):
                    st = result.get("status") if isinstance(result, dict) else "?"
                    logger.debug("[cdp] 页内 fetch HTTP %s %s", st, api_url[:80])
                    continue
                items = _parse_inpage_json(str(result.get("text") or ""), platform)
                if items:
                    logger.info(
                        "[cdp] %s 页内 API 命中 %d 条 (%s)",
                        platform.value,
                        len(items),
                        api_url.split("?", 1)[0][-48:],
                    )
                    return items[:limit]

            href_sub = _DOM_HREF_SUBSTR.get(platform, "/square/")
            try:
                rows = browser.evaluate_fn(
                    sid, _DOM_SCRAPE_BODY, href_sub, max(limit, 40)
                )
            except Exception as e:
                logger.warning("[cdp] DOM 解析失败: %s", e)
                rows = []
            if isinstance(rows, list) and rows:
                items = _dom_rows_to_items(rows, platform=platform, limit=limit)
                if items:
                    logger.info("[cdp] %s DOM 抓到 %d 条真链", platform.value, len(items))
                    return items
            logger.warning("[cdp] %s 页内 API + DOM 均无结果", platform.value)
            return []
    except SilentCdpError as e:
        logger.warning("[cdp] 静默 CDP 失败: %s", e)
        return []
    except Exception as e:
        logger.warning("[cdp] 静默打开页面失败: %s", e)
        return []


async def fetch_via_cdp(platform: Platform, *, limit: int = 40) -> list[RawFetchItem]:
    """异步入口：HTTP 失败后调用。串行化，避免多源同时抢 Chrome。"""
    if not cdp_fallback_enabled():
        return []
    async with _driver_lock:
        return await asyncio.to_thread(_scrape_platform_sync, platform, limit=limit)


def _scrape_reddit_hot_sync(*, limit: int = 40) -> list[RawFetchItem]:
    if not chrome_cdp_alive():
        logger.warning("[cdp] Reddit: Chrome 9222 未就绪")
        return []
    home = os.getenv(
        "CRYPTO_PULSE_REDDIT_HOT_URL",
        "https://www.reddit.com/r/CryptoCurrency/hot/",
    ).strip()
    port = chrome_debug_port()
    try:
        with silent_background_page(
            port, home, wait_sec=max(cdp_wait_sec(), 5), page_load_timeout=35
        ) as (browser, sid):
            api = "https://www.reddit.com/r/CryptoCurrency/hot.json?limit=50&raw_json=1"
            result = _inpage_fetch(browser, sid, api, {"Accept": "application/json"})
            if isinstance(result, dict) and result.get("ok"):
                try:
                    data = json.loads(str(result.get("text") or ""))
                    kids = (data.get("data") or {}).get("children") or []
                    out: list[RawFetchItem] = []
                    for c in kids:
                        row = (c or {}).get("data") or {}
                        eid = str(row.get("id") or "").strip()
                        title = str(row.get("title") or "").strip()
                        if not eid or not title:
                            continue
                        permalink = str(row.get("permalink") or "")
                        url = (
                            f"https://www.reddit.com{permalink}"
                            if permalink.startswith("/")
                            else (
                                permalink
                                or f"https://www.reddit.com/r/CryptoCurrency/comments/{eid}/"
                            )
                        )
                        created = row.get("created_utc")
                        pub = utc_now_iso()
                        try:
                            from datetime import datetime, timezone

                            pub = datetime.fromtimestamp(
                                float(created), tz=timezone.utc
                            ).strftime("%Y-%m-%dT%H:%M:%SZ")
                        except (TypeError, ValueError, OSError):
                            pass
                        author = str(row.get("author") or "reddit")
                        out.append(
                            RawFetchItem(
                                external_id=eid,
                                platform=Platform.REDDIT,
                                author=author if author.startswith("u/") else f"u/{author}",
                                title=title[:200],
                                content=str(row.get("selftext") or title)[:2000],
                                like_count=int(row.get("score") or 0),
                                comment_count=int(row.get("num_comments") or 0),
                                share_count=int(row.get("num_crossposts") or 0),
                                published_at=pub,
                                source_url=url,
                            )
                        )
                        if len(out) >= limit:
                            break
                    if out:
                        logger.info("[cdp] Reddit hot.json 命中 %d 条", len(out))
                        return out
                except Exception as e:
                    logger.debug("[cdp] Reddit hot.json 解析失败: %s", e)

            rows = browser.evaluate_fn(sid, _REDDIT_HOT_BODY, max(limit, 40))
            if not isinstance(rows, list):
                return []
            out = []
            for row in rows:
                eid = str(row.get("eid") or "").strip()
                title = str(row.get("title") or "").strip()
                href = str(row.get("href") or "").strip()
                if not eid or not title:
                    continue
                author = str(row.get("author") or "reddit")
                out.append(
                    RawFetchItem(
                        external_id=eid,
                        platform=Platform.REDDIT,
                        author=author if author.startswith("u/") else f"u/{author}",
                        title=title[:200],
                        content=str(row.get("content") or title)[:2000],
                        like_count=int(row.get("likes") or 0),
                        comment_count=int(row.get("comments") or 0),
                        published_at=utc_now_iso(),
                        source_url=href,
                    )
                )
                if len(out) >= limit:
                    break
            if out:
                logger.info("[cdp] Reddit DOM 命中 %d 条", len(out))
            return out
    except Exception as e:
        logger.warning("[cdp] Reddit 静默打开失败: %s", e)
        return []


def _scrape_tradingview_ideas_sync(*, limit: int = 40) -> list[RawFetchItem]:
    if not chrome_cdp_alive():
        return []
    home = os.getenv(
        "CRYPTO_PULSE_TV_IDEAS_URL",
        "https://www.tradingview.com/markets/cryptocurrencies/ideas/",
    ).strip()
    port = chrome_debug_port()
    try:
        with silent_background_page(
            port, home, wait_sec=max(cdp_wait_sec(), 4), page_load_timeout=30
        ) as (browser, sid):
            try:
                html = browser.evaluate(
                    sid, "document.documentElement.outerHTML || ''"
                ) or ""
            except Exception as e:
                logger.warning("[cdp] TV 取 HTML 失败: %s", e)
                return []
            from news_mornitor.fetchers.tradingview_ideas import _parse_ideas_from_html

            ideas = _parse_ideas_from_html(str(html))
            out: list[RawFetchItem] = []
            for idea in ideas:
                agrees = int(
                    idea.get("agree_count")
                    or idea.get("likes_count")
                    or idea.get("boosts_count")
                    or 0
                )
                comments = int(idea.get("comments_count") or 0)
                is_hot = bool(idea.get("is_hot"))
                if not is_hot and agrees <= 0 and comments <= 0:
                    continue
                eid = str(idea.get("id") or "").strip()
                title = str(idea.get("name") or "").strip()
                if not eid or not title:
                    continue
                user = idea.get("user") or {}
                author = ""
                if isinstance(user, dict):
                    author = str(user.get("username") or "")
                chart = str(
                    idea.get("chart_url") or f"https://www.tradingview.com/chart/{eid}/"
                )
                out.append(
                    RawFetchItem(
                        external_id=eid,
                        platform=Platform.TRADINGVIEW,
                        author=author or "tradingview",
                        title=title[:200],
                        content=str(idea.get("description") or title)[:2000],
                        like_count=max(agrees, 1 if is_hot else agrees),
                        comment_count=comments,
                        source_url=chart,
                        published_at=utc_now_iso(),
                    )
                )
                if len(out) >= limit:
                    break
            if out:
                logger.info("[cdp] TradingView Ideas 命中 %d 条", len(out))
            return out
    except Exception as e:
        logger.warning("[cdp] TradingView 静默打开失败: %s", e)
        return []


def _scrape_bitget_insights_sync(*, limit: int = 40) -> list[RawFetchItem]:
    if not chrome_cdp_alive():
        logger.warning("[cdp] Bitget Insights: Chrome 9222 未就绪")
        return []
    home = os.getenv(
        "CRYPTO_PULSE_BITGET_INSIGHTS_URL",
        "https://www.bitget.com/zh-CN/insights",
    ).strip()
    port = chrome_debug_port()
    try:
        with silent_background_page(
            port, home, wait_sec=max(cdp_wait_sec(), 5), page_load_timeout=35
        ) as (browser, sid):
            try:
                rows = browser.evaluate_fn(sid, _BITGET_INSIGHTS_BODY, max(limit, 40))
            except Exception as e:
                logger.warning("[cdp] Bitget DOM 失败: %s", e)
                return []
            if not isinstance(rows, list):
                return []
            out: list[RawFetchItem] = []
            for row in rows:
                eid = str(row.get("eid") or "").strip()
                title = str(row.get("title") or "").strip()
                href = str(row.get("href") or "").strip()
                if not eid or not title or title in ("查看原文",):
                    continue
                author = str(row.get("author") or "bitget").strip()
                if author in ("查看原文",):
                    author = "bitget"
                out.append(
                    RawFetchItem(
                        external_id=eid,
                        platform=Platform.BITGET,
                        author=author[:80],
                        title=title[:200],
                        content=str(row.get("content") or title)[:4000],
                        like_count=int(row.get("likes") or 0),
                        comment_count=int(row.get("comments") or 0),
                        published_at=utc_now_iso(),
                        source_url=href
                        or f"https://www.bitget.com/zh-CN/insights/posts/{eid}",
                    )
                )
                if len(out) >= limit:
                    break
            if out:
                logger.info("[cdp] Bitget Insights DOM 命中 %d 条", len(out))
            return out
    except Exception as e:
        logger.warning("[cdp] Bitget 静默打开失败: %s", e)
        return []


async def fetch_reddit_hot_cdp(*, limit: int = 40) -> list[RawFetchItem]:
    if not cdp_fallback_enabled():
        return []
    async with _driver_lock:
        return await asyncio.to_thread(_scrape_reddit_hot_sync, limit=limit)


async def fetch_tradingview_ideas_cdp(*, limit: int = 40) -> list[RawFetchItem]:
    if not cdp_fallback_enabled():
        return []
    async with _driver_lock:
        return await asyncio.to_thread(_scrape_tradingview_ideas_sync, limit=limit)


async def fetch_bitget_insights_cdp(*, limit: int = 40) -> list[RawFetchItem]:
    if not cdp_fallback_enabled():
        return []
    async with _driver_lock:
        return await asyncio.to_thread(_scrape_bitget_insights_sync, limit=limit)
