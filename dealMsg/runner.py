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
import queue
import re
import sys
import threading
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
    """禁用进程内的代理环境变量：确保 WSS/HTTP 直连（含 SOCKS）。"""
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SOCKS_PROXY",
        "SOCKS5_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "socks_proxy",
        "socks5_proxy",
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


def _tv_binance_symbol(ticker: str) -> str:
    """
    TradingView `BINANCE:` 后的符号部分。
    - ETHUSD -> ETHUSDT
    - SOLUSDT.P（永续）-> SOLUSDT.P
    """
    t = (ticker or "").strip().upper()
    if not t:
        return ""
    is_perp = t.endswith(".P")
    if is_perp:
        t = t[:-2]
    if t.endswith("USD") and not t.endswith("USDT"):
        t = t[:-3] + "USDT"
    return f"{t}.P" if is_perp else t


def period_to_tradingview_interval(period: str) -> str:
    """
    将 15m / 30m / 1h / 4h / 1d 等转为 TradingView chart 的 interval 参数。
    日内用分钟数字符串；日线等价 1440 分钟，TradingView 使用 1D（比 interval=1440 更稳定）。
    """
    p = (period or "").strip().lower()
    if not p:
        return "15"
    table = {
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "60m": "60",
        "h1": "60",
        "4h": "240",
        "240m": "240",
        "1d": "1D",
        "1day": "1D",
        "d": "1D",
        "d1": "1D",
        "1440": "1D",
        "1440m": "1D",
    }
    if p in table:
        return table[p]
    if p.endswith("m") and p[:-1].isdigit():
        return p[:-1]
    if p.endswith("h") and p[:-1].isdigit():
        return str(int(p[:-1]) * 60)
    if p.isdigit():
        return p
    return p


def _tradingview_url(symbol_part: str, timeframe: str) -> str:
    """
    直接构造 TradingView 地址，避免依赖 config.py 中被注释的 TRADINGVIEW_BASE_URL。
    """
    # examples:
    # https://www.tradingview.com/chart/?symbol=ETHUSDT&interval=15
    # https://www.tradingview.com/chart/?symbol=SOLUSDT.P&interval=60
    interval = period_to_tradingview_interval(timeframe)
    return f"https://www.tradingview.com/chart/?symbol={symbol_part}&interval={interval}"


def _playwright_cdp_url() -> Optional[str]:
    """
    Playwright 是否通过 CDP 连接本机已启动的 Chrome（与 9222 远程调试一致）。
    默认开启：DEALMSG_PLAYWRIGHT_USE_CDP=0 时才改为独立 launchPersistentContext。
    """
    v = os.getenv("DEALMSG_PLAYWRIGHT_USE_CDP", "1").strip().lower()
    if v in ("0", "false", "no"):
        return None
    port = (
        os.getenv("CHROME_DEBUG_PORT")
        or os.getenv("DEALMSG_CHROME_DEBUG_PORT")
        or "9222"
    ).strip()
    return f"http://127.0.0.1:{port}"


def _capture_tradingview_playwright(url: str, out_path: str) -> str:
    """使用 dealMsg/tv_playwright：默认 connectOverCDP(9222) 复用已打开的 Chrome；否则独立 user_data。"""
    import shutil
    import subprocess

    script_dir = PROJECT_ROOT / "dealMsg" / "tv_playwright"
    script = script_dir / "screenshot.js"
    if not script.is_file():
        raise FileNotFoundError(f"缺少 {script}，请先安装依赖，见 dealMsg/tv_playwright/README.md")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("未找到 node，请先安装 Node.js")
    abs_out = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(abs_out) or ".", exist_ok=True)
    timeout_ms = int(os.getenv("DEALMSG_PLAYWRIGHT_TIMEOUT_MS", "120000"))
    cmd = [
        node,
        str(script),
        "--url",
        url,
        "--out",
        abs_out,
        "--timeout",
        str(timeout_ms),
    ]
    cdp = _playwright_cdp_url()
    if cdp:
        cmd.extend(["--cdp", cdp])
        print(f"[INFO] Playwright 将 CDP 连接到 {cdp}（与 Selenium 远程调试同一 Chrome）", file=sys.stderr)
    r = subprocess.run(
        cmd,
        cwd=str(script_dir),
        capture_output=True,
        text=True,
        timeout=min(600, timeout_ms / 1000 + 180),
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"Playwright 截图失败: {err}")
    if r.stdout.strip():
        print(r.stdout.strip(), file=sys.stderr)
    return abs_out


def _dealmsg_use_remote_debugging() -> bool:
    """是否连接已开启远程调试的 Chrome。默认与 config 一致（通常为 True）。"""
    v = os.getenv("DEALMSG_USE_REMOTE_DEBUGGING", "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    # 未单独配置时读项目根 .env / 环境里的 USE_REMOTE_DEBUGGING
    return os.getenv("USE_REMOTE_DEBUGGING", "True").strip().lower() == "true"


def capture_tradingview_chart(ticker: str, timeframe: str, out_path: str) -> str:
    """
    截 TradingView 图到指定 out_path。

    - 设置 DEALMSG_USE_PLAYWRIGHT=1 时使用 Playwright + stealth（推荐缓解 Reconnect/风控）
    - 否则使用 Selenium；远程调试模式在新标签页打开图表，截图后只关闭该标签
    """
    import time
    import traceback

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    symbol_part = _tv_binance_symbol(ticker)
    url = _tradingview_url(symbol_part, timeframe)

    if os.getenv("DEALMSG_USE_PLAYWRIGHT", "0").strip().lower() in ("1", "true", "yes"):
        print("[INFO] 使用 Playwright Stealth 截图（dealMsg/tv_playwright）", file=sys.stderr)
        return _capture_tradingview_playwright(url, out_path)

    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    use_remote = _dealmsg_use_remote_debugging()
    driver = init_browser(use_remote_debugging=use_remote)

    main_handle = None
    opened_new_tab = False
    wait_timeout = int(os.getenv("DEALMSG_CHART_WAIT_SEC", "45"))

    try:
        if use_remote and driver.window_handles:
            main_handle = driver.current_window_handle
            driver.execute_script("window.open('about:blank','_blank');")
            WebDriverWait(driver, 15).until(lambda d: len(d.window_handles) > 1)
            new_handles = [h for h in driver.window_handles if h != main_handle]
            if new_handles:
                driver.switch_to.window(new_handles[-1])
                opened_new_tab = True

        driver.set_page_load_timeout(90)
        driver.get(url)

        # 多选择器兜底（先长等 #chart-container，再短等其它）
        chart_found = False
        last_err = None
        primary = ((By.ID, "chart-container"),)
        fallbacks = (
            (By.CSS_SELECTOR, "div#chart-container"),
            (By.CSS_SELECTOR, "[id^='chart-container']"),
            (By.CSS_SELECTOR, "#chart-container canvas"),
        )
        try:
            WebDriverWait(driver, wait_timeout).until(
                EC.presence_of_element_located(primary[0])
            )
            chart_found = True
        except (TimeoutException, WebDriverException) as e:
            last_err = e
            for by, sel in fallbacks:
                try:
                    WebDriverWait(driver, 12).until(EC.presence_of_element_located((by, sel)))
                    chart_found = True
                    break
                except (TimeoutException, WebDriverException) as e2:
                    last_err = e2

        if not chart_found:
            # 再等几秒后仍尝试截图（可能仅有部分元素或反爬页）
            time.sleep(5)
            if last_err:
                print(
                    f"[WARN] 未检测到 chart-container，仍尝试截图。最后错误: {type(last_err).__name__}: {last_err}",
                    file=sys.stderr,
                )

        time.sleep(3)
        driver.save_screenshot(out_path)
        return out_path
    except Exception as e:
        print(
            f"[ERROR] TradingView 截图异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}",
            file=sys.stderr,
        )
        raise
    finally:
        try:
            if use_remote and opened_new_tab and main_handle:
                try:
                    driver.close()
                except Exception:
                    pass
                try:
                    driver.switch_to.window(main_handle)
                except Exception:
                    pass
            # 远程调试下 quit() 有时会结束整个浏览器；默认仍 quit 以释放会话，便于连续多条消息。
            # 若 quit 会关掉 Chrome，可设 DEALMSG_REMOTE_SKIP_QUIT=1（仅单次截图或需手动结束 chromedriver）
            skip_quit = use_remote and os.getenv("DEALMSG_REMOTE_SKIP_QUIT", "0").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if not skip_quit:
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


def _run_forever_handle_raw_message(message: str) -> None:
    """解析一条 WSS 文本并执行截图 + Gemini（由单 worker 串行调用）。"""
    obj = _extract_json(message)
    if not obj:
        print("[WARN] 收到非 JSON 消息，忽略", file=sys.stderr)
        return

    print("[WS] obj:", json.dumps(obj, ensure_ascii=False, indent=2), file=sys.stderr)

    ticker, period = parse_ws_payload(obj)
    if not ticker:
        print(f"[WARN] 缺少 ticker/period: ticker={ticker} period={period}", file=sys.stderr)
        return

    symbol_part = _tv_binance_symbol(ticker)
    out_path = os.path.join(get_screenshot_dir(), f"{symbol_part}_{period}.png")

    try:
        print(f"[INFO] 截图: {ticker} {period} -> {out_path}", file=sys.stderr)
        capture_tradingview_chart(ticker=ticker, timeframe=period, out_path=out_path)

        print(f"[INFO] Gemini 分析请求: {out_path}", file=sys.stderr)
        result = gemini_chat_kline(out_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[ERROR] 处理失败: {e}", file=sys.stderr)
        print(json.dumps({"error": str(e), "ticker": ticker, "period": period}, ensure_ascii=False))


def run_forever(ws_url: str) -> None:
    """
    阻塞监听 WSS。多条信号在短时间内到达时，使用 FIFO 队列 + 单 worker，
    上一条截图+分析完成后才处理下一条。
    """
    from websocket import WebSocketApp

    signal_queue: queue.Queue = queue.Queue()

    def _worker():
        while True:
            raw = signal_queue.get()
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                _run_forever_handle_raw_message(raw)
            except Exception as e:
                print(f"[ERROR] worker 处理异常: {e}", file=sys.stderr)
            finally:
                signal_queue.task_done()

    threading.Thread(target=_worker, daemon=True).start()

    def on_open(ws):
        print(f"[INFO] WS 连接成功: {ws_url}", file=sys.stderr)

    def on_message(ws, message):
        signal_queue.put(message)
        ut = signal_queue.unfinished_tasks
        if ut > 1:
            print(
                f"[INFO] 当前积压 {ut} 条（含正在处理的一条），将按顺序逐条执行",
                file=sys.stderr,
            )

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

