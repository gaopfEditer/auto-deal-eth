#!/usr/bin/env python3
"""
dealMsg: 监听 WSS 消息 -> 解析币种/周期 -> 截 TradingView 图 -> 调 ezcoin Gemini 封装接口。

期望收到的消息（示例）：
{
  "response": {
    "data": {
      "ticker": "ETHUSD",
      "period": "15m",
      "type": "射击之星"
    }
  }
}
"""

import base64
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional, Tuple

import requests

# 让脚本在任意 cwd 下都能导入项目根模块
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_automation import init_browser


def get_screenshot_dir() -> str:
    """
    直接读取项目根 .env 的 SCREENSHOT_DIR；未配置时默认 ./screenshots。
    """
    env_path = PROJECT_ROOT / ".env"
    screenshot_dir = "./screenshots"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() == "SCREENSHOT_DIR":
                        screenshot_dir = v.strip().strip("\"'")
                        break
        except Exception:
            pass
    return os.path.join(str(PROJECT_ROOT), screenshot_dir.lstrip("./"))


def disable_proxy_env() -> None:
    """禁用进程内的代理环境变量：确保 WSS/HTTP 直连。"""
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        os.environ.pop(k, None)


def _extract_json(text: str) -> Optional[dict]:
    """
    有些 WSS 消息可能带前缀行（如日志前缀 "2|nextjs-j | ...")。
    尝试从字符串中截取第一个完整 JSON 对象。
    """
    if not text:
        return None
    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 兜底：截取 {...} 段
    m = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _normalize_symbol(ticker: str) -> str:
    """
    TradingView/BINANCE 常用符号：ETHUSDT
    输入可能是 ETHUSD -> 转成 ETHUSDT
    """
    t = (ticker or "").strip().upper()
    if not t:
        return t
    if t.endswith("USD") and not t.endswith("USDT"):
        return t[:-3] + "USDT"
    return t


def _tradingview_url(symbol_usdt: str, timeframe: str) -> str:
    """
    直接构造 TradingView 地址，避免依赖 config.py 中被注释的 TRADINGVIEW_BASE_URL。
    """
    # examples:
    # https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT&interval=15m
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol_usdt}&interval={timeframe}"


def capture_tradingview_chart(ticker: str, timeframe: str, out_path: str) -> str:
    """
    Selenium 截 TradingView 图到指定 out_path。
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    symbol_usdt = _normalize_symbol(ticker)
    url = _tradingview_url(symbol_usdt, timeframe)

    driver = init_browser()
    try:
        driver.get(url)
        # TradingView 图表加载等待
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "chart-container"))
        )
        # 再等一下，确保画面完成渲染
        import time
        time.sleep(3)
        driver.save_screenshot(out_path)
        return out_path
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def gemini_chat_kline(image_path: str, role: str = "k_line_analysis", message: str = "分析这个走势？") -> Any:
    """
    调用你提供的 ezcoin Gemini 封装接口。

    按你的示例请求：
      {"role":"k_line_analysis","message":"分析这个走势？", "files":"xxx.png"}

    但实际文件上传通常需要 multipart/form-data 或 base64。
    这里按“最常见且成功率较高”的做法：multipart 上传文件（字段名为 files）。
    """
    url = "https://bz.d.ezcoin.ink/gemini/chat"

    session = requests.Session()
    # 不使用代理：直连
    session.trust_env = False
    disable_proxy_env()

    # 先读取图片字节（便于两种请求方式复用）
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    # 方式1：multipart 上传文件（字段名 files）
    files = {"files": (os.path.basename(image_path), io.BytesIO(img_bytes), "image/png")}
    data = {"role": role, "message": message}
    resp = session.post(url, data=data, files=files, timeout=60)

    # 尽量返回 JSON，否则返回文本
    ct = (resp.headers.get("content-type") or "").lower()
    if resp.ok:
        if "application/json" in ct:
            return resp.json()
        try:
            return resp.text
        except Exception:
            return {"raw": str(resp.content)}

    # 方式2（兜底）：JSON 发送 base64 data URL（files）
    b64 = base64.b64encode(img_bytes).decode("ascii")
    payload = {
        "role": role,
        "message": message,
        "files": f"data:image/png;base64,{b64}",
    }
    resp2 = session.post(url, json=payload, timeout=60)
    ct2 = (resp2.headers.get("content-type") or "").lower()
    if resp2.ok:
        if "application/json" in ct2:
            return resp2.json()
        try:
            return resp2.text
        except Exception:
            return {"raw": str(resp2.content)}

    # 两种方式都失败：返回响应摘要便于你排查
    return {
        "error": "gemini/chat request failed",
        "status_1": resp.status_code,
        "response_1": (resp.text or "").strip()[:500],
        "status_2": resp2.status_code,
        "response_2": (resp2.text or "").strip()[:500],
    }


DEFAULT_PERIOD = "15m"


def _parse_period_from_original_message(text: str) -> Optional[str]:
    """从 metadata.original_message 里解析周期，例如 '... | 9.143 | 15m; 触发信号'（取最后一个 | Xm;）。"""
    if not text or not isinstance(text, str):
        return None
    found = re.findall(r"\|\s*(\d+[mMdDhH])\s*;", text)
    if found:
        return found[-1].lower()
    return None


def _normalize_period(period: Optional[str], original_message: Optional[str] = None) -> str:
    """period 为空时：先试 original_message，再默认 15m。"""
    p = (period or "").strip()
    if p:
        return p
    from_om = _parse_period_from_original_message(original_message or "")
    if from_om:
        return from_om
    return DEFAULT_PERIOD


def parse_ws_payload(payload: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    从 WSS 消息里提取 ticker/period。

    新结构（message_received）：
      message.metadata.ticker / period / original_message

    旧结构：response.data 或顶层 ticker/period
    """
    if not payload:
        return None, None

    # 新结构：type=message_received，数据在 message.metadata
    if payload.get("type") == "message_received" and isinstance(payload.get("message"), dict):
        msg = payload["message"]
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        ticker = meta.get("ticker") or meta.get("symbol") or ""
        raw_period = meta.get("period") or meta.get("timeframe") or meta.get("interval") or ""
        om = meta.get("original_message") or ""
        period = _normalize_period(raw_period, om)
        t = str(ticker).strip() or None
        if t:
            return t, period
        return None, None

    data = payload
    if isinstance(payload.get("response"), dict):
        data = payload["response"].get("data") or payload["response"]

    if not isinstance(data, dict):
        return None, None

    ticker = data.get("ticker") or data.get("symbol") or ""
    raw_period = data.get("period") or data.get("timeframe") or data.get("interval") or ""
    om = data.get("original_message") or ""
    period = _normalize_period(raw_period, om)
    t = str(ticker).strip() or None
    return (t, period if t else None)


def run_forever(ws_url: str) -> None:
    # websocket-client 依赖
    from websocket import WebSocketApp

    def on_open(ws):
        print(f"[INFO] WS 连接成功: {ws_url}", file=sys.stderr)

    def on_message(ws, message):
        obj = _extract_json(message)
        if not obj:
            print("[WARN] 收到非 JSON 消息，忽略", file=sys.stderr)
            return

        print("[WS] obj:", json.dumps(obj, ensure_ascii=False, indent=2), file=sys.stderr)

        ticker, period = parse_ws_payload(obj)
        if not ticker:
            print(f"[WARN] 缺少 ticker/period: ticker={ticker} period={period}", file=sys.stderr)
            return

        # 文件输出：例如 ETHUSDT_15m.png
        symbol_usdt = _normalize_symbol(ticker)
        out_path = os.path.join(get_screenshot_dir(), f"{symbol_usdt}_{period}.png")

        try:
            print(f"[INFO] 截图: {ticker} {period} -> {out_path}", file=sys.stderr)
            capture_tradingview_chart(ticker=ticker, timeframe=period, out_path=out_path)

            print(f"[INFO] Gemini 分析请求: {out_path}", file=sys.stderr)
            result = gemini_chat_kline(out_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[ERROR] 处理失败: {e}", file=sys.stderr)
            print(json.dumps({"error": str(e), "ticker": ticker, "period": period}, ensure_ascii=False))

    def on_error(ws, error):
        print(f"[ERROR] WS 错误: {error}", file=sys.stderr)

    def on_close(ws, close_status_code, close_msg):
        print(f"[WARN] WS 已关闭: {close_status_code} {close_msg}", file=sys.stderr)

    ws = WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # 直连：不使用系统代理
    disable_proxy_env()
    ws.run_forever(ping_interval=25, ping_timeout=10)


def main():
    import argparse

    ap = argparse.ArgumentParser(description="dealMsg - WSS->截图->Gemini 分析")
    ap.add_argument("--ws-url", default="wss://bz.a.gaopf.top/api/ws", help="WSS 地址")
    ap.add_argument("--once", action="store_true", help="仅用于调试（收到一条消息后不退出，这里不实现）")
    args = ap.parse_args()

    run_forever(args.ws_url)


if __name__ == "__main__":
    main()

