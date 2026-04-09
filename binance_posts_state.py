"""
Square 关注流帖子：12 小时滚动窗口、状态持久化、新帖提示、Gemini 多空判断。

状态文件默认与 --out 同目录下的 binance_posts_state.json。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

TZ_BEIJING = ZoneInfo("Asia/Shanghai")

POST_RETENTION_HOURS = 12
DEFAULT_STATE_BASENAME = "binance_posts_state.json"


def _dt_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_published_to_dt(post: Dict[str, Any], ref_now: datetime) -> Optional[datetime]:
    """
    从帖子字段解析「发帖时间」为 UTC，用于 12 小时窗口。
    优先 published_iso（time[datetime]），其次 time_label / time 的中文相对时间。
    """
    iso = (post.get("published_iso") or "").strip()
    if iso:
        try:
            t = iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return _dt_utc(dt)
        except ValueError:
            pass
    label = (post.get("time_label") or post.get("time") or "").strip()
    if label:
        dt = _parse_zh_time_label(label, ref_now)
        if dt:
            return _dt_utc(dt)
    return None


def _parse_zh_time_label(label: str, ref_now: datetime) -> Optional[datetime]:
    """
    解析相对发帖时间（相对 ref_now，北京日历）。
    支持：3小时前 / 3小时（无前缀，币安常见）/ 12分钟 / 3秒 / 英文 hours ago 等。
    """
    s = (label or "").strip()
    if not s:
        return None
    ref = ref_now.astimezone(TZ_BEIJING)
    if "刚刚" in s or s == "现在":
        return ref

    # 币安 create-time：「4月10日」类（至少跨日；12 小时窗口会筛掉）
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = ref.year
        try:
            return datetime(y, mo, d, 12, 0, tzinfo=TZ_BEIJING)
        except ValueError:
            try:
                return datetime(y - 1, mo, d, 12, 0, tzinfo=TZ_BEIJING)
            except ValueError:
                pass

    # 英文（币安可能随语言显示）
    m = re.search(r"(\d+)\s*(?:hours?|hrs?)\s*ago", s, re.I)
    if m:
        return ref - timedelta(hours=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:minutes?|mins?)\s*ago", s, re.I)
    if m:
        return ref - timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:seconds?|secs?)\s*ago", s, re.I)
    if m:
        return ref - timedelta(seconds=int(m.group(1)))

    # 组合：3小时12分钟前
    m = re.search(r"(\d+)\s*小时\s*(\d+)\s*分钟前", s)
    if m:
        return ref - timedelta(
            hours=int(m.group(1)), minutes=int(m.group(2))
        )
    m = re.search(r"(\d+)\s*小时\s*(\d+)\s*分钟\s*(\d+)\s*秒前", s)
    if m:
        return ref - timedelta(
            hours=int(m.group(1)),
            minutes=int(m.group(2)),
            seconds=int(m.group(3)),
        )
    # 「3小时12分钟」无「前」（须在单纯 N小时 之前匹配，避免吃掉「1小时2分钟前」）
    m = re.search(r"(\d+)\s*小时\s*(\d+)\s*分钟(?!前)", s)
    if m:
        return ref - timedelta(
            hours=int(m.group(1)), minutes=int(m.group(2))
        )
    m = re.search(r"(\d+)\s*分钟\s*(\d+)\s*秒(?!前)", s)
    if m:
        return ref - timedelta(
            minutes=int(m.group(1)), seconds=int(m.group(2))
        )

    # 带「前」
    m = re.search(r"(\d+)\s*秒前", s)
    if m:
        return ref - timedelta(seconds=int(m.group(1)))
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return ref - timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        return ref - timedelta(hours=int(m.group(1)))
    m = re.search(r"(\d+)\s*天前", s)
    if m:
        return ref - timedelta(days=int(m.group(1)))

    # 不带「前」：仅「3小时」「12分钟」单独出现（若后面还跟「分钟」则已由组合规则处理）
    m = re.search(r"(\d+)\s*小时(?!前)(?!\s*\d+\s*分钟)", s)
    if m:
        return ref - timedelta(hours=int(m.group(1)))
    m = re.search(r"(\d+)\s*分钟(?!前)(?!\s*\d+\s*秒)", s)
    if m:
        return ref - timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d+)\s*秒(?!前)", s)
    if m:
        return ref - timedelta(seconds=int(m.group(1)))
    if "昨天" in s:
        m2 = re.search(r"(\d{1,2})\s*:\s*(\d{2})", s)
        d = ref.date() - timedelta(days=1)
        if m2:
            return datetime(
                d.year,
                d.month,
                d.day,
                int(m2.group(1)),
                int(m2.group(2)),
                tzinfo=TZ_BEIJING,
            )
        return datetime(d.year, d.month, d.day, 12, 0, tzinfo=TZ_BEIJING)
    if "前天" in s:
        d = ref.date() - timedelta(days=2)
        m2 = re.search(r"(\d{1,2})\s*:\s*(\d{2})", s)
        if m2:
            return datetime(
                d.year,
                d.month,
                d.day,
                int(m2.group(1)),
                int(m2.group(2)),
                tzinfo=TZ_BEIJING,
            )
        return datetime(d.year, d.month, d.day, 12, 0, tzinfo=TZ_BEIJING)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4):
            H, Mi = int(m.group(4)), int(m.group(5))
            return datetime(y, mo, d, H, Mi, tzinfo=TZ_BEIJING)
        return datetime(y, mo, d, 12, 0, tzinfo=TZ_BEIJING)
    m = re.match(r"^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", s)
    if m:
        mo, d, H, Mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        y = ref.year
        return datetime(y, mo, d, H, Mi, tzinfo=TZ_BEIJING)
    return None


def enrich_post_published_fields(post: Dict[str, Any], ref_now: datetime) -> None:
    """写入 published_at（北京时间可读串）；解析失败则置空。"""
    dt = parse_published_to_dt(post, ref_now)
    if dt:
        post["published_at"] = _format_beijing(dt.astimezone(TZ_BEIJING))
    else:
        post["published_at"] = ""


def filter_posts_by_published_age(
    posts: List[Dict[str, Any]],
    hours: int,
    ref_now: datetime,
) -> List[Dict[str, Any]]:
    """只保留发帖时间在 [now-hours, now] 内的帖子；无法解析时间的丢弃；置顶但时间过旧的一并丢弃。"""
    cutoff = _dt_utc(ref_now) - timedelta(hours=hours)
    out: List[Dict[str, Any]] = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        dt = parse_published_to_dt(p, ref_now)
        if dt is None:
            continue
        if _dt_utc(dt) < cutoff:
            continue
        out.append(p)
    return out


def _published_dt_for_record(rec: Dict[str, Any], ref_now: datetime) -> Optional[datetime]:
    """状态条目中取发帖时刻（published_iso / time_label / published_at 字符串）。"""
    dt = parse_published_to_dt(rec, ref_now)
    if dt is not None:
        return dt
    pa = (rec.get("published_at") or "").strip()
    if pa and "北京时间" in pa:
        t2 = re.sub(r"\s*北京时间\s*$", "", pa).strip()
        try:
            naive = datetime.strptime(t2, "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=TZ_BEIJING)
        except ValueError:
            pass
    return None


def default_posts_state_path(out_json_path: str) -> str:
    p = Path(out_json_path).resolve()
    return str(p.parent / DEFAULT_STATE_BASENAME)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """解析存储的时间：支持「YYYY-MM-DD HH:MM:SS 北京时间」及旧版 UTC ISO（Z）。"""
    if not s or not str(s).strip():
        return None
    t = str(s).strip()
    if "北京时间" in t:
        t2 = re.sub(r"\s*北京时间\s*$", "", t).strip()
        try:
            naive = datetime.strptime(t2, "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=TZ_BEIJING)
        except ValueError:
            pass
    if t.endswith("Z"):
        t = t.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_beijing(dt: datetime) -> str:
    """统一为易读北京时间：2026-04-10 08:34:28 北京时间"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(TZ_BEIJING)
    return local.strftime("%Y-%m-%d %H:%M:%S") + " 北京时间"


def beijing_time_str(dt: Optional[datetime] = None) -> str:
    """当前或指定 UTC/任意时区时刻，输出北京时间字符串。"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return _format_beijing(dt)


def _direction_zh(direction: str) -> str:
    m = {
        "long": "做多",
        "short": "做空",
        "neutral": "中性",
        "unclear": "不明",
    }
    return m.get((direction or "").lower(), direction or "不明")


def _load_state(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {"version": 1, "posts": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "posts": {}}
        posts = data.get("posts")
        if not isinstance(posts, dict):
            posts = {}
        return {"version": 1, "posts": posts}
    except Exception:
        return {"version": 1, "posts": {}}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def process_watchlist_posts(
    result: Dict[str, Any],
    out_json_path: str,
    state_path: Optional[str] = None,
    *,
    skip_gemini: bool = False,
) -> Dict[str, Any]:
    """
    合并本次抓取的 latest_posts 与持久化状态：
    - 以**帖子发帖时间**为准保留 POST_RETENTION_HOURS 小时内；剔除无法解析时间及超期帖（含久远置顶）；
    - 新出现的 href 写入 post_alerts 并提示；对**新帖**调用 Gemini；
    - 不再维护「首次/最后一次发现时间」。
    """
    spath = state_path or default_posts_state_path(out_json_path)
    state = _load_state(spath)
    posts_map: Dict[str, Any] = state.get("posts") or {}

    scraped = result.get("scraped_at")
    now = _parse_iso(scraped) if scraped else _utc_now()

    cutoff = _dt_utc(now) - timedelta(hours=POST_RETENTION_HOURS)
    removed = 0
    to_del: List[str] = []
    for href, rec in list(posts_map.items()):
        if not isinstance(rec, dict):
            to_del.append(href)
            continue
        pdt = _published_dt_for_record(rec, now)
        if pdt is None or _dt_utc(pdt) < cutoff:
            to_del.append(href)
    for href in to_del:
        posts_map.pop(href, None)
        removed += 1

    incoming: List[Dict[str, Any]] = list(
        (result.get("watchlist") or {}).get("latest_posts") or []
    )
    previous_hrefs = set(posts_map.keys())

    alerts: List[Dict[str, Any]] = []

    from gemini_analyzer import classify_square_post_direction

    for p in incoming:
        if not isinstance(p, dict):
            continue
        href = (p.get("href") or "").strip()
        if not href or "/square/post/" not in href.lower():
            continue
        enrich_post_published_fields(p, now)
        title = (p.get("title") or "")[:2000]
        raw = (p.get("raw") or "")[:12000]
        author = (p.get("author") or "")[:500]
        slug = (p.get("author_slug") or "")[:200]
        tm = (p.get("time") or "")[:80]
        pub_at = (p.get("published_at") or "")[:80]
        p_iso = (p.get("published_iso") or "")[:80]
        t_label = (p.get("time_label") or "")[:120]
        is_pin = bool(p.get("is_pinned"))

        if href in posts_map:
            rec = posts_map[href]
            rec["title"] = title
            rec["raw"] = raw
            rec["author"] = author
            rec["author_slug"] = slug
            rec["time"] = tm
            rec["published_at"] = pub_at
            rec["published_iso"] = p_iso
            rec["time_label"] = t_label
            rec["is_pinned"] = is_pin
            imgs = (rec.get("image_urls") or []) + (p.get("image_urls") or [])
            rec["image_urls"] = list(dict.fromkeys(imgs))[:24]
            if p.get("saved_image_paths"):
                rec["saved_image_paths"] = p.get("saved_image_paths")
        else:
            rec = {
                "href": href,
                "published_at": pub_at,
                "published_iso": p_iso,
                "time_label": t_label,
                "is_pinned": is_pin,
                "title": title,
                "raw": raw,
                "author": author,
                "author_slug": slug,
                "time": tm,
                "image_urls": list(dict.fromkeys(p.get("image_urls") or []))[:24],
                "saved_image_paths": p.get("saved_image_paths") or [],
                "gemini_direction": None,
                "gemini_confidence": None,
                "gemini_reason": None,
                "gemini_bias_zh": None,
            }
            posts_map[href] = rec
            previous_hrefs.add(href)

            g: Optional[Dict[str, Any]] = None
            if not skip_gemini:
                print(
                    f"[posts_state] 新帖 — 请求 Gemini 判断方向: {title[:60]}..."
                )
                g = classify_square_post_direction(title, raw, author=author)
            if g:
                d = str(g.get("direction", "unclear")).lower()
                rec["gemini_direction"] = d
                rec["gemini_confidence"] = g.get("confidence")
                rec["gemini_reason"] = g.get("reason")
                rec["gemini_bias_zh"] = _direction_zh(d)
            elif not skip_gemini:
                rec["gemini_direction"] = "unclear"
                rec["gemini_bias_zh"] = "不明"

            alerts.append(
                {
                    "type": "new_post",
                    "href": href,
                    "published_at": rec.get("published_at"),
                    "title": title[:500],
                    "gemini": {
                        "direction": rec.get("gemini_direction"),
                        "bias_zh": rec.get("gemini_bias_zh"),
                        "confidence": rec.get("gemini_confidence"),
                        "reason": rec.get("gemini_reason"),
                    },
                }
            )
            print(
                "\n"
                + "=" * 56
                + "\n[新帖信号] "
                + (rec.get("gemini_bias_zh") or "（未分类）")
                + "\n"
                + f"  发帖时间: {pub_at or t_label or '未知'}\n"
                + f"  链接: {href}\n"
                + f"  标题: {title[:120]}{'…' if len(title) > 120 else ''}\n"
                + (
                    f"  Gemini: {rec.get('gemini_bias_zh')} — {rec.get('gemini_reason')}\n"
                    if rec.get("gemini_reason")
                    else ""
                )
                + "=" * 56
                + "\n"
            )

    # 输出列表：按发帖时间新到旧
    merged: List[Dict[str, Any]] = []
    for href, rec in posts_map.items():
        if not isinstance(rec, dict):
            continue
        merged.append(
            {
                "author": rec.get("author", ""),
                "author_slug": rec.get("author_slug", ""),
                "href": href,
                "raw": rec.get("raw", ""),
                "time": rec.get("time", ""),
                "title": rec.get("title", ""),
                "published_at": rec.get("published_at", ""),
                "published_iso": rec.get("published_iso", ""),
                "time_label": rec.get("time_label", ""),
                "is_pinned": rec.get("is_pinned", False),
                "image_urls": rec.get("image_urls") or [],
                "saved_image_paths": rec.get("saved_image_paths") or [],
                "gemini_direction": rec.get("gemini_direction"),
                "gemini_bias_zh": rec.get("gemini_bias_zh"),
                "gemini_confidence": rec.get("gemini_confidence"),
                "gemini_reason": rec.get("gemini_reason"),
            }
        )
    merged.sort(
        key=lambda x: _published_dt_for_record(x, now)
        or datetime(1970, 1, 1, tzinfo=TZ_BEIJING),
        reverse=True,
    )

    wl = result.setdefault("watchlist", {})
    wl["latest_posts"] = merged
    wl["post_alerts"] = alerts
    wl["posts_state_file"] = spath
    wl["posts_retention_hours"] = POST_RETENTION_HOURS
    wl["posts_pruned_count"] = removed

    state["posts"] = posts_map
    state["updated_at"] = _format_beijing(now)
    _save_state(spath, state)

    if removed:
        print(
            f"[posts_state] 已按发帖时间剔除超过 {POST_RETENTION_HOURS} 小时的记录: {removed} 条"
        )
    print(
        f"[posts_state] 窗口内帖子 {len(merged)} 条，新帖信号 {len(alerts)} 条，状态已写入 {spath}"
    )

    return result
