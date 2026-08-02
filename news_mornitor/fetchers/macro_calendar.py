"""宏观财经日历 — 优先 AkShare 华尔街见闻（与 getinfo/calendar_akshare 同源），金十 HTTP 仅作兜底。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from news_mornitor.config import (
    HTTP_TIMEOUT_SEC,
    JINSHI_CALENDAR_URL,
    MACRO_AHEAD_HOURS,
    MACRO_BEHIND_HOURS,
    MACRO_MIN_STAR,
    MACRO_TZ,
    USE_MOCK_FETCHER,
    proxy_url,
)
from news_mornitor.models import MacroBias, MacroEvent, utc_now_iso

logger = logging.getLogger("CryptoPulse.Macro")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    _TZ_CN = ZoneInfo(MACRO_TZ)
except Exception:
    _TZ_CN = ZoneInfo("Asia/Shanghai")

# 华尔街见闻 1～3 星 → 前端金十风格 1～5 星
_WSCN_TO_JIN10_STAR = {3: 5, 2: 3, 1: 1}

_BIAS_RULES: list[tuple[list[str], MacroBias, str]] = [
    (["降息", "利率决议", "鸽派", "QE", "量化宽松", "资产负债表"], MacroBias.BULLISH, "宽松预期 → 风险偏好抬升"),
    (["加息", "鹰派", "缩表", "QT", "紧缩"], MacroBias.BEARISH, "紧缩预期 → 美元承压风险资产"),
    (["CPI", "PCE", "通胀", "PPI"], MacroBias.BEARISH, "通胀数据偏强常压制降息预期"),
    (["非农", "失业率", "初请", "就业"], MacroBias.NEUTRAL, "就业数据双向解读，关注超预期方向"),
    (["GDP", "零售销售", "ISM", "PMI"], MacroBias.NEUTRAL, "增长数据影响利率路径，方向待确认"),
    (["FOMC", "鲍威尔", "Fed", "美联储", "LPR"], MacroBias.NEUTRAL, "政策节点驱动波动，方向看结果"),
]


def infer_bias(title: str) -> tuple[MacroBias, str]:
    t = title or ""
    for keys, bias, reason in _BIAS_RULES:
        if any(k.lower() in t.lower() if k.isascii() else k in t for k in keys):
            return bias, reason
    return MacroBias.NEUTRAL, "影响路径不明确，观望为主"


def _bias_label(bias: MacroBias) -> str:
    if bias == MacroBias.BULLISH:
        return "利好"
    if bias == MacroBias.BEARISH:
        return "利空"
    return "中性"


def _event_id(title: str, publish_at: str, country: str) -> str:
    raw = f"{country}|{publish_at}|{title}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:16]


def cn_now() -> datetime:
    return datetime.now(_TZ_CN)


def _to_iso_cn(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ_CN)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_beijing_iso(iso_utc: str) -> str:
    try:
        ts = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return iso_utc
    return ts.astimezone(_TZ_CN).isoformat(timespec="minutes")


def _mock_calendar(
    *,
    min_star: int,
    ahead_hours: int,
    behind_hours: int,
) -> list[MacroEvent]:
    now = cn_now()
    templates: list[tuple[int, str, str, str | None, str | None, int]] = [
        (-68, "美国", "核心PCE物价指数年率（前）", "2.9%", "2.8%", 4),
        (-52, "欧元区", "CPI同比终值", "2.5%", "2.4%", 3),
        (-8, "美国", "非农就业人口变动（前）", "17.5万", "19.0万", 5),
        (6, "美国", "核心PCE物价指数年率", "2.8%", "2.7%", 4),
        (48, "美国", "非农就业人口变动", "18.5万", "20.0万", 5),
        (62, "美国", "FOMC利率决议", "5.25%", "5.25%", 5),
    ]
    out: list[MacroEvent] = []
    ahead_cap = max(ahead_hours, 1)
    behind_cap = max(behind_hours, 0)
    for hours_off, country, title, prev, cons, star in templates:
        if star < min_star:
            continue
        if hours_off >= 0:
            offset_h = min(hours_off, ahead_cap - 1) if ahead_cap > 1 else hours_off
        else:
            offset_h = max(hours_off, -(behind_cap - 1) if behind_cap > 1 else hours_off)
        dt = now + timedelta(hours=offset_h, minutes=(abs(hours_off) * 7) % 45)
        bias, reason = infer_bias(title)
        pub = _to_iso_cn(dt)
        out.append(
            MacroEvent(
                id=_event_id(title, pub, country),
                title=title,
                country=country,
                star=star,
                publish_at=pub,
                previous=prev,
                consensus=cons,
                actual=("已公布" if hours_off < 0 else None),
                bias=bias,
                bias_label=_bias_label(bias),
                bias_reason=reason,
                source="jinshi_mock",
            )
        )
    out.sort(key=lambda e: e.publish_at)
    return out


def filter_upcoming(
    events: list[MacroEvent],
    *,
    min_star: int = MACRO_MIN_STAR,
    ahead_hours: int = MACRO_AHEAD_HOURS,
    behind_hours: int = MACRO_BEHIND_HOURS,
    now: datetime | None = None,
) -> list[MacroEvent]:
    now_cn = now.astimezone(_TZ_CN) if now is not None else cn_now()
    start = now_cn - timedelta(hours=max(behind_hours, 0))
    end = now_cn + timedelta(hours=max(ahead_hours, 0))
    kept: list[MacroEvent] = []
    for e in events:
        if e.star < min_star:
            continue
        try:
            ts = datetime.fromisoformat(e.publish_at.replace("Z", "+00:00")).astimezone(_TZ_CN)
        except ValueError:
            continue
        if ts < start or ts > end:
            continue
        bias, reason = infer_bias(e.title)
        e.bias = bias
        e.bias_reason = e.bias_reason or reason
        e.bias_label = _bias_label(bias)
        kept.append(e)
    kept.sort(key=lambda x: x.publish_at)
    return kept


def _parse_dt_cn(value: Any) -> datetime | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        try:
            value = value.to_pydatetime()
        except Exception:
            pass
    if isinstance(value, datetime):
        return value.replace(tzinfo=_TZ_CN) if value.tzinfo is None else value.astimezone(_TZ_CN)
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=_TZ_CN)
        except ValueError:
            continue
    try:
        ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return ts.astimezone(_TZ_CN) if ts.tzinfo else ts.replace(tzinfo=_TZ_CN)
    except ValueError:
        return None


def _cell(row: Any, *names: str) -> Any:
    for n in names:
        try:
            if hasattr(row, "get") and n in row and row.get(n) is not None:
                return row.get(n)
        except Exception:
            pass
        try:
            if n in row.index:
                v = row[n]
                if v is not None and str(v) != "nan":
                    return v
        except Exception:
            pass
    return None


def _wscn_star_to_jin10(raw: Any) -> int:
    """华尔街见闻重要度 / 「星级」文案 → 金十 1～5 星。"""
    from getinfo.calendar_akshare import _normalize_wscn_star

    n = _normalize_wscn_star(raw)
    if n is not None:
        return int(_WSCN_TO_JIN10_STAR.get(n, 5 if n >= 3 else n))

    s = str(raw or "").strip()
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return 0
    # _add_star_column 产出：3星(5星·高) / 2星(3-4星·中) / 1星(低)
    if "高" in s:
        return 5
    if "中" in s:
        return 3
    if "低" in s:
        return 1
    try:
        n2 = int(float(s))
    except (TypeError, ValueError):
        return 0
    return int(_WSCN_TO_JIN10_STAR.get(n2, 5 if n2 >= 3 else n2))


def _df_to_macro_events(df: Any) -> list[MacroEvent]:
    out: list[MacroEvent] = []
    if df is None or getattr(df, "empty", True):
        return out
    for _, row in df.iterrows():
        title = str(_cell(row, "事件", "event", "title", "name") or "").strip()
        if not title or title.lower() == "nan":
            continue
        country = str(_cell(row, "地区", "country", "region") or "").strip()
        if country.lower() == "nan":
            country = ""
        # 华尔街见闻实际列名是「重要性」（不是「重要度」）
        star = _wscn_star_to_jin10(
            _cell(row, "重要性", "重要度", "importance", "星级")
        )
        dt = _parse_dt_cn(_cell(row, "时间", "date", "日期", "datetime"))
        if dt is None:
            continue
        pub = _to_iso_cn(dt)
        prev = _cell(row, "前值", "previous")
        cons = _cell(row, "预期", "预测", "consensus", "forecast")
        actual = _cell(row, "今值", "公布", "actual")

        def _s(v: Any) -> str | None:
            if v is None:
                return None
            s = str(v).strip()
            if not s or s.lower() in ("nan", "none", "-", "—"):
                return None
            return s

        bias, reason = infer_bias(title)
        out.append(
            MacroEvent(
                id=_event_id(title, pub, country),
                title=title,
                country=country,
                star=star,
                publish_at=pub,
                previous=_s(prev),
                consensus=_s(cons),
                actual=_s(actual),
                bias=bias,
                bias_label=_bias_label(bias),
                bias_reason=reason,
                source="wallstreetcn_akshare",
            )
        )
    return out


def _fetch_akshare_calendar_sync(
    *,
    ahead_hours: int,
    behind_hours: int,
) -> list[MacroEvent]:
    """同步拉取：复用 getinfo.calendar_akshare（华尔街见闻 macro_info_ws）。"""
    from getinfo.calendar_akshare import _add_star_column, _fetch_calendar_df, _normalize_wscn_star

    today = cn_now().date()
    behind_days = max(1, int(behind_hours / 24) + 1)
    ahead_days = max(1, int(ahead_hours / 24) + 1)
    start = today - timedelta(days=behind_days)
    total_days = behind_days + ahead_days + 1
    df = _fetch_calendar_df(days=total_days, start_date=start)
    if df is None or df.empty:
        logger.warning("AkShare macro_info_ws 无数据（%s 起 %s 天）", start, total_days)
        return []

    cols = list(df.columns)
    imp_col = None
    for name in ("重要性", "重要度", "importance"):
        if name in cols:
            imp_col = name
            break
    if imp_col is None and len(cols) > 3:
        imp_col = cols[3]
    if imp_col is not None:
        df = _add_star_column(df, imp_col)
        star_ser = df[imp_col].map(_normalize_wscn_star)
        # 华尔街 2/3 星 ≈ 金十 ≥3
        df = df.loc[star_ser.fillna(0).isin((2, 3))].copy()

    events = _df_to_macro_events(df)
    logger.info(
        "AkShare 华尔街见闻日历原始 %s 条（窗口 %s～%s）",
        len(events),
        start,
        today + timedelta(days=ahead_days),
    )
    return events


def _parse_jinshi_json(data: Any) -> list[MacroEvent]:
    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for k in ("data", "list", "result", "calendar"):
            if isinstance(data.get(k), list):
                rows = data[k]
                break
    out: list[MacroEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("name") or row.get("title") or row.get("event") or "").strip()
        if not title:
            continue
        star = int(row.get("star") or row.get("importance") or row.get("level") or 0)
        country = str(row.get("country") or row.get("countryName") or row.get("region") or "")
        pub = row.get("pub_time") or row.get("time") or row.get("publish_at") or row.get("date")
        if isinstance(pub, (int, float)):
            pub = datetime.fromtimestamp(
                pub / (1000 if pub > 1e11 else 1), tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            pub_s = str(pub or "").strip()
            if pub_s and "T" not in pub_s and " " in pub_s:
                try:
                    dt = datetime.strptime(pub_s[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_TZ_CN)
                    pub = _to_iso_cn(dt)
                except ValueError:
                    pub = utc_now_iso()
            elif pub_s:
                pub = pub_s if pub_s.endswith("Z") or "+" in pub_s[10:] else pub_s
            else:
                pub = utc_now_iso()
        bias, reason = infer_bias(title)
        out.append(
            MacroEvent(
                id=_event_id(title, pub, country),
                title=title,
                country=country,
                star=star,
                publish_at=pub,
                previous=str(row["previous"]) if row.get("previous") is not None else None,
                consensus=str(row["consensus"]) if row.get("consensus") is not None else None,
                actual=str(row["actual"]) if row.get("actual") is not None else None,
                bias=bias,
                bias_label=_bias_label(bias),
                bias_reason=reason,
                source="jinshi",
            )
        )
    return out


async def _fetch_jinshi_http() -> list[MacroEvent]:
    import aiohttp

    from news_mornitor.config import JINSHI_CALENDAR_URL_FALLBACKS

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://rili.jin10.com/",
    }
    urls = list(dict.fromkeys([JINSHI_CALENDAR_URL, *JINSHI_CALENDAR_URL_FALLBACKS]))
    try:
        async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=timeout, proxy=proxy_url()) as resp:
                        if resp.status != 200:
                            continue
                        text = await resp.text()
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if "json" not in ctype and not text.strip().startswith(("{", "[")):
                            continue
                        return _parse_jinshi_json(json.loads(text))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("金十兜底失败: %s", e)
    return []


async def fetch_jinshi_calendar(
    *,
    min_star: int = MACRO_MIN_STAR,
    ahead_hours: int = MACRO_AHEAD_HOURS,
    behind_hours: int = MACRO_BEHIND_HOURS,
    use_mock: bool | None = None,
) -> list[MacroEvent]:
    """
    拉取宏观日历。
    优先：getinfo/calendar_akshare（AkShare 华尔街见闻）。
    其次：金十 HTTP。
    """
    mock = USE_MOCK_FETCHER if use_mock is None else use_mock
    if mock:
        logger.info(
            "宏观日历 USE_MOCK=1，返回 ≥%s★ 北京时间 过去%sh～未来%sh",
            min_star,
            behind_hours,
            ahead_hours,
        )
        return _mock_calendar(
            min_star=min_star, ahead_hours=ahead_hours, behind_hours=behind_hours
        )

    events: list[MacroEvent] = []
    try:
        events = await asyncio.to_thread(
            _fetch_akshare_calendar_sync,
            ahead_hours=ahead_hours,
            behind_hours=behind_hours,
        )
    except ImportError as e:
        logger.warning("AkShare/getinfo 不可用: %s；尝试金十 HTTP", e)
    except Exception as e:
        logger.warning("AkShare 宏观日历失败: %s；尝试金十 HTTP", e)

    if not events:
        events = await _fetch_jinshi_http()

    filtered = filter_upcoming(
        events,
        min_star=min_star,
        ahead_hours=ahead_hours,
        behind_hours=behind_hours,
    )
    if not filtered:
        logger.warning("宏观日历过滤后无 ≥%s★ 事件", min_star)
        return []
    logger.info("宏观日历可用 %s 条（≥%s★，源=%s）", len(filtered), min_star, filtered[0].source)
    return filtered
