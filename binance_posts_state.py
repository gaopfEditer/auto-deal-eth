"""
Square 关注流帖子：24 小时滚动窗口、状态持久化、新帖提示、Gemini 多空判断。

状态文件默认与 --out 同目录下的 binance_posts_state.json。
posts 结构为 { 关注者 author_slug: { 帖子 href: 记录 } }；旧版扁平 { href: 记录 } 会在加载时自动迁移。
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from gemini_analyzer import extract_json_from_gemini_text

try:
    import requests
except ModuleNotFoundError:
    requests = None

TZ_BEIJING = ZoneInfo("Asia/Shanghai")

# 默认保留最近 24 小时（可通过环境变量覆盖）
POST_RETENTION_HOURS = int(os.getenv("POST_RETENTION_HOURS", "24").strip() or "24")
DEFAULT_STATE_BASENAME = "binance_posts_state.json"
LOCAL_CHAT_ANALYZE_URL = "http://127.0.0.1:3860/chat"
LOCAL_CHAT_ANALYZE_ROLE = os.getenv("LOCAL_CHAT_ANALYZE_ROLE", "binance_square").strip() or "binance_square"
LOCAL_CHAT_ANALYZE_TIMEOUT_SEC = 45
# 默认不并发；后续切本地模型时可开启并发
LOCAL_CHAT_ANALYZE_CONCURRENT = (
    os.getenv("LOCAL_CHAT_ANALYZE_CONCURRENT", "false").strip().lower() == "true"
)
# 并发开启时的 worker 数（建议小值）
LOCAL_CHAT_ANALYZE_WORKERS = int(
    os.getenv("LOCAL_CHAT_ANALYZE_WORKERS", "3").strip() or "3"
)

# 发帖时间不得晚于「当前」超过该容差（避免时钟误差误判）
_PUBLISHED_MAX_FUTURE_SKEW = timedelta(minutes=2)

# 无 author_slug 时的分桶键（便于与真实 slug 区分）
_POSTS_BUCKET_UNKNOWN = "_unknown"


def _dt_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _reject_future_published_dt(
    dt: Optional[datetime], ref_now: datetime
) -> Optional[datetime]:
    """发帖时间不得晚于当前（未来时间视为无效，避免写入错误 published_at）。"""
    if dt is None:
        return None
    if _dt_utc(dt) <= _dt_utc(ref_now) + _PUBLISHED_MAX_FUTURE_SKEW:
        return dt
    return None


def parse_published_to_dt(post: Dict[str, Any], ref_now: datetime) -> Optional[datetime]:
    """
    从帖子字段解析「发帖时间」为 UTC，用于 24 小时窗口。
    优先 published_iso（time[datetime]），其次 time_label / time 的中文相对时间。
    """
    iso = (post.get("published_iso") or "").strip()
    if iso:
        try:
            t = iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return _reject_future_published_dt(_dt_utc(dt), ref_now)
        except ValueError:
            pass
    label = (post.get("time_label") or post.get("time") or "").strip()
    if label:
        dt = _parse_zh_time_label(label, ref_now)
        if dt:
            return _reject_future_published_dt(_dt_utc(dt), ref_now)
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

    # 完整日历：2025年5月22日 / 2024年8月30日（须优先于下方仅「M月D日」规则，否则会误用 ref.year）
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d, 12, 0, tzinfo=TZ_BEIJING)
        except ValueError:
            pass

    # 币安 create-time：「4月10日」类（无年份时用 ref 年；若落在未来则退回上一年）
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        for y in (ref.year, ref.year - 1):
            try:
                dt = datetime(y, mo, d, 12, 0, tzinfo=TZ_BEIJING)
            except ValueError:
                continue
            if dt <= ref:
                return dt

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
    """状态条目中取发帖时刻（优先绝对时间：published_iso/published_at，再回退 time_label）。"""
    iso = (rec.get("published_iso") or "").strip()
    if iso:
        try:
            t = iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out = _reject_future_published_dt(_dt_utc(dt), ref_now)
            if out is not None:
                return out
        except ValueError:
            pass
    pa = (rec.get("published_at") or "").strip()
    if pa and "北京时间" in pa:
        t2 = re.sub(r"\s*北京时间\s*$", "", pa).strip()
        try:
            naive = datetime.strptime(t2, "%Y-%m-%d %H:%M:%S")
            return _reject_future_published_dt(
                naive.replace(tzinfo=TZ_BEIJING), ref_now
            )
        except ValueError:
            pass
    # 绝对时间不可用时，再回退相对时间标签
    dt = parse_published_to_dt(rec, ref_now)
    if dt is not None:
        return dt
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


def _normalize_posts_to_buckets(posts: Any) -> Dict[str, Dict[str, Any]]:
    """
    规范为 { 关注者标识(author_slug): { 帖子 href: 记录 } }。
    兼容旧版扁平结构 { href: 记录 }（按条目的 author_slug 归入桶）。
    """
    if not isinstance(posts, dict) or not posts:
        return {}
    any_key = next(iter(posts.keys()))
    if "/square/post/" in str(any_key):
        out: Dict[str, Dict[str, Any]] = {}
        for href, rec in posts.items():
            if not isinstance(rec, dict):
                continue
            slug = (rec.get("author_slug") or "").strip().lower() or _POSTS_BUCKET_UNKNOWN
            out.setdefault(slug, {})[str(href)] = rec
        return out
    out2: Dict[str, Dict[str, Any]] = {}
    for slug, inner in posts.items():
        if not isinstance(inner, dict):
            continue
        bucket: Dict[str, Any] = {}
        for href, rec in inner.items():
            if isinstance(rec, dict) and "/square/post/" in str(href).lower():
                bucket[str(href)] = rec
        if bucket:
            out2[str(slug)] = bucket
    return out2


def _href_slug_index(buckets: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """href -> 所在桶（slug）。"""
    idx: Dict[str, str] = {}
    for slug, inner in buckets.items():
        if not isinstance(inner, dict):
            continue
        for href in inner:
            idx[href] = slug
    return idx


def _load_state(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {"version": 1, "posts": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "posts": {}}
        posts_raw = data.get("posts")
        posts = _normalize_posts_to_buckets(posts_raw if isinstance(posts_raw, dict) else {})
        out: Dict[str, Any] = {"version": int(data.get("version", 1)), "posts": posts}
        if "updated_at" in data:
            out["updated_at"] = data["updated_at"]
        return out
    except Exception:
        return {"version": 1, "posts": {}}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _pick_first_existing_file(paths: List[str]) -> str:
    for p in paths:
        pp = (p or "").strip()
        if pp and os.path.isfile(pp):
            return pp
    return ""


def _signal_analysis_done(rec: Dict[str, Any]) -> bool:
    """是否已完成且成功分析（用于下次跳过重复请求）。"""
    if bool(rec.get("signal_analyzed_ok")):
        return True
    # 兼容旧数据：没有标志位时，按已有成功结果字段推断
    if rec.get("signal_error") is None and rec.get("signal_star") is not None:
        return True
    return False


def _collect_record_image_paths(rec: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for p in list(rec.get("saved_image_paths") or []):
        pp = str(p or "").strip()
        if pp:
            out.append(pp)
    s = str(rec.get("signal_image_used") or "").strip()
    if s:
        out.append(s)
    return out


def _iter_all_record_image_paths(posts_map: Dict[str, Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for inner in posts_map.values():
        if not isinstance(inner, dict):
            continue
        for rec in inner.values():
            if not isinstance(rec, dict):
                continue
            out.extend(_collect_record_image_paths(rec))
    return out


def _cleanup_removed_post_images(candidate_paths: List[str], remaining_paths: List[str]) -> int:
    """
    删除已被剔除帖子关联的本地截图文件：
    - 只处理路径里包含 square_post_images 的文件
    - 若文件仍被其他帖子引用，则不删
    """
    if not candidate_paths:
        return 0
    remaining = {os.path.abspath(p) for p in remaining_paths if p}
    deleted = 0
    for p in candidate_paths:
        pp = str(p or "").strip()
        if not pp:
            continue
        ap = os.path.abspath(pp)
        low = ap.replace("\\", "/").lower()
        if "/square_post_images/" not in low:
            continue
        if ap in remaining:
            continue
        try:
            if os.path.isfile(ap):
                os.remove(ap)
                deleted += 1
                # 顺带清理空目录（最多向上 3 层，避免误删更高层）
                parent = os.path.dirname(ap)
                for _ in range(3):
                    if not parent:
                        break
                    name = os.path.basename(parent).lower()
                    if name == "square_post_images":
                        break
                    if os.path.isdir(parent) and not os.listdir(parent):
                        os.rmdir(parent)
                        parent = os.path.dirname(parent)
                    else:
                        break
        except Exception:
            continue
    return deleted


def _analyze_post_via_local_api(
    href: str, title: str, raw: str, image_path: str
) -> Dict[str, Any]:
    """
    调本地接口分析帖子（用于交易信号）。
    返回结构始终包含 ok 字段，成功时含 data。
    """
    if requests is None:
        return {"ok": False, "error": "missing_requests"}
    msg = (
        "给出建议\n"
        f"标题: {(title or '')[:500]}\n"
        f"正文: {(raw or '')[:8000]}\n"
        f"链接: {href}"
    )
    print(
        f"[posts_state][signal_api] 请求开始 role={LOCAL_CHAT_ANALYZE_ROLE} "
        f"url={LOCAL_CHAT_ANALYZE_URL} timeout={LOCAL_CHAT_ANALYZE_TIMEOUT_SEC}s href={href}"
    )
    print("[posts_state][signal_api] 请求模式: text_only（不上传文件）")
    try:
        payload = {"role": LOCAL_CHAT_ANALYZE_ROLE, "message": msg}
        r = requests.post(
            LOCAL_CHAT_ANALYZE_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=LOCAL_CHAT_ANALYZE_TIMEOUT_SEC,
        )
        r.raise_for_status()
        obj = r.json() if r.content else {}
        if not isinstance(obj, dict):
            print("[posts_state][signal_api] 返回不是 JSON 对象")
            return {"ok": False, "error": "invalid_json"}
        print(
            "[posts_state][signal_api] 请求成功 "
            f"isSign={obj.get('isSign')} star={obj.get('star')}"
        )
        return {"ok": True, "data": obj}
    except Exception as e:
        print(f"[posts_state][signal_api] 请求失败 href={href} error={e}")
        return {"ok": False, "error": str(e)}


def _normalize_signal_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    适配接口返回：
    1) 直接结构：{"isSign": bool, "content": str, "star": int}
    2) 包裹结构：{"text": "```json ...```"} / {"raw_data":{"text":"..."}}
    返回统一 dict（至少尽量含 isSign/content/star）。
    """
    if not isinstance(data, dict):
        return {}
    if any(k in data for k in ("isSign", "content", "star")):
        return data
    text_candidates: List[str] = []
    t = data.get("text")
    if isinstance(t, str) and t.strip():
        text_candidates.append(t)
    rd = data.get("raw_data")
    if isinstance(rd, dict):
        t2 = rd.get("text")
        if isinstance(t2, str) and t2.strip():
            text_candidates.append(t2)
    for s in text_candidates:
        parsed = extract_json_from_gemini_text(s)
        if isinstance(parsed, dict):
            return parsed
    return data


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
    posts_map: Dict[str, Dict[str, Any]] = _normalize_posts_to_buckets(
        state.get("posts") or {}
    )

    scraped = result.get("scraped_at")
    now = _parse_iso(scraped) if scraped else _utc_now()

    cutoff = _dt_utc(now) - timedelta(hours=POST_RETENTION_HOURS)
    removed = 0
    href_index = _href_slug_index(posts_map)
    to_del: List[Tuple[str, str]] = []
    removed_image_candidates: List[str] = []
    for slug, inner in list(posts_map.items()):
        if not isinstance(inner, dict):
            to_del.append((slug, "__drop_bucket__"))
            continue
        for href, rec in list(inner.items()):
            if not isinstance(rec, dict):
                to_del.append((slug, href))
                continue
            pdt = _published_dt_for_record(rec, now)
            if pdt is None or _dt_utc(pdt) < cutoff:
                to_del.append((slug, href))
    for slug, href in to_del:
        inner = posts_map.get(slug)
        if href == "__drop_bucket__":
            posts_map.pop(slug, None)
            continue
        if isinstance(inner, dict) and href in inner:
            rec_to_drop = inner.get(href)
            if isinstance(rec_to_drop, dict):
                removed_image_candidates.extend(_collect_record_image_paths(rec_to_drop))
            del inner[href]
            href_index.pop(href, None)
            removed += 1
        if isinstance(inner, dict) and not inner:
            posts_map.pop(slug, None)
    removed_images = _cleanup_removed_post_images(
        removed_image_candidates, _iter_all_record_image_paths(posts_map)
    )

    incoming: List[Dict[str, Any]] = list(
        (result.get("watchlist") or {}).get("latest_posts") or []
    )

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
        bucket = (slug or "").strip().lower() or _POSTS_BUCKET_UNKNOWN
        tm = (p.get("time") or "")[:80]
        pub_at = (p.get("published_at") or "")[:80]
        p_iso = (p.get("published_iso") or "")[:80]
        t_label = (p.get("time_label") or "")[:120]
        is_pin = bool(p.get("is_pinned"))

        if href in href_index:
            old_slug = href_index[href]
            rec = posts_map[old_slug][href]
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
            # 保留既有的接口分析字段（后续会统一异步刷新）
            if old_slug != bucket:
                del posts_map[old_slug][href]
                if not posts_map[old_slug]:
                    del posts_map[old_slug]
                posts_map.setdefault(bucket, {})[href] = rec
                href_index[href] = bucket
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
                "signal_is_sign": None,
                "signal_star": None,
                "signal_content": None,
                "signal_raw_data": None,
                "signal_error": None,
                "signal_analyzed_at": None,
                "signal_image_used": None,
                "signal_analyzed_ok": False,
            }
            posts_map.setdefault(bucket, {})[href] = rec
            href_index[href] = bucket

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

    # 文章抓取归档后：异步调用本地接口分析（每篇文章一条任务）
    analyze_jobs: List[Tuple[str, str, Dict[str, Any]]] = []
    analyzed_skip = 0
    for slug_key, inner in posts_map.items():
        if not isinstance(inner, dict):
            continue
        for href, rec in inner.items():
            if not isinstance(rec, dict):
                continue
            if _signal_analysis_done(rec):
                analyzed_skip += 1
                continue
            image_used = _pick_first_existing_file(list(rec.get("saved_image_paths") or []))
            analyze_jobs.append((slug_key, href, {"rec": rec, "image": image_used}))

    analyzed_ok = 0
    analyzed_fail = 0
    if analyze_jobs:
        def _apply_signal_result(slug_key: str, href: str, image_used: str, out: Dict[str, Any]) -> None:
            nonlocal analyzed_ok, analyzed_fail
            rec = posts_map.get(slug_key, {}).get(href)
            if not isinstance(rec, dict):
                return
            rec["signal_analyzed_at"] = beijing_time_str(_utc_now())
            rec["signal_image_used"] = image_used

            if not out.get("ok"):
                rec["signal_error"] = str(out.get("error") or "unknown")
                rec["signal_analyzed_ok"] = False
                analyzed_fail += 1
                print(
                    f"[posts_state][signal_api] 任务失败 href={href} "
                    f"error={rec['signal_error']}"
                )
                return

            data_raw = out.get("data") or {}
            if not isinstance(data_raw, dict):
                rec["signal_error"] = "invalid_response_data"
                rec["signal_analyzed_ok"] = False
                analyzed_fail += 1
                print(
                    f"[posts_state][signal_api] 任务失败 href={href} invalid_response_data"
                )
                return
            data = _normalize_signal_payload(data_raw)
            rec["signal_error"] = None
            rec["signal_analyzed_ok"] = True
            rec["signal_is_sign"] = bool(data.get("isSign"))
            star_raw = data.get("star")
            try:
                rec["signal_star"] = int(star_raw)
            except Exception:
                rec["signal_star"] = 0 if star_raw is None else None
            # 适配实际接口返回：{"isSign": bool, "content": str, "star": int}
            rec["signal_content"] = data.get("content")
            # 若接口未返回 raw_data，保留完整返回对象，便于排查/回放
            rec["signal_raw_data"] = data_raw
            analyzed_ok += 1
            print(
                f"[posts_state][signal_api] 任务成功 href={href} "
                f"isSign={rec.get('signal_is_sign')} star={rec.get('signal_star')}"
            )

        if LOCAL_CHAT_ANALYZE_CONCURRENT:
            workers = max(1, min(8, LOCAL_CHAT_ANALYZE_WORKERS))
            print(
                f"[posts_state][signal_api] 开始并发分析：jobs={len(analyze_jobs)} "
                f"mode=concurrent workers={workers}"
            )
            with ThreadPoolExecutor(max_workers=workers) as ex:
                fut_map = {}
                for slug_key, href, payload in analyze_jobs:
                    rec = payload["rec"]
                    image_used = payload["image"]
                    print(
                        f"[posts_state][signal_api] 提交任务 href={href} "
                        f"image={'Y' if image_used else 'N'} title={str(rec.get('title') or '')[:50]}"
                    )
                    fut = ex.submit(
                        _analyze_post_via_local_api,
                        href,
                        str(rec.get("title") or ""),
                        str(rec.get("raw") or ""),
                        image_used,
                    )
                    fut_map[fut] = (slug_key, href, image_used)
                for fut in as_completed(fut_map):
                    slug_key, href, image_used = fut_map[fut]
                    out = fut.result()
                    _apply_signal_result(slug_key, href, image_used, out)
        else:
            print(
                f"[posts_state][signal_api] 开始串行分析：jobs={len(analyze_jobs)} "
                "mode=sequential"
            )
            for slug_key, href, payload in analyze_jobs:
                rec = payload["rec"]
                image_used = payload["image"]
                print(
                    f"[posts_state][signal_api] 串行执行 href={href} "
                    f"image={'Y' if image_used else 'N'} title={str(rec.get('title') or '')[:50]}"
                )
                out = _analyze_post_via_local_api(
                    href,
                    str(rec.get("title") or ""),
                    str(rec.get("raw") or ""),
                    image_used,
                )
                _apply_signal_result(slug_key, href, image_used, out)

    # 输出列表：按发帖时间新到旧
    merged: List[Dict[str, Any]] = []
    filtered_star0 = 0
    for _slug, inner in posts_map.items():
        if not isinstance(inner, dict):
            continue
        for href, rec in inner.items():
            if not isinstance(rec, dict):
                continue
            star_v = rec.get("signal_star")
            if isinstance(star_v, int) and star_v == 0:
                filtered_star0 += 1
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
                    "signal_is_sign": rec.get("signal_is_sign"),
                    "signal_star": rec.get("signal_star"),
                    "signal_content": rec.get("signal_content"),
                    "signal_raw_data": rec.get("signal_raw_data"),
                    "signal_error": rec.get("signal_error"),
                    "signal_analyzed_at": rec.get("signal_analyzed_at"),
                    "signal_image_used": rec.get("signal_image_used"),
                    "signal_analyzed_ok": rec.get("signal_analyzed_ok"),
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
    wl["posts_pruned_image_files"] = removed_images
    wl["posts_signal_analyzed_ok"] = analyzed_ok
    wl["posts_signal_analyzed_fail"] = analyzed_fail
    wl["posts_signal_analyzed_skip"] = analyzed_skip
    wl["posts_signal_filtered_star0"] = filtered_star0

    state["posts"] = posts_map
    state["updated_at"] = _format_beijing(now)
    _save_state(spath, state)

    if removed:
        print(
            f"[posts_state] 已按发帖时间剔除超过 {POST_RETENTION_HOURS} 小时的记录: {removed} 条"
        )
    if removed_images:
        print(f"[posts_state] 已删除超期帖子关联截图: {removed_images} 个文件")
    print(
        f"[posts_state] 窗口内帖子 {len(merged)} 条，新帖信号 {len(alerts)} 条，状态已写入 {spath}"
    )

    return result
