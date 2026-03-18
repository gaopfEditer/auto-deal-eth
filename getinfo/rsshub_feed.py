"""
从 RSSHub 获取资讯，可选 Gemini 提纯后生成简报并推送 Telegram。

环境变量（可选）：
  GEMINI_API_URL: 提纯用 Gemini 聊天接口（如 https://xxx/gemini/chat），不设则不做 AI 提纯
  RSSHUB_BASE:   RSSHub 基础 URL，默认 https://rsshub.app
  RSSHUB_FEEDS:   JSON 数组覆盖默认订阅，格式 [{"name":"","url":"","role":""}]
  GETINFO_DAILY_FILE: 简报追加写入的文件路径，默认 daily_insight.md
  GETINFO_SEND_TELEGRAM: 是否发送简报到 Telegram，默认 1
"""
import os
import json
import requests
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


def get_rss_feeds() -> List[Dict[str, str]]:
    """获取 RSS 订阅列表：优先环境变量 RSSHUB_FEEDS（JSON），否则默认列表。"""
    raw = os.getenv("RSSHUB_FEEDS", "").strip()
    if raw:
        try:
            feeds = json.loads(raw)
            if isinstance(feeds, list) and feeds:
                return feeds
        except json.JSONDecodeError:
            pass
    base = (os.getenv("RSSHUB_BASE") or "https://rsshub.app").strip().rstrip("/")
    return [
        {**f, "url": f["url"].replace("https://rsshub.app", base).replace("http://你的IP:1200", base)}
        for f in DEFAULT_RSS_FEEDS
    ]


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


def fetch_feed_entries(feed_url: str, max_entries: int = 3, timeout: int = 15) -> List[Dict[str, Any]]:
    """拉取单条 RSS 源的前 max_entries 条条目。"""
    if not feedparser:
        raise ImportError("请安装 feedparser: pip install feedparser")
    resp = requests.get(
        feed_url,
        headers={"User-Agent": "getinfo/1.0"},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
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
    从 RSSHub 拉取各源最新条目，可选 Gemini 提纯，生成简报字符串。
    若 save_path 非空则追加写入文件；若 send_telegram 为 True 则发送到 Telegram。
    """
    feeds = feeds or get_rss_feeds()
    api_url = get_gemini_api_url() if use_gemini else None
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
        feed_summary = f"\n【{name}】\n"
        for entry in entries:
            raw = f"标题: {entry['title']}\n描述: {(entry['description'] or '')[:300]}"
            insight = filter_with_gemini(raw, role, api_url=api_url) if api_url else raw[:400]
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
