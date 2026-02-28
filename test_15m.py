#!/usr/bin/env python3
"""测试用 .env 中的 GEMINI_API_KEY 分析 screenshots/chart_15m.png
只用 requests，无需 google-generativeai"""
import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from config import GEMINI_API_KEY
IMAGE_PATH = os.path.join(ROOT, "screenshots", "chart_15m.png")

PROMPT = """你是一个资深的加密货币技术分析师。请分析提供的 K 线图表，并严格按照 JSON 格式输出建议。
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
    "indicators": {"macd": "string", "rsi": "string", "bb": "string"},
    "recommendation": "string",
    "risk_level": "string",
    "reasoning": "string"
}
"""


def main():
    key = (GEMINI_API_KEY or "").strip()
    if not key:
        print("[ERROR] .env 中未配置 GEMINI_API_KEY")
        sys.exit(1)

    if not os.path.isfile(IMAGE_PATH):
        print(f"[ERROR] 图片不存在: {IMAGE_PATH}")
        sys.exit(1)

    import requests

    with open(IMAGE_PATH, "rb") as f:
        img_b64 = base64.standard_b64encode(f.read()).decode()

    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": img_b64
                    }
                }
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    # 先获取可用模型列表，再逐个尝试
    models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        mr = requests.get(models_url, timeout=10)
        if mr.status_code == 200:
            model_names = [
                m["name"].replace("models/", "")
                for m in mr.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            # 优先 flash 系列（便宜快）
            model_names = [n for n in model_names if "flash" in n.lower()] + [
                n for n in model_names if "flash" not in n.lower()
            ]
            if not model_names:
                model_names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
        else:
            model_names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
    except Exception:
        model_names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]

    for model in model_names[:6]:  # 最多尝试 6 个
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        print(f"[INFO] 分析图片: {IMAGE_PATH}")
        print(f"[INFO] 使用模型: {model}")
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            break
        if r.status_code in (403, 404):
            try:
                err = r.json().get("error", {}).get("message", r.text[:150])
            except Exception:
                err = r.text[:150]
            print(f"[WARN] {model} {r.status_code}: {err}")
        else:
            r.raise_for_status()
    else:
        print("[ERROR] 所有模型均失败。若为 403「leaked」: 请到 https://aistudio.google.com/apikey 新建 API Key 并更新 .env")
        sys.exit(1)

    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    print("\n[OK] 分析结果:")
    try:
        data = json.loads(text)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print(text)


if __name__ == "__main__":
    main()
