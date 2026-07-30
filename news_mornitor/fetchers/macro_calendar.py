"""金十风格宏观财经日历 — ≥3★、未来 24h、利好/利空标注。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from news_mornitor.config import (
    HTTP_TIMEOUT_SEC,
    JINSHI_CALENDAR_URL,
    MACRO_AHEAD_HOURS,
    MACRO_MIN_STAR,
    USE_MOCK_FETCHER,
    proxy_url,
)
from news_mornitor.models import MacroBias, MacroEvent, utc_now_iso

logger = logging.getLogger("CryptoPulse.Macro")

try:
    from zoneinfo import ZoneInfo

    _TZ_CN = ZoneInfo("Asia/Shanghai")
except Exception:
    _TZ_CN = timezone(timedelta(hours=8))

# keyword → (bias, reason) 相对加密风险偏好的启发式
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


def _cn_now() -> datetime:
    return datetime.now(_TZ_CN)


def _to_iso_cn(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ_CN)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_calendar(*, min_star: int, ahead_hours: int) -> list[MacroEvent]:
    """生成未来一天内、≥3★ 的演示宏观事件（相对当前时刻滚动）。"""
    now = _cn_now()
    # (hours_ahead, country, title, previous, consensus, star)
    templates: list[tuple[int, str, str, str | None, str | None, int]] = [
        (2, "美国", "初请失业金人数", "21.2万", "21.5万", 2),
        (3, "美国", "核心PCE物价指数年率", "2.8%", "2.7%", 4),
        (5, "美国", "ADP就业人数", "14.5万", "15.0万", 3),
        (8, "欧元区", "CPI同比初值", "2.4%", "2.3%", 3),
        (11, "美国", "美联储主席鲍威尔讲话", None, None, 5),
        (14, "美国", "非农就业人口变动", "18.5万", "20.0万", 5),
        (16, "美国", "失业率", "4.1%", "4.1%", 4),
        (18, "美国", "FOMC利率决议", "5.25%", "5.25%", 5),
        (20, "中国", "LPR报价（1年期）", "3.45%", "3.45%", 3),
        (22, "英国", "央行利率决议", "5.00%", "5.00%", 4),
    ]
    out: list[MacroEvent] = []
    for hours_ahead, country, title, prev, cons, star in templates:
        if star < min_star:
            continue
        offset_h = min(max(hours_ahead, 1), max(ahead_hours - 1, 1))
        dt = now + timedelta(hours=offset_h, minutes=(hours_ahead * 7) % 45)
        if dt < now:
            continue
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
                actual=None,
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
    now: datetime | None = None,
) -> list[MacroEvent]:
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(hours=ahead_hours)
    kept: list[MacroEvent] = []
    for e in events:
        if e.star < min_star:
            continue
        try:
            ts = datetime.fromisoformat(e.publish_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < now or ts > end:
            continue
        bias, reason = infer_bias(e.title)
        e.bias = bias
        e.bias_reason = e.bias_reason or reason
        e.bias_label = _bias_label(bias)
        kept.append(e)
    kept.sort(key=lambda x: x.publish_at)
    return kept


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
            pub = str(pub or utc_now_iso())
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


async def fetch_jinshi_calendar(
    *,
    min_star: int = MACRO_MIN_STAR,
    ahead_hours: int = MACRO_AHEAD_HOURS,
    use_mock: bool | None = None,
) -> list[MacroEvent]:
    """
    拉取宏观日历。默认 mock（金十页多为前端渲染）。
    CRYPTO_PULSE_USE_MOCK=0 时尝试 HTTP，失败回退 mock。
    """
    mock = USE_MOCK_FETCHER if use_mock is None else use_mock
    if mock:
        logger.info("宏观日历 USE_MOCK=1，返回 ≥%s★ 未来 %sh", min_star, ahead_hours)
        return _mock_calendar(min_star=min_star, ahead_hours=ahead_hours)

    import aiohttp

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://rili.jin10.com/",
    }
    try:
        async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
            async with session.get(
                JINSHI_CALENDAR_URL,
                timeout=timeout,
                proxy=proxy_url(),
            ) as resp:
                if resp.status != 200:
                    logger.warning("金十日历 HTTP %s，回退 mock", resp.status)
                    return _mock_calendar(min_star=min_star, ahead_hours=ahead_hours)
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "json" not in ctype:
                    logger.warning("金十返回非 JSON，回退 mock")
                    return _mock_calendar(min_star=min_star, ahead_hours=ahead_hours)
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning("金十日历拉取失败: %s，回退 mock", e)
        return _mock_calendar(min_star=min_star, ahead_hours=ahead_hours)

    filtered = filter_upcoming(
        _parse_jinshi_json(data), min_star=min_star, ahead_hours=ahead_hours
    )
    if not filtered:
        logger.warning("金十解析后无 ≥%s★ 事件，回退 mock", min_star)
        return _mock_calendar(min_star=min_star, ahead_hours=ahead_hours)
    return filtered
