"""
本地图片分析：POST {OLLAMA_CHAT_IMAGE_URL}，JSON 字段 role / prompt / image_path（与 curl 示例一致）。
保留原 gemini_analyzer 中与其它模块共用的工具函数名，便于替换导入。
"""
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from config import (
    OLLAMA_CHAT_IMAGE_PROMPT,
    OLLAMA_CHAT_IMAGE_ROLE,
    OLLAMA_CHAT_IMAGE_TIMEOUT,
    OLLAMA_CHAT_IMAGE_URL,
    OLLAMA_CLASSIFY_CHAT_URL,
)


def init_gemini():
    """
    兼容旧接口：本地图片分析不依赖 Gemini Key。
    返回非 None 表示「可进行图分析」（供 run_gemini_analyzer 等多周期分支判断）。
    """
    return "local_image_llm"


def _kline_json_schema_text() -> str:
    return r"""{
    "symbol": "string",
    "trend_regime": "string",
    "trend": {
        "summary": "string",
        "decision": {
            "support_level": "string",
            "resistance_level": "string",
            "entry_zone": "string",
            "stop_loss": "string",
            "take_profit": "string",
            "recommendation": "string"
        }
    },
    "candlestick_signals": [
        {
            "pattern": "string",
            "note": "string"
        }
    ],
    "indicators": {
        "macd": "string",
        "rsi": "string",
        "oversold_overbought": "string"
    },
    "signal_strength": "string",
    "risk_level": "string",
    "reasoning": "string"
}"""


def get_kline_analysis_prompt(symbol: str, *, multi_timeframe: bool = False) -> str:
    """K 线分析长提示词（多周期 / 浏览器自动化等仍引用）。"""
    root = Path(__file__).resolve().parent / "browser_media_runner" / "prompts"
    name = "kline_analysis_multi.txt" if multi_timeframe else "kline_analysis_single.txt"
    path = root / name
    if path.is_file():
        return path.read_text(encoding="utf-8").replace("<<SYMBOL>>", str(symbol))

    layout = (
        """
图表说明：可能为多周期拼图（如 2x2）；请按图上可见分区/标注区分周期。若实际只有一张单周期图，则按单图处理。
"""
        if multi_timeframe
        else """
图表说明：一般为**单一周期**的一张 K 线截图，请只基于本图时间与价位分析，不要臆造其它周期。
"""
    )
    schema = _kline_json_schema_text()
    return f"""你是加密货币技术分析师。**只输出一个 JSON 对象**，不要 markdown、不要代码围栏、不要多余说明。

品种/图表标识：{symbol}
{layout}
**原则：少写规则、少做「全面汇总」。细碎波动、模棱两可的形态不要写；弱信号没有交易价值，不必提。**

**只写图上足够醒目的内容（没有就写「无明显信号」或留空）：**
- **趋势**：趋势方向，首先要看是单边还是横盘，因为趋势往往会延续，所以看k线之前先判断是否单边，写在 trend.summary。如果是单边，则继续判断趋势方向，上涨还是下跌，写在 trend.decision.direction。
- **K 线**：重点看**射击之星**、**看涨/看跌吞没**、背离，上插针下插针频率，尤其短期连续插针的时候，这个作为主要判断标准；其它形态只有非常清晰才写。
- **超买超卖 / 超买超卖**：写在 indicators.oversold_overbought。
- **MACD**：是否**金叉 / 死叉**或清晰的多空转折（写在 indicators.macd）。
- **RSI**：是否**明显过高 / 明显过低**（写在 indicators.rsi）。

**禁止**把多个弱信号凑在一起「综合分析」；reasoning 里只简述与上述显著信号相关的依据即可。

**价位与风格（短线）**：trend.decision 填支撑、阻力、入场、止损、止盈（数字与图表标尺一致）。默认按**短线**思路：**止损偏小**、入场与止盈区间**紧凑**，不要给过宽的价格带或过大的波动区间；trend.summary、trend_regime、signal_strength、risk_level 简短自然即可，**不要**为凑格式编造内容。

**JSON 字段名与下表一致即可，取值自由、从简：**
{schema}
"""


def get_analysis_prompt() -> str:
    return get_kline_analysis_prompt("ETH", multi_timeframe=False)


def extract_json_from_gemini_text(text: str) -> Optional[Dict[str, Any]]:
    """从模型返回文本中提取 JSON（去 markdown 围栏、截取第一个大括号对象）。"""
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _normalize_chat_image_response(data: Any) -> str:
    """将服务端返回统一成一段可打印/可再解析的文本。"""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for k in ("analysis", "response", "message", "content", "text", "reply", "result"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v
        try:
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return str(data)
    return str(data)


def _post_chat_image(abs_image_path: str, role: str, prompt: str) -> str:
    url = (OLLAMA_CHAT_IMAGE_URL or "").strip()
    if not url:
        raise RuntimeError("未配置 OLLAMA_CHAT_IMAGE_URL")

    session = requests.Session()
    session.trust_env = False
    payload = {
        "role": role,
        "prompt": prompt,
        "image_path": abs_image_path,
    }
    r = session.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=OLLAMA_CHAT_IMAGE_TIMEOUT,
    )
    if not r.ok:
        body = (r.text or "")[:800]
        raise RuntimeError(f"chat-image HTTP {r.status_code}: {body}")

    ct = (r.headers.get("content-type") or "").lower()
    if "application/json" in ct:
        try:
            return _normalize_chat_image_response(r.json())
        except Exception:
            return (r.text or "").strip()
    return (r.text or "").strip()


def analyze_chart(combined_image_path: str, symbol: str, use_api: bool = False):
    """
    分析单张图片：调用本地 Ollama chat-image 接口。
    use_api 参数保留以兼容旧调用，已不再区分（不再使用 Gemini 网页/API）。
    """
    _ = use_api
    if not combined_image_path or not os.path.isfile(combined_image_path):
        return {
            "symbol": symbol,
            "status": "error",
            "error": f"图片不存在: {combined_image_path}",
        }

    abs_path = os.path.abspath(combined_image_path)
    role = (OLLAMA_CHAT_IMAGE_ROLE or "binance_k_line").strip()
    base_prompt = (OLLAMA_CHAT_IMAGE_PROMPT or "根据这张图判断趋势").strip()
    prompt = f"{base_prompt}\n图表/任务标识: {symbol}"

    try:
        print(f"[INFO] 请求本地图分析: {OLLAMA_CHAT_IMAGE_URL}", file=sys.stderr)
        text = _post_chat_image(abs_path, role, prompt)
        return {"symbol": symbol, "analysis": text, "status": "success"}
    except Exception as e:
        print(f"[ERROR] 本地图分析失败: {e}", file=sys.stderr)
        return {"symbol": symbol, "status": "error", "error": str(e)}


def analyze_all_timeframes(image_paths: dict, base_symbol: str = "ETH"):
    """每个周期单独一张图时，逐张调用本地接口。"""
    results = {}
    for timeframe, image_path in image_paths.items():
        chart_id = f"{base_symbol}_{timeframe}"
        extra = f"\n周期: {timeframe}，标识: {chart_id}"
        role = (OLLAMA_CHAT_IMAGE_ROLE or "binance_k_line").strip()
        base_prompt = (OLLAMA_CHAT_IMAGE_PROMPT or "根据这张图判断趋势").strip()
        prompt = f"{base_prompt}{extra}"
        try:
            print(f"[INFO] 本地分析 {timeframe} ...", file=sys.stderr)
            if not image_path or not os.path.isfile(image_path):
                raise FileNotFoundError(image_path)
            text = _post_chat_image(os.path.abspath(image_path), role, prompt)
            results[timeframe] = {"timeframe": timeframe, "analysis": text, "status": "success"}
        except Exception as e:
            print(f"[ERROR] 分析失败 {timeframe}: {e}", file=sys.stderr)
            results[timeframe] = {"timeframe": timeframe, "status": "error", "error": str(e)}
    return results


def classify_square_post_direction(
    title: str,
    raw_text: str,
    *,
    author: str = "",
) -> Optional[Dict[str, Any]]:
    """
    文本分类（无图）：若配置了 OLLAMA_CLASSIFY_CHAT_URL 则 POST JSON 调用；否则返回 None。
    期望服务端返回 JSON：direction / confidence / reason。
    """
    url = (OLLAMA_CLASSIFY_CHAT_URL or "").strip()
    if not url:
        return None

    body = (raw_text or "")[:12000]
    auth = (author or "").strip()
    prompt = f"""根据以下币安 Square 动态（可能是中文），判断作者**主要**表达的交易方向倾向。

只输出**一个** JSON 对象，不要 markdown、不要代码围栏。字段：
- direction: 必须是以下之一： "long" | "short" | "neutral" | "unclear"
- confidence: "high" | "medium" | "low"
- reason: 一句简短中文理由（不超过 80 字）

作者（若有）: {auth}
标题: {title}
正文:
{body}
"""
    try:
        session = requests.Session()
        session.trust_env = False
        r = session.post(
            url,
            json={"role": "square_post_direction", "prompt": prompt},
            headers={"Content-Type": "application/json"},
            timeout=OLLAMA_CHAT_IMAGE_TIMEOUT,
        )
        if not r.ok:
            print(f"[WARN] 分类接口 HTTP {r.status_code}: {(r.text or '')[:200]}", file=sys.stderr)
            return None
        ct = (r.headers.get("content-type") or "").lower()
        text = ""
        if "application/json" in ct:
            data = r.json()
            text = _normalize_chat_image_response(data)
        else:
            text = (r.text or "").strip()
        parsed = extract_json_from_gemini_text(text)
        if not isinstance(parsed, dict):
            return None
        d = str(parsed.get("direction", "unclear")).lower()
        if d not in ("long", "short", "neutral", "unclear"):
            parsed["direction"] = "unclear"
        return parsed
    except Exception as e:
        print(f"[WARN] 帖子方向分类失败: {e}", file=sys.stderr)
        return None
