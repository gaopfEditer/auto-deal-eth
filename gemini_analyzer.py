"""
Gemini分析模块 - 使用 REST API，无需 google-generativeai
"""
import base64
import json
import os
import re
import sys
from multiprocessing import Process, Queue
from typing import Any, Dict, Optional

from config import GEMINI_API_KEY, GEMINI_REQUEST_TIMEOUT


def init_gemini():
    """校验 API Key，返回 key 或 None"""
    key = (GEMINI_API_KEY or "").strip()
    if not key:
        print("[INFO] GEMINI_API_KEY 未配置，跳过 AI 分析步骤")
        return None
    print(f"[OK] 使用 Gemini REST API")
    return key


def _get_available_models(key):
    """从 ListModels 获取支持 generateContent 的模型，优先 flash"""
    try:
        import requests
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=10
        )
        if r.status_code != 200:
            return ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
        names = [
            m["name"].replace("models/", "")
            for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        flash = [n for n in names if "flash" in n.lower()]
        other = [n for n in names if n not in flash]
        return (flash + other) or ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
    except Exception:
        return ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


def _generate_via_rest(key, prompt, image_path, timeout=60):
    """通过 REST API 调用 generateContent，自动尝试可用模型"""
    import requests
    with open(image_path, "rb") as f:
        img_b64 = base64.standard_b64encode(f.read()).decode()
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/png", "data": img_b64}}
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    for model in _get_available_models(key)[:6]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code in (403, 404):
            try:
                err = r.json().get("error", {}).get("message", "")[:100]
            except Exception:
                err = ""
            if err and "leaked" not in err.lower():
                print(f"[WARN] {model} {r.status_code}: {err}")
        else:
            r.raise_for_status()
    raise RuntimeError("所有模型均失败，请检查 API Key 或到 https://aistudio.google.com/apikey 新建")


def _mime_for_image_path(image_path: str) -> str:
    low = (image_path or "").lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".webp"):
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def generate_multimodal_via_rest(
    key: str,
    prompt: str,
    image_paths: list,
    *,
    timeout: int = 60,
    response_mime_type: str = "application/json",
) -> str:
    """
    多图 + 文本一次 generateContent（与 _generate_via_rest 相同模型轮询策略）。
    image_paths：本地文件路径列表，顺序会保留在 parts 中。
    """
    import requests

    parts: list = [{"text": prompt}]
    for p in image_paths:
        with open(p, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode()
        parts.append(
            {"inline_data": {"mime_type": _mime_for_image_path(p), "data": b64}}
        )
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"response_mime_type": response_mime_type},
    }
    for model in _get_available_models(key)[:6]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code in (403, 404):
            try:
                err = r.json().get("error", {}).get("message", "")[:100]
            except Exception:
                err = ""
            if err and "leaked" not in err.lower():
                print(f"[WARN] {model} {r.status_code}: {err}")
        else:
            r.raise_for_status()
    raise RuntimeError("所有模型均失败，请检查 API Key 或到 https://aistudio.google.com/apikey 新建")


def _kline_json_schema_text() -> str:
    """与提示词中一致的 JSON 结构说明（字符串块，字段名保持一致即可）。"""
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
    """
    K 线分析提示词：只写显著信号，少规则、少枚举，避免模型因约束过多出错。
    仅输出 JSON（无 markdown 围栏）。

    正文来自 ``browser_media_runner/prompts/kline_analysis_single.txt`` 或
    ``kline_analysis_multi.txt``（占位 ``<<SYMBOL>>``）；若文件缺失则回退到内置拼接。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent / "browser_media_runner" / "prompts"
    name = (
        "kline_analysis_multi.txt" if multi_timeframe else "kline_analysis_single.txt"
    )
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


def get_analysis_prompt():
    """兼容旧接口：单图默认 ETH 周期未知时用通用标识。"""
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


def analyze_charts(key, image_paths: dict, base_symbol: str = "ETH"):
    """分析多个周期的K线图（每个周期单独一张图时使用）。"""
    results = {}
    for timeframe, image_path in image_paths.items():
        chart_id = f"{base_symbol}_{timeframe}"
        prompt = get_kline_analysis_prompt(chart_id, multi_timeframe=False)
        try:
            print(f"正在分析 {timeframe} 周期...")
            text = _generate_via_rest(key, prompt, image_path, timeout=GEMINI_REQUEST_TIMEOUT or 60)
            results[timeframe] = {'timeframe': timeframe, 'analysis': text, 'status': 'success'}
        except Exception as e:
            print(f"[ERROR] 分析失败 {timeframe}: {str(e)}")
            results[timeframe] = {'timeframe': timeframe, 'status': 'error', 'error': str(e)}
    return results

def _api_worker(q: Queue, image_path: str, symbol: str):
    """子进程里跑 API 调用，超时可由主进程 kill。必须在模块顶层以便 pickle。"""
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except Exception:
        pass
    try:
        key = init_gemini()
        if key is None:
            q.put({"status": "error", "symbol": symbol, "error": "No API key"})
            return
        q.put(_analyze_with_api(key, image_path, symbol))
    except Exception as e:
        q.put({"status": "error", "symbol": symbol, "error": str(e)})


def analyze_chart(combined_image_path: str, symbol: str, use_api: bool = False):
    """分析图片（支持K线图和普通页面）
    
    Args:
        combined_image_path: 图片路径
        symbol: 符号名称
        use_api: 是否使用 API 模式，False 则使用浏览器网页版模式
    """
    # 如果指定使用 API 模式
    if use_api:
        try:
            key = init_gemini()
            if key is None:
                print("[INFO] API 模式需要配置 GEMINI_API_KEY，切换到浏览器模式")
                use_api = False
            else:
                # 用多进程 + 超时，超时直接杀进程，避免卡死
                print(f"  请求 Gemini API（{GEMINI_REQUEST_TIMEOUT} 秒超时）...")
                q = Queue()
                p = Process(target=_api_worker, args=(q, combined_image_path, symbol))
                p.start()
                p.join(timeout=GEMINI_REQUEST_TIMEOUT)
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=3)
                    if p.is_alive():
                        p.kill()
                    err_msg = (
                        f"Gemini API 在 {GEMINI_REQUEST_TIMEOUT} 秒内无响应，已终止。\n"
                        "  可能原因：网络无法访问 Google、需代理/VPN、或 API 限流。\n"
                        "  建议：检查网络/代理，或使用 --web 走浏览器模式。"
                    )
                    raise TimeoutError(err_msg)
                if q.empty():
                    raise RuntimeError("子进程未返回结果")
                return q.get_nowait()
        except TimeoutError as e:
            print(f"[WARNING] API 模式失败（超时）:\n  {e}\n  切换到浏览器模式")
            use_api = False
        except Exception as e:
            print(f"[WARNING] API 模式失败: {e}\n  切换到浏览器模式")
            use_api = False
    
    # 使用浏览器网页版模式（默认）
    if not use_api:
        print("[INFO] 使用 Gemini 网页版进行分析（浏览器模式）")
        from browser_automation import analyze_with_gemini_web
        return analyze_with_gemini_web(combined_image_path, symbol)

def _analyze_with_api(key, combined_image_path: str, symbol: str):
    """使用 REST API 进行分析（内部函数）"""
    try:
        # 根据symbol判断分析类型
        if symbol == "tophub" or "tophub" in symbol.lower():
            # 普通页面分析
            print(f"  正在分析页面内容...")
            prompt = f"""
请分析这个网页截图的内容，并严格按照 JSON 格式输出分析结果。

这是一个技术开发者热门内容聚合页面（tophub.today/c/developer）。

分析要求：
1. 识别页面上的主要内容类型和主题
2. 提取热门文章/项目的标题和关键信息
3. 分析当前技术趋势和热点话题
4. 总结页面上的重要信息
5. 提供有价值的洞察

输出格式必须符合以下 JSON 结构：
{{
    "page_type": "string",
    "main_topics": ["string"],
    "hot_items": [
        {{
            "title": "string",
            "description": "string",
            "category": "string"
        }}
    ],
    "trends": "string",
    "insights": "string",
    "summary": "string"
}}
"""
        else:
            # K线图分析（组合图）
            print(f"  正在分析 {symbol} 组合图表...")
            prompt = get_kline_analysis_prompt(symbol, multi_timeframe=True)
        
        # 通过 REST API 调用
        text = _generate_via_rest(key, prompt, combined_image_path, timeout=GEMINI_REQUEST_TIMEOUT or 60)
        return {'symbol': symbol, 'analysis': text, 'status': 'success'}
    except Exception as e:
        print(f"[ERROR] {symbol} 分析失败: {str(e)}")
        return {
            'symbol': symbol,
            'status': 'error',
            'error': str(e)
        }

def analyze_all_timeframes(image_paths: dict, base_symbol: str = "ETH"):
    """主入口（兼容旧接口）"""
    key = init_gemini()
    if key is None:
        print("[INFO] 跳过 AI 分析（未配置 API key）")
        return {}
    return analyze_charts(key, image_paths, base_symbol=base_symbol)


def _generate_text_via_rest(key: str, prompt: str, timeout: int = 60) -> str:
    """纯文本 generateContent（无图片），用于帖子方向分类等。"""
    import requests

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    for model in _get_available_models(key)[:6]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            parts = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            if parts and parts[0].get("text"):
                return parts[0]["text"]
            raise RuntimeError("Gemini 返回无 text 字段")
        if r.status_code in (403, 404):
            try:
                err = r.json().get("error", {}).get("message", "")[:120]
            except Exception:
                err = ""
            if err and "leaked" not in err.lower():
                print(f"[WARN] {model} {r.status_code}: {err}")
        else:
            r.raise_for_status()
    raise RuntimeError("所有模型均失败，请检查 API Key 或网络")


def classify_square_post_direction(
    title: str,
    raw_text: str,
    *,
    author: str = "",
) -> Optional[Dict[str, Any]]:
    """
    根据 Square 帖子标题与正文，判断作者倾向做多 / 做空 / 中性 / 不明。
    返回 JSON 字典，含 direction、confidence、reason；失败返回 None。
    """
    key = init_gemini()
    if key is None:
        return None
    body = (raw_text or "")[:12000]
    auth = (author or "").strip()
    prompt = f"""你是加密货币交易内容分析师。根据以下币安 Square 动态（可能是中文），判断作者**主要**表达的交易方向倾向。

只输出**一个** JSON 对象，不要 markdown、不要代码围栏。字段：
- direction: 必须是以下之一： "long" | "short" | "neutral" | "unclear"
  - long: 明确看多、做多、低吸、反弹做多、突破做多、看涨等
  - short: 明确看空、做空、开空、压力做空、看跌、包空等
  - neutral: 纯闲聊、引流、无方向复盘、教学无多空立场
  - unclear: 信息不足无法归类
- confidence: "high" | "medium" | "low"
- reason: 一句简短中文理由（不超过 80 字）

作者（若有）: {auth}
标题: {title}
正文:
{body}
"""
    try:
        text = _generate_text_via_rest(
            key, prompt, timeout=GEMINI_REQUEST_TIMEOUT or 45
        )
        parsed = extract_json_from_gemini_text(text)
        if not isinstance(parsed, dict):
            return None
        d = str(parsed.get("direction", "unclear")).lower()
        if d not in ("long", "short", "neutral", "unclear"):
            parsed["direction"] = "unclear"
        return parsed
    except Exception as e:
        print(f"[WARN] Gemini 帖子方向分类失败: {e}")
        return None