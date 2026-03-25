"""
从 RSSHub / FreshRSS 等 RSS 源获取资讯，可选 LLM 提纯后生成简报并推送 Telegram。

环境变量（可选）：
  QWEN_API_KEY: 通义千问（DashScope OpenAI 兼容接口）API Key；与 GETINFO_PURIFY_ENGINE 配合使用
  QWEN_API_URL: 默认 https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
  QWEN_MODEL: 默认 qwen-turbo（可改为 qwen-plus、qwen-max 等）
  GETINFO_PURIFY_ENGINE: 空=自动（优先 Qwen，无 QWEN_API_KEY 时用 GEMINI 代理）；qwen / gemini 强制指定
  GEMINI_API_URL: 提纯用 Gemini 聊天接口（如 https://xxx/gemini/chat），不设则不做 AI 提纯
  RSSHUB_BASE:   RSSHub 基础 URL，默认 https://rsshub.app（仅作用于下方默认订阅里的 rsshub.app 占位）
  RSSHUB_FEEDS:   JSON 数组完全覆盖订阅列表，格式 [{"name":"","url":"","role":""}]
  FRESHRSS_RSS_URL:  FreshRSS 对外 RSS 地址（用户查询分享里选 RSS，或实例提供的带 token 的 RSS URL）
  FRESHRSS_FEED_NAME / FRESHRSS_ROLE: 上述源的显示名与 role，默认 FreshRSS / k_line_analysis
  RSSHUB_YOUTUBE_TRENDING_URL: 自建 RSSHub 完整路由 URL（如 .../youtube/trending/cn?token=xxx，token 勿提交仓库）
  或拆分为 RSSHUB_SELF_BASE + RSSHUB_ACCESS_TOKEN（自动拼 /youtube/trending/cn?token=）
  RSSHUB_YOUTUBE_FEED_NAME / RSSHUB_YOUTUBE_ROLE: YouTube 源显示名与 role
  RSSHUB_APPEND_DEFAULTS: 设为 0 时仅使用 FRESHRSS / 自建 YouTube 等「额外源」，不再追加默认 Reuters 等（若额外源为空则仍用默认列表）
  GETINFO_DAILY_FILE: 简报追加写入的文件路径，默认 daily_insight.md
  GETINFO_SEND_TELEGRAM: 是否发送简报到 Telegram，默认 1
  GETINFO_RSS_USER_AGENT: 拉取 RSS 时的 User-Agent；不设则模拟 Chrome（部分站点对 requests 默认 UA 返回 403）
  GETINFO_RSS_WARMUP_FIRST: 设为 1 时先 GET 站点首页再拉 RSS（部分 WAF 需先下发 Cookie）
  GETINFO_RSS_STRIP_REFERER: 设为 1 时不带 Referer（少数反代对 Referer 与直连不一致会 403）
  GETINFO_RSS_SELENIUM_CDP: 设为 1 时用 Selenium 连接本机 Chrome 远程调试（与 getinfo.run_binance_square 相同，debuggerAddress + CHROME_DEBUG_PORT，默认 9222）再打开 RSS，绕过 WAF/403
  GETINFO_RSS_USE_PLAYWRIGHT: 兼容旧名，等同 GETINFO_RSS_SELENIUM_CDP=1（已不再使用 Playwright）
  GETINFO_RSS_CDP_FALLBACK: Selenium 失败时是否回退 requests，默认 0（避免用 requests 再撞 403 掩盖真实错误）
  GETINFO_RSS_BROWSER_SUBFETCH: 设为 1 时，在导航结果为空后再尝试页面内 fetch/XHR（部分 WAF 会拦子请求，默认关）
"""
import os
import re
import json
import requests
from urllib.parse import urlparse
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    # 让 getinfo 脚本也能读项目根目录的 .env（和主程序一致）
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import feedparser
except ImportError:
    feedparser = None

# RSSHub 默认订阅（可通过 RSSHUB_FEEDS 覆盖）
DEFAULT_RSS_FEEDS = [
    {"name": "金融-委内瑞拉局势", "url": "https://rsshub.app/reuters/world/americas", "role": "k_line_analysis"},
    {"name": "技术-Github趋势", "url": "https://rsshub.app/github/trending/daily/javascript", "role": "common"},
    {"name": "Hacker News", "url": "https://rsshub.app/hackernews", "role": "common"},
]


def get_gemini_api_url() -> Optional[str]:
    """提纯用 Gemini 接口 URL，未配置则返回 None。"""
    return (os.getenv("GEMINI_API_URL") or os.getenv("RSSHUB_GEMINI_API_URL") or "").strip() or None


def get_qwen_api_key() -> Optional[str]:
    """通义千问 API Key（DashScope），未配置则返回 None。"""
    return (os.getenv("QWEN_API_KEY") or "").strip() or None


def _truncate_raw(content: str, limit: int = 400) -> str:
    return content[:limit] + ("..." if len(content) > limit else "")


def filter_with_qwen(content: str, role: str, timeout: Optional[int] = None) -> str:
    """
    调用通义千问（DashScope 兼容 OpenAI Chat）对资讯做价值提纯。
    未配置 QWEN_API_KEY 或请求失败时返回截断原文。
    """
    api_key = get_qwen_api_key()
    if not api_key:
        return _truncate_raw(content)
    url = (os.getenv("QWEN_API_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").strip()
    model = (os.getenv("QWEN_MODEL") or "qwen-turbo").strip()
    if timeout is None:
        try:
            timeout = int(os.getenv("QWEN_TIMEOUT", "60"))
        except ValueError:
            timeout = 60
    user_text = (
        f"[分析上下文 role={role}]\n"
        f"请对以下资讯进行价值提纯，过滤无用信息，只保留核心逻辑：\n\n{content}"
    )
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是财经与科技资讯助理，输出简洁中文要点。"},
                    {"role": "user", "content": user_text},
                ],
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return _truncate_raw(content)
        data = resp.json()
        msg = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content")
        )
        if msg and isinstance(msg, str) and msg.strip():
            return msg.strip()
        return _truncate_raw(content)
    except Exception as e:
        return f"[提纯失败: {e}] {_truncate_raw(content, 300)}"


def purify_content(content: str, role: str) -> str:
    """
    按环境变量选择提纯后端：GETINFO_PURIFY_ENGINE 或自动（优先 Qwen，其次 Gemini 代理）。
    """
    engine = (os.getenv("GETINFO_PURIFY_ENGINE") or "").strip().lower()
    if engine == "gemini":
        return filter_with_gemini(content, role)
    if engine == "qwen":
        return filter_with_qwen(content, role)
    if get_qwen_api_key():
        return filter_with_qwen(content, role)
    if get_gemini_api_url():
        return filter_with_gemini(content, role)
    return _truncate_raw(content)


def _extra_feeds_from_env() -> List[Dict[str, str]]:
    """从环境变量组装 FreshRSS、自建 RSSHub（YouTube 等）等额外订阅（不含默认 Reuters 列表）。"""
    out: List[Dict[str, str]] = []
    fr = (os.getenv("FRESHRSS_RSS_URL") or "").strip()
    if fr:
        name = (os.getenv("FRESHRSS_FEED_NAME") or "FreshRSS").strip() or "FreshRSS"
        role = (os.getenv("FRESHRSS_ROLE") or "k_line_analysis").strip() or "k_line_analysis"
        out.append({"name": name, "url": fr, "role": role})

    yt = (os.getenv("RSSHUB_YOUTUBE_TRENDING_URL") or "").strip()
    if not yt:
        base = (os.getenv("RSSHUB_SELF_BASE") or "").strip().rstrip("/")
        token = (os.getenv("RSSHUB_ACCESS_TOKEN") or "").strip()
        if base and token:
            yt = f"{base}/youtube/trending/cn?token={token}"
    if yt:
        yname = (os.getenv("RSSHUB_YOUTUBE_FEED_NAME") or "YouTube-国内热榜").strip() or "YouTube-国内热榜"
        yrole = (os.getenv("RSSHUB_YOUTUBE_ROLE") or "common").strip() or "common"
        out.append({"name": yname, "url": yt, "role": yrole})
    return out


def get_rss_feeds() -> List[Dict[str, str]]:
    """获取 RSS 订阅列表：优先环境变量 RSSHUB_FEEDS（JSON），否则为「额外源」+ 默认列表（可关默认）。"""
    raw = os.getenv("RSSHUB_FEEDS", "").strip()
    if raw:
        try:
            feeds = json.loads(raw)
            if isinstance(feeds, list) and feeds:
                return feeds
        except json.JSONDecodeError:
            pass

    extras = _extra_feeds_from_env()
    append_defaults = os.getenv("RSSHUB_APPEND_DEFAULTS", "1").strip() != "0"
    base = (os.getenv("RSSHUB_BASE") or "https://rsshub.app").strip().rstrip("/")
    defaults = [
        {**f, "url": f["url"].replace("https://rsshub.app", base).replace("http://你的IP:1200", base)}
        for f in DEFAULT_RSS_FEEDS
    ]
    if append_defaults:
        return extras + defaults
    if extras:
        return extras
    return defaults


def filter_with_gemini(content: str, role: str, api_url: Optional[str] = None, timeout: int = 30) -> str:
    """
    调用 Gemini 聊天接口对资讯做价值提纯。
    若未配置 api_url 或请求失败，返回原始摘要。
    """
    api_url = api_url or get_gemini_api_url()
    if not api_url:
        return content[:400] + ("..." if len(content) > 400 else "")
    try:
        payload = {
            "role": role,
            "message": f"请对以下资讯进行价值提纯，过滤无用信息，只保留核心逻辑：\n\n{content}",
        }
        resp = requests.post(api_url, data=payload, timeout=timeout)
        if resp.status_code != 200:
            return content[:400] + "..."
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return data.get("message", data.get("text", content[:400] + "..."))
    except Exception as e:
        return f"[提纯失败: {e}] {content[:300]}..."


def _rss_origin(feed_url: str) -> str:
    try:
        p = urlparse(feed_url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}/"
    except Exception:
        pass
    return ""


def _rss_request_headers(feed_url: str, *, strip_referer: bool = False) -> Dict[str, str]:
    """
    浏览器常见头：仅用「脚本 UA」时，不少反爬/CDN 会对 RSS 返回 403，而浏览器直接打开正常。
    """
    ua = (os.getenv("GETINFO_RSS_USER_AGENT") or "").strip()
    if not ua:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    strip_ref = strip_referer or (os.getenv("GETINFO_RSS_STRIP_REFERER", "").strip() == "1")
    headers: Dict[str, str] = {
        "User-Agent": ua,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    if not strip_ref:
        try:
            p = urlparse(feed_url)
            if p.scheme and p.netloc:
                headers["Referer"] = f"{p.scheme}://{p.netloc}/"
                headers["Sec-Fetch-Site"] = "same-origin"
        except Exception:
            pass
    return headers


def _chrome_debug_port() -> int:
    try:
        from config import CHROME_DEBUG_PORT as port
        return int(port)
    except Exception:
        try:
            return int(os.getenv("CHROME_DEBUG_PORT", "9222"))
        except ValueError:
            return 9222


def _use_selenium_cdp_for_rss() -> bool:
    if os.getenv("GETINFO_RSS_SELENIUM_CDP", "").strip().lower() in ("1", "true", "yes"):
        return True
    # 旧环境变量名，与 binance 一致走 CDP，无需 Playwright
    return os.getenv("GETINFO_RSS_USE_PLAYWRIGHT", "").strip().lower() in ("1", "true", "yes")


def _selenium_cdp_fallback_enabled() -> bool:
    """默认不回退 requests：避免 403 来自 Python 请求，与「浏览器里明明能开」的语义不一致。"""
    v = (os.getenv("GETINFO_RSS_CDP_FALLBACK") or os.getenv("GETINFO_RSS_PLAYWRIGHT_FALLBACK") or "0").strip()
    return v == "1"


def _rss_text_from_navigation_dom(driver: Any) -> str:
    """
    只读「driver.get 已完成的导航结果」里的文档，与地址栏展示同源；不发起 fetch/XHR 二次请求。
    很多网关允许 document 导航 200，但拦子资源/API 请求。
    """
    out = driver.execute_script(
        """
        try {
          var root = document.documentElement;
          if (root) {
            var ln = (root.localName || root.nodeName || '').toLowerCase().replace(/^[^:]+:/, '');
            if (ln === 'rss' || ln === 'feed' || ln === 'rdf') {
              return new XMLSerializer().serializeToString(document);
            }
          }
          var ct = (document.contentType || '').toLowerCase();
          if (ct.indexOf('xml') >= 0 && root) {
            return new XMLSerializer().serializeToString(document);
          }
          var pres = document.getElementsByTagName('pre');
          for (var i = 0; i < pres.length; i++) {
            var s = (pres[i].innerText || pres[i].textContent || '').trim();
            if (s.indexOf('<rss') >= 0 || s.indexOf('<feed') >= 0) return s;
          }
          if (document.body) {
            var b = (document.body.innerText || '').trim();
            if (b.indexOf('<?xml') === 0 || b.indexOf('<rss') >= 0 || b.indexOf('<feed') >= 0) return b;
          }
        } catch (e) {}
        return '';
        """
    )
    return (out or "").strip() if isinstance(out, str) else ""


def _extract_rss_fragment_from_page_source(page_source: str) -> Optional[str]:
    """从整页 HTML/XML 字符串中抠出 <rss>...</rss> 或 <feed>...</feed>。"""
    if not page_source or not page_source.strip():
        return None
    s = page_source
    for pat in (r"<rss\b[^>]*>[\s\S]*?</rss>", r"<feed\b[^>]*>[\s\S]*?</feed>"):
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _rss_body_via_subresource_fetch(driver: Any, url: str) -> str:
    """可选：页面内 fetch + 同步 XHR（仅当 GETINFO_RSS_BROWSER_SUBFETCH=1）。"""
    text = driver.execute_async_script(
        """
        var target = arguments[0];
        var done = arguments[arguments.length - 1];
        fetch(target, { credentials: 'include', cache: 'no-store', redirect: 'follow' })
          .then(function(r) {
            if (!r.ok) return r.text().then(function() { throw new Error('HTTP ' + r.status); });
            return r.text();
          })
          .then(function(t) { done(t); })
          .catch(function(e) { done('__ERR__:' + (e && e.message ? e.message : String(e))); });
        """,
        url,
    )
    if isinstance(text, str) and text.strip() and not text.startswith("__ERR__:"):
        return text
    xout = driver.execute_script(
        """
        var u = arguments[0];
        try {
          var x = new XMLHttpRequest();
          x.open('GET', u, false);
          x.send(null);
          if (x.status !== 200) return '';
          return x.responseText;
        } catch (e) { return ''; }
        """,
        url,
    )
    return (xout or "").strip() if isinstance(xout, str) else ""


def fetch_rss_raw_via_selenium_cdp(feed_url: str, timeout: int) -> bytes:
    """
    通过 Selenium 连接已启动远程调试的 Chrome（同 binance_square_cdp._connect_chrome_driver）。

    只信任「导航」结果：driver.get 后从 **当前文档 DOM / page_source** 提取 RSS/XML，
    与你在地址栏打开同一 URL 所见一致；**默认不再**发 fetch/XHR/Python requests，避免被 WAF 403。

    前置：本机已启动 Chrome，例如 chrome.exe --remote-debugging-port=9222
    """
    from selenium.webdriver.support.ui import WebDriverWait

    from getinfo.binance_square_cdp import _connect_chrome_driver

    sec = max(int(timeout), 15)
    driver = _connect_chrome_driver(_chrome_debug_port())
    try:
        driver.set_page_load_timeout(sec)
        driver.set_script_timeout(sec)
        driver.get(feed_url)
        WebDriverWait(driver, min(sec, 60)).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        final_url = (driver.current_url or feed_url).strip()

        text = _rss_text_from_navigation_dom(driver)
        if not text:
            ps = driver.page_source or ""
            text = _extract_rss_fragment_from_page_source(ps) or ""

        if not text and os.getenv("GETINFO_RSS_BROWSER_SUBFETCH", "").strip() == "1":
            text = _rss_body_via_subresource_fetch(driver, final_url)

        if not (text or "").strip():
            raise RuntimeError(
                "导航完成后仍无法从页面解析出 RSS/Atom。"
                "请确认地址栏直接打开该 URL 能看到 XML；若仍失败可设 GETINFO_RSS_BROWSER_SUBFETCH=1 尝试子请求"
            )
        return text.encode("utf-8")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _fetch_rss_raw_requests(feed_url: str, timeout: int) -> bytes:
    """
    拉取 RSS 原始字节。遇 403 时依次尝试：会话预热、去掉 Referer（部分反代仅允许「地址栏直开」形态）。
    """
    origin = _rss_origin(feed_url)
    warm_first = os.getenv("GETINFO_RSS_WARMUP_FIRST", "").strip() == "1"

    def one_session(headers: Dict[str, str], warmup: bool) -> requests.Response:
        s = requests.Session()
        s.headers.update(headers)
        if warmup and origin:
            s.get(origin, timeout=timeout, allow_redirects=True)
        return s.get(feed_url, timeout=timeout, allow_redirects=True)

    # 1) 默认头（含 Referer）
    h = _rss_request_headers(feed_url)
    r = one_session(h, warm_first)
    if r.status_code == 200:
        return r.content

    # 2) 未主动预热且 403：先访问首页再拉 RSS
    if r.status_code == 403 and origin and not warm_first:
        r = one_session(h, True)
        if r.status_code == 200:
            return r.content

    # 3) 仍 403：去掉 Referer / Sec-Fetch-Site 改为 none
    if r.status_code == 403:
        h2 = _rss_request_headers(feed_url, strip_referer=True)
        r = one_session(h2, False)
        if r.status_code == 200:
            return r.content
    if r.status_code == 403:
        h3 = _rss_request_headers(feed_url, strip_referer=True)
        r = one_session(h3, True)
        if r.status_code == 200:
            return r.content

    r.raise_for_status()
    return r.content


def _fetch_rss_raw(feed_url: str, timeout: int) -> bytes:
    if _use_selenium_cdp_for_rss():
        try:
            return fetch_rss_raw_via_selenium_cdp(feed_url, timeout)
        except Exception as e:
            if not _selenium_cdp_fallback_enabled():
                raise
            print(f"[WARN] Selenium CDP 拉取 RSS 失败，回退 requests: {e}")
            return _fetch_rss_raw_requests(feed_url, timeout)
    return _fetch_rss_raw_requests(feed_url, timeout)


def fetch_feed_entries(feed_url: str, max_entries: int = 3, timeout: int = 15) -> List[Dict[str, Any]]:
    """拉取单条 RSS 源的前 max_entries 条条目。"""
    if not feedparser:
        raise ImportError("请安装 feedparser: pip install feedparser")
    raw = _fetch_rss_raw(feed_url, timeout=timeout)
    parsed = feedparser.parse(raw)
    entries = []
    for e in getattr(parsed, "entries", [])[:max_entries]:
        title = getattr(e, "title", "") or ""
        desc = getattr(e, "description", "") or getattr(e, "summary", "") or ""
        link = getattr(e, "link", "") or ""
        published = getattr(e, "published", "") or getattr(e, "updated", "")
        entries.append({"title": title, "description": desc, "link": link, "published": published})
    return entries


def generate_morning_report(
    feeds: Optional[List[Dict[str, str]]] = None,
    max_entries_per_feed: int = 3,
    use_gemini: bool = True,
    save_path: Optional[str] = None,
    send_telegram: Optional[bool] = None,
) -> str:
    """
    从 RSSHub 拉取各源最新条目，可选 LLM 提纯（默认优先 Qwen，其次 Gemini 代理），生成简报字符串。
    use_gemini: 实为「是否启用 LLM 提纯」，名称保留兼容旧调用。
    若 save_path 非空则追加写入文件；若 send_telegram 为 True 则发送到 Telegram。
    """
    feeds = feeds or get_rss_feeds()
    # 避免 Windows 终端/文件默认 gbk 编码导致的 emoji 写入失败
    report = f"[REPORT] AI 提纯简报 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    report += "=" * 40 + "\n"

    for feed in feeds:
        name = feed.get("name", "未命名")
        url = feed.get("url", "").strip()
        role = feed.get("role", "common")
        if not url:
            continue
        print(f"正在抓取: {name}...")
        try:
            entries = fetch_feed_entries(url, max_entries=max_entries_per_feed)
        except Exception as e:
            report += f"\n【{name}】\n- 抓取失败: {e}\n"
            continue
        if not entries:
            report += f"\n【{name}】\n- 无可用条目（该时段无匹配文章，或订阅为空）\n"
            continue
        feed_summary = f"\n【{name}】\n"
        for entry in entries:
            raw = f"标题: {entry['title']}\n描述: {(entry['description'] or '')[:300]}"
            insight = purify_content(raw, role) if use_gemini else _truncate_raw(raw, 400)
            feed_summary += f"- {entry['title']}\n  💡 {insight}\n"
        report += feed_summary

    save_path = save_path or os.getenv("GETINFO_DAILY_FILE", "daily_insight.md")
    if save_path:
        try:
            with open(save_path, "a", encoding="utf-8") as f:
                f.write(report + "\n\n")
            print(f"[OK] 简报已追加写入 {save_path}")
        except Exception as e:
            print(f"[ERROR] 写入文件失败: {e}")

    send_telegram = send_telegram if send_telegram is not None else (os.getenv("GETINFO_SEND_TELEGRAM", "1") == "1")
    if send_telegram:
        try:
            from notifier import send_telegram_message
            if send_telegram_message(report):
                print("[OK] 已推送 Telegram")
            else:
                print("[WARN] Telegram 未配置或发送失败")
        except ImportError:
            print("[WARN] 未找到 notifier 模块，跳过 Telegram 推送")

    return report


if __name__ == "__main__":
    generate_morning_report()
