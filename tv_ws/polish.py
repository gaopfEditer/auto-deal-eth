"""
TradingView 信号本地润色：Ollama + prompts/promat（原 8000 publish/signal 的模型部分）。

配置见 config.PROMAT_ANALYSIS（Ollama base_url / model / timeout）。
提示词拼装见 promat_publish.build_tv_signal_compose_prompt。
"""
from __future__ import annotations

import socket
import sys
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from image_llm_analyzer import extract_json_from_gemini_text
from promat_publish import (
    build_tv_signal_compose_prompt,
    format_polished_for_terminal,
    is_high_confidence,
    normalize_confidence,
    normalize_trend,
)

try:
    from config import PROMAT_ANALYSIS
except ImportError:
    PROMAT_ANALYSIS = {}


def _ollama_cfg() -> Dict[str, Any]:
    root = PROMAT_ANALYSIS if isinstance(PROMAT_ANALYSIS, dict) else {}
    o = root.get("ollama") if isinstance(root.get("ollama"), dict) else {}
    return o


def _ollama_reachable(base_url: str, timeout: float = 1.5) -> bool:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return False
    parsed = urlparse(base if "://" in base else f"http://{base}")
    host = (parsed.hostname or "").strip().lower()
    port = parsed.port
    if host not in {"127.0.0.1", "localhost"} or not port:
        return True
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def polish_tv_signal(signal_text: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    本地 Ollama 润色 TV 信号。

    返回 (ok, body)，body 结构与旧 8000 publish/signal 响应兼容：
    { ok, model, polished: { isSign, content, star, meta? } }
    """
    if requests is None:
        print("[polish] 缺少 requests，无法调用 Ollama", file=sys.stderr)
        return False, None

    o = _ollama_cfg()
    if not bool(o.get("enabled", True)):
        print("[polish] PROMAT_ANALYSIS Ollama 已禁用", file=sys.stderr)
        return False, None

    base = (o.get("base_url") or "").strip().rstrip("/")
    model = (o.get("model") or "").strip()
    timeout_sec = int(o.get("timeout_sec") or 120)
    if not base or not model:
        print("[polish] Ollama 配置不完整（base_url / model）", file=sys.stderr)
        return False, None

    prompt = build_tv_signal_compose_prompt(signal_text)
    if not prompt.strip():
        print("[polish] 提示词为空", file=sys.stderr)
        return False, None

    if not _ollama_reachable(base):
        print(f"[polish] Ollama 不可达: {base}", file=sys.stderr)
        return False, None

    url = f"{base}/api/generate"
    print(
        f"[polish] Ollama 润色 model={model!r} url={url} signal_len={len(signal_text)}",
        file=sys.stderr,
    )
    try:
        session = requests.Session()
        session.trust_env = False
        r = session.post(
            url,
            json={"model": model, "prompt": prompt, "stream": False},
            headers={"Content-Type": "application/json"},
            timeout=timeout_sec,
        )
        r.raise_for_status()
        raw = r.json() if r.content else {}
        if not isinstance(raw, dict):
            print("[polish] Ollama 响应非 JSON 对象", file=sys.stderr)
            return False, None
        resp_text = raw.get("response")
        if not isinstance(resp_text, str) or not resp_text.strip():
            print("[polish] Ollama 空响应", file=sys.stderr)
            return False, None

        parsed = extract_json_from_gemini_text(resp_text)
        if not isinstance(parsed, dict):
            print("[polish] 模型输出无法解析为 JSON", file=sys.stderr)
            return False, None

        # 规范化趋势 / 信心，供担子打标
        trend = normalize_trend(parsed.get("trend"))
        conf = normalize_confidence(parsed.get("confidence"))
        if trend:
            parsed["trend"] = trend
        if conf is not None:
            parsed["confidence"] = conf
        # 无 confidence 时用 star 粗映射，便于旧模型兼容
        if conf is None and parsed.get("star") is not None:
            try:
                star_i = int(parsed.get("star") or 0)
                mapped = max(0, min(100, star_i * 20))
                parsed["confidence"] = mapped
                conf = mapped
            except (TypeError, ValueError):
                pass
        parsed["high_confidence"] = is_high_confidence(parsed)

        body: Dict[str, Any] = {
            "ok": True,
            "model": model,
            "polished": parsed,
            "prompt_selection": {
                "style": "style_tianya_classic",
                "strategy": "strategy_left_ambush",
            },
        }
        print("[polish] 润色完成:\n" + format_polished_for_terminal(parsed), file=sys.stderr)
        return True, body
    except Exception as e:
        print(f"[polish] Ollama 请求失败: {e}", file=sys.stderr)
        return False, None
