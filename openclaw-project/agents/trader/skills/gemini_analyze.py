#!/usr/bin/env python3
"""
调用 Gemini API，输出 JSON。

两种模式：
1. 携带图片 → 分析 K 线行情（币种从图中识别）
2. 不携带图片 → 获取实时资讯

  python3 gemini_analyze.py ./chart.png
  python3 gemini_analyze.py --role trader
"""

import base64
import io
import json
import os
import sys
from datetime import datetime, timezone

# 加载 .env
def _load_dotenv():
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        for p in [root, root.parent]:
            env = p / ".env"
            if env.exists():
                with open(env, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            k, v = k.strip(), v.strip().strip('"\'')
                            if k == "PROXY_PORT" and v and "HTTP" not in os.environ:
                                os.environ.setdefault("HTTP_PROXY", f"http://127.0.0.1:{v}")
                                os.environ.setdefault("HTTPS_PROXY", f"http://127.0.0.1:{v}")
                            elif k != "PROXY_PORT":
                                os.environ.setdefault(k, v)
                break
    except Exception:
        pass

_load_dotenv()

# 清除代理，直连 Gemini（与 run_gemini_analyzer 一致）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_REQUEST_TIMEOUT", "60"))


def _get_proxies():
    return None


def _call_gemini_rest(contents: list, role: str = "trader") -> str:
    import requests

    model = GEMINI_MODEL if GEMINI_MODEL.startswith("models/") else f"models/{GEMINI_MODEL}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"
    params = {"key": GEMINI_API_KEY}
    body = {
        "contents": [{"parts": contents}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    proxies = _get_proxies()

    r = requests.post(url, params=params, json=body, timeout=GEMINI_TIMEOUT, proxies=proxies)
    r.raise_for_status()
    data = r.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError("Gemini 返回空内容")
    return parts[0].get("text", "").strip()


def _get_prompt(role: str = "trader") -> str:
    base = """请分析提供的 K 线图表，按下列 JSON 结构输出。

分析要求：
1. 从图中识别币种（如 ETH、BTC），填入 symbol
2. 识别当前趋势（上涨/下跌/震荡）
3. 识别关键支撑位和阻力位
4. 多周期共振：若为多周期组合图，至少两周期同向才给出方向
5. 风险优先：评估最大回撤与止损位
6. 不猜顶底：趋势跟随

输出必须是合法 JSON，且包含以下字段：
{
  "symbol": "从图中识别的币种",
  "direction": "long 或 short 或 neutral",
  "confidence": 0.0-1.0 的数字,
  "entry": "建议入场区间或价位",
  "stop_loss": "止损位",
  "take_profit": "目标位",
  "reason": "简要理由",
  "trend": "趋势描述",
  "support_level": "支撑位",
  "resistance_level": "阻力位"
}

仅返回 JSON，不要其他文字。"""
    if role == "trader":
        return "你是战神 Ares，交易员资讯获取角色。专注 K 线技术分析与交易建议。\n\n" + base
    return base


def _get_news_prompt(role: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    base = f"""作为交易员资讯获取角色，请输出当前加密货币市场需要关注的内容。

当前时间：{now}

输出必须是合法 JSON，且仅包含以下字段：
{{
  "timestamp": "{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}",
  "mode": "news",
  "highlights": ["简要热点1", "简要热点2", "..."],
  "suggested_focus": "建议关注的方向或币种",
  "risk_alerts": ["需警惕的风险或事件"],
  "summary": "一段话总结"
}}

仅返回 JSON，不要其他文字。"""
    if role == "trader":
        return "你是战神 Ares，交易员资讯获取角色。\n\n" + base
    return base


def fetch_news(role: str = "trader") -> dict:
    if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
        raise ValueError("未配置 GEMINI_API_KEY")
    prompt = _get_news_prompt(role)
    raw = _call_gemini_rest([{"text": prompt}], role)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(raw)
    data["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return data


def analyze(image_path: str, role: str = "trader") -> dict:
    from PIL import Image

    if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
        raise ValueError("未配置 GEMINI_API_KEY")

    img = Image.open(image_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    prompt = _get_prompt(role)
    contents = [
        {"inlineData": {"mimeType": "image/jpeg", "data": b64}},
        {"text": prompt},
    ]

    raw = _call_gemini_rest(contents, role)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(raw)
    data["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return data


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Gemini：有图=分析K线，无图=获取实时资讯")
    ap.add_argument("image", nargs="?", help="K 线图路径（不传则走资讯模式）")
    ap.add_argument("--role", "-r", default="trader", help="角色，默认 trader")
    ap.add_argument("--output", "-o", help="写入文件而非 stdout")
    args = ap.parse_args()

    if not args.image:
        try:
            result = fetch_news(role=args.role)
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            result = analyze(args.image, role=args.role)
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

    out = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[OK] 已写入 {args.output}", file=sys.stderr)

    print(out)


if __name__ == "__main__":
    main()
