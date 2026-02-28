"""
Gemini分析模块 - 使用 REST API，无需 google-generativeai
"""
import base64
import os
import sys
from multiprocessing import Process, Queue

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
            return ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
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

def get_analysis_prompt():
    """获取分析提示词 (优化了 prompt 以适配 JSON 模式)"""
    return """
你是一个资深的加密货币技术分析师。请分析提供的 K 线图表，并严格按照 JSON 格式输出建议。
分析要求：
1. 识别当前趋势（上涨/下跌/震荡）
2. 识别关键支撑位和阻力位
3. 分析技术指标信号（MACD, RSI, Bollinger Bands 等）
4. 给出明确交易建议（Long/Short/Neutral）
5. 评估风险等级（Low/Medium/High）

输出格式必须符合以下 JSON 结构：
{
    "trend": "string",
    "support_level": "string",
    "resistance_level": "string",
    "indicators": {
        "macd": "string",
        "rsi": "string",
        "bb": "string"
    },
    "recommendation": "string",
    "risk_level": "string",
    "reasoning": "string"
}
"""

def analyze_charts(key, image_paths: dict):
    """分析多个周期的K线图"""
    results = {}
    prompt = get_analysis_prompt()
    for timeframe, image_path in image_paths.items():
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
            # K线图分析
            print(f"  正在分析 {symbol} 组合图表...")
            prompt = f"""
你是一个资深的加密货币技术分析师。请分析提供的 K 线图表组合图，并严格按照 JSON 格式输出建议。

图表说明：
- 这是一张包含4个时间周期的组合图（2x2布局）
- 左上角：15分钟周期
- 右上角：30分钟周期
- 左下角：1小时周期
- 右下角：2小时周期
- 币种：{symbol}

分析要求：
1. 识别当前趋势（上涨/下跌/震荡）
2. 识别关键支撑位和阻力位
3. 分析技术指标信号（MACD, RSI, Bollinger Bands 等）
4. 综合4个周期的分析，给出明确交易建议（Long/Short/Neutral）
5. 评估风险等级（Low/Medium/High）

输出格式必须符合以下 JSON 结构：
{{
    "symbol": "{symbol}",
    "trend": "string",
    "support_level": "string",
    "resistance_level": "string",
    "indicators": {{
        "macd": "string",
        "rsi": "string",
        "bb": "string"
    }},
    "recommendation": "string",
    "risk_level": "string",
    "reasoning": "string"
}}
"""
        
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

def analyze_all_timeframes(image_paths: dict):
    """主入口（兼容旧接口）"""
    key = init_gemini()
    if key is None:
        print("[INFO] 跳过 AI 分析（未配置 API key）")
        return {}
    return analyze_charts(key, image_paths)