"""
promat 提示词加载与拼装（供 publish/signal 服务或本地调试）。

默认路径：prompts/promat/
"""
from __future__ import annotations

import json
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


def normalize_polished_content(content: Any) -> str:
    """把模型返回的 content 转为易读多行（处理 \\n 转义）。"""
    if content is None:
        return ""
    s = str(content).strip()
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    return s


def format_polished_for_terminal(polished: Dict[str, Any]) -> str:
    """终端展示用：分行 + 星级 + meta。"""
    if not isinstance(polished, dict):
        return str(polished)
    lines = []
    star = polished.get("star")
    if star is not None:
        lines.append(f"⭐ 信号强度: {star}/5  |  isSign={polished.get('isSign')}")
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
    """从 publish/signal 响应提取 Telegram 配文（润色正文优先）。"""
    if not isinstance(body, dict) or not body.get("ok"):
        return ""
    polished = body.get("polished")
    if not isinstance(polished, dict):
        return ""
    lines: list[str] = []
    star = polished.get("star")
    if star is not None:
        lines.append(f"⭐ 信号强度: {star}/5")
    content = normalize_polished_content(polished.get("content"))
    if content:
        lines.append(content)
    return "\n".join(lines).strip()


def describe_publish_response(body: Dict[str, Any]) -> str:
    """从 /api/publish/signal 响应 JSON 提取可读摘要。"""
    if not isinstance(body, dict):
        return str(body)
    if not body.get("ok"):
        return json.dumps(body, ensure_ascii=False, indent=2)
    parts = [f"ok={body.get('ok')}"]
    if body.get("model"):
        parts.append(f"model={body.get('model')}")
    polished = body.get("polished")
    if isinstance(polished, dict):
        parts.append("\n" + format_polished_for_terminal(polished))
    sel = body.get("prompt_selection")
    if isinstance(sel, dict):
        parts.append(
            "\n[prompt] "
            + ", ".join(f"{k}={v}" for k, v in sel.items() if v)
        )
    return "\n".join(parts)
