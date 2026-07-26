"""
promat 提示词加载与拼装（供 publish/signal 服务或本地调试）。

默认路径：prompts/promat/
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

_REPO = Path(__file__).resolve().parent
_PROMAT_DIR = Path(
    os.getenv("PROMAT_PUBLISH_DIR", str(_REPO / "prompts" / "promat"))
).resolve()

_STYLE_FILE = "style_tianya_classic.txt"
_STRATEGY_FILE = "strategy_left_ambush.txt"
_COMPOSE_FILE = "tv_signal_compose.txt"


def promat_dir() -> Path:
    return _PROMAT_DIR


def _read(name: str) -> str:
    p = _PROMAT_DIR / name
    return p.read_text(encoding="utf-8").strip()


def load_style_tianya_classic() -> str:
    return _read(_STYLE_FILE)


def load_strategy_left_ambush() -> str:
    return _read(_STRATEGY_FILE)


def build_tv_signal_compose_prompt(signal_input: str) -> str:
    """将 signal 原文填入 tv_signal_compose 总模板。"""
    tpl = _read(_COMPOSE_FILE)
    return (
        tpl.replace("{{STYLE_TIANYA_CLASSIC}}", load_style_tianya_classic())
        .replace("{{STRATEGY_LEFT_AMBUSH}}", load_strategy_left_ambush())
        .replace("{{SIGNAL_INPUT}}", (signal_input or "").strip())
    )


def high_confidence_threshold() -> int:
    try:
        from config import TV_SIGNAL_HIGH_CONFIDENCE

        return int(TV_SIGNAL_HIGH_CONFIDENCE)
    except Exception:
        return int(os.getenv("TV_SIGNAL_HIGH_CONFIDENCE", "80") or "80")


def normalize_confidence(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, v))


def normalize_trend(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if any(x in s for x in ("多", "long", "Long", "bull", "Bull", "上涨")):
        return "看多"
    if any(x in s for x in ("空", "short", "Short", "bear", "Bear", "下跌")):
        return "看空"
    if any(x in s for x in ("观望", "中性", "wait", "Wait", "neutral")):
        return "观望"
    return s[:16]


def is_high_confidence(polished: Dict[str, Any] | None) -> bool:
    if not isinstance(polished, dict):
        return False
    conf = normalize_confidence(polished.get("confidence"))
    if conf is not None:
        return conf >= high_confidence_threshold()
    try:
        star = int(polished.get("star") or 0)
    except (TypeError, ValueError):
        star = 0
    return star >= 4


def normalize_polished_content(content: Any) -> str:
    """把模型返回的 content 转为易读多行（处理 \\n 转义）。"""
    if content is None:
        return ""
    s = str(content).strip()
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    return s


def format_polished_for_terminal(polished: Dict[str, Any]) -> str:
    """终端展示用：分行 + 趋势/信心 + 星级 + meta。"""
    if not isinstance(polished, dict):
        return str(polished)
    lines = []
    trend = normalize_trend(polished.get("trend"))
    conf = normalize_confidence(polished.get("confidence"))
    star = polished.get("star")
    high = is_high_confidence(polished)
    head_bits = []
    if high:
        head_bits.append("【高信心】")
    if trend:
        head_bits.append(f"趋势={trend}")
    if conf is not None:
        head_bits.append(f"信心={conf}/100")
    if star is not None:
        head_bits.append(f"⭐{star}/5")
    head_bits.append(f"isSign={polished.get('isSign')}")
    lines.append(" · ".join(head_bits))
    lines.append("")
    body = normalize_polished_content(polished.get("content"))
    if body:
        lines.append(body)
    meta = polished.get("meta")
    if isinstance(meta, dict) and meta:
        lines.append("")
        lines.append(
            f"— meta: style={meta.get('style')} strategy={meta.get('strategy')}"
        )
    return "\n".join(lines)


def telegram_caption_from_publish_body(body: Optional[Dict[str, Any]]) -> str:
    """从 publish/signal 响应提取 Telegram 配文（润色正文优先；高信心打标）。"""
    if not isinstance(body, dict) or not body.get("ok"):
        return ""
    polished = body.get("polished")
    if not isinstance(polished, dict):
        return ""
    lines: list[str] = []
    high = is_high_confidence(polished)
    trend = normalize_trend(polished.get("trend"))
    conf = normalize_confidence(polished.get("confidence"))
    star = polished.get("star")
    if high:
        # 发出的担子醒目标记，便于事后验证/对照
        lines.append("【高信心担子】可对照验证")
    head = []
    if trend:
        head.append(f"趋势建议：{trend}")
    if conf is not None:
        head.append(f"信心：{conf}/100")
    if star is not None:
        head.append(f"⭐ {star}/5")
    if head:
        lines.append(" · ".join(head))
    content = normalize_polished_content(polished.get("content"))
    if content:
        lines.append(content)
    return "\n".join(lines).strip()


def describe_publish_response(body: Dict[str, Any]) -> str:
    """从 /api/publish/signal 响应 JSON 提取可读摘要。"""
    if not isinstance(body, dict):
        return str(body)
    parts: list[str] = [f"ok={body.get('ok')}"]
    if body.get("model"):
        parts.append(f"model={body.get('model')}")
    polished = body.get("polished")
    if isinstance(polished, dict):
        return " ".join(parts) + "\n" + format_polished_for_terminal(polished)
    return " ".join(parts)
