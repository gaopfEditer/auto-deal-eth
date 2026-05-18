"""
主程序 - 第1部分：导入和主流程函数
"""
import json
import os
import queue
import sys
import threading
import schedule
import time
from datetime import datetime, time as dt_time, timezone
# TradingView相关功能（已注释，暂时不使用）
# from browser_automation import capture_all_timeframes_for_symbol
# from image_llm_analyzer import analyze_chart
# from config import SYMBOLS

from browser_automation import capture_target_page
from image_llm_analyzer import analyze_chart, extract_json_from_gemini_text
from notifier import format_analysis_message, send_notification, send_telegram_message
from ws_signal_handler import process_tradingview_ws_message
from config import TARGET_URL

from dealMsg.runner import (
    _extract_json,
    _tv_binance_symbol,
    capture_tradingview_chart,
    disable_proxy_env,
    get_screenshot_dir,
    parse_ws_payload,
    period_to_tradingview_interval,
)

ANALYSIS_SYMBOL = "ETH_1H"

# 全局变量：是否使用 API 模式
USE_API_MODE = False

def run_analysis(use_api: bool = False):
    """执行完整的分析流程（目标页面）"""
    print("=" * 50)
    print("开始执行页面分析...")
    print("=" * 50)
    
    # 步骤1: 截图目标页面
    print(f"\n[步骤1] 开始截图目标页面: {TARGET_URL}")
    try:
        screenshot_path = capture_target_page()
    except Exception as e:
        print(f"[ERROR] 截图失败: {e}")
        return
    
    if not screenshot_path:
        print("[ERROR] 截图失败，终止流程")
        return
    
    # 步骤2: 本地图模型分析（OLLAMA_CHAT_IMAGE_URL）
    print(f"\n[步骤2] 开始本地图分析...")
    print(f"  [模式] Ollama chat-image（OLLAMA_CHAT_IMAGE_URL）")

    analysis_result = None
    try:
        analysis_result = analyze_chart(screenshot_path, ANALYSIS_SYMBOL, use_api=use_api)
        if analysis_result and analysis_result.get('status') == 'skipped':
            print("[INFO] AI 分析已跳过")
        elif analysis_result and analysis_result.get('status') == 'success':
            print("[OK] 分析完成", file=sys.stderr)
            raw = analysis_result.get("analysis") or ""
            parsed = extract_json_from_gemini_text(raw) if raw else None
            if parsed is not None:
                print(json.dumps(parsed, ensure_ascii=False, indent=2))
            elif raw.strip():
                print(raw.strip())
        else:
            print("[WARNING] 分析失败，但继续执行")
    except Exception as e:
        print(f"[WARNING] 分析异常: {e}，但继续执行")
    
    # 步骤3: 发送通知（如果有分析结果）
    if analysis_result and analysis_result.get('status') not in ['skipped', 'error']:
        print(f"\n[步骤3] 发送通知...")
        message = format_analysis_message({ANALYSIS_SYMBOL: analysis_result})
        send_notification(message)
    else:
        print(f"\n[步骤3] 跳过通知（无分析结果）")
    
    print("\n" + "=" * 50)
    print("分析流程完成！")
    print("=" * 50 + "\n")
    
    # TradingView相关功能（已注释，暂时不使用）
    # all_results = {}
    # 
    # # 遍历所有币种
    # for symbol in SYMBOLS:
    #     print(f"\n{'='*50}")
    #     print(f"处理币种: {symbol}")
    #     print(f"{'='*50}")
    #     
    #     # 步骤1: 截图所有周期并组合
    #     print(f"\n[步骤1] 开始截图 {symbol}...")
    #     try:
    #         screenshot_paths, combined_path = capture_all_timeframes_for_symbol(symbol)
    #     except Exception as e:
    #         print(f"[ERROR] {symbol} 截图失败: {e}")
    #         continue
    #     
    #     if not screenshot_paths or len(screenshot_paths) < 4:
    #         print(f"[ERROR] {symbol} 截图不完整，跳过")
    #         continue
    #     
    #     print(f"[OK] {symbol} 成功截图 {len(screenshot_paths)} 个周期")
    #     
    #     if not combined_path:
    #         print(f"[ERROR] {symbol} 图片组合失败，跳过")
    #         continue
    #     
    #     # 步骤2: Gemini分析（使用组合图片）
    #     print(f"\n[步骤2] 开始Gemini分析 {symbol}...")
    #     try:
    #         analysis_result = analyze_chart(combined_path, symbol)
    #         if analysis_result:
    #             all_results[symbol] = analysis_result
    #             print(f"[OK] {symbol} 分析完成")
    #         else:
    #             print(f"[ERROR] {symbol} 分析失败")
    #     except Exception as e:
    #         print(f"[ERROR] {symbol} 分析异常: {e}")
    # 
    # if not all_results:
    #     print("\n[ERROR] 所有币种分析失败")
    #     return
    # 
    # # 步骤3: 发送通知
    # print(f"\n[步骤3] 发送通知...")
    # message = format_analysis_message(all_results)
    # send_notification(message)
    # 
    # print("\n" + "=" * 50)
    # print(f"分析流程完成！共处理 {len(all_results)} 个币种")
    # print("=" * 50 + "\n")


def handle_ws_tv_message(raw: str, use_api: bool) -> None:
    """
    处理 WSS 文本：心跳跳过；whisper 发车；tradingview 先发格式化告警，
    再按 ticker + period 拼 TradingView URL 截图并 Gemini 分析、发通知。

    注意：由 run_websocket_forever 中的单 worker 串行调用；短时间多条信号会排队，
    前一条（截图+分析+通知）全部完成后才会处理下一条。
    """
    obj = _extract_json(raw)
    if not obj:
        print("[WS] 无法解析为 JSON，忽略", file=sys.stderr)
        return

    if obj.get("type") == "heartbeat":
        print("[WS] 心跳，跳过", file=sys.stderr)
        return

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return

    source = (msg.get("source") or "").strip().lower()
    if source == "whisper":
        send_telegram_message("🚗 发车了！")
        return

    if source != "tradingview":
        return

    ok, note = process_tradingview_ws_message(obj)
    print(f"[WS] {note}", file=sys.stderr)
    if not ok:
        return

    # 可选：截图后再做本地图分析（默认关闭，设 WS_AFTER_SCREENSHOT_ANALYZE=1 开启）
    if os.getenv("WS_AFTER_SCREENSHOT_ANALYZE", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return

    ticker, period = parse_ws_payload(obj)
    symbol_part = _tv_binance_symbol(ticker or "")
    interval_key = period_to_tradingview_interval(period or "1h")
    out_path = os.path.join(get_screenshot_dir(), f"{symbol_part}_{interval_key}.png")
    if not os.path.isfile(out_path):
        return

    analysis_label = f"{symbol_part}_{interval_key}"
    analysis_result = None
    try:
        analysis_result = analyze_chart(out_path, analysis_label, use_api=use_api)
        if analysis_result and analysis_result.get("status") == "success":
            raw_a = analysis_result.get("analysis") or ""
            parsed = extract_json_from_gemini_text(raw_a) if raw_a else None
            if parsed is not None:
                print(json.dumps(parsed, ensure_ascii=False, indent=2))
            elif raw_a.strip():
                print(raw_a.strip())
    except Exception as e:
        print(f"[WS] 图分析异常: {e}", file=sys.stderr)

    if analysis_result and analysis_result.get("status") not in ("skipped", "error"):
        print("\n[WS] 发送分析通知...", file=sys.stderr)
        body = format_analysis_message({analysis_label: analysis_result})
        send_notification(body)


def run_websocket_forever(use_api: bool) -> None:
    """
    阻塞：连接 MAIN_WS_URL（默认 wss://bz.a.gaopf.top/api/ws），处理告警。

    使用单线程 worker + FIFO 队列：1 分钟内（或任意时段）连发多条信号时，
    严格按到达顺序依次处理，不会并行截图/分析。
    """
    from websocket import WebSocketApp

    ws_url = os.getenv("MAIN_WS_URL", "wss://bz.a.gaopf.top/api/ws")
    disable_proxy_env()

    # 单消费者队列：上一条（截图+分析+通知）完成后再取下一条
    signal_queue: queue.Queue = queue.Queue()

    def _ws_worker():
        while True:
            raw = signal_queue.get()
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                handle_ws_tv_message(raw, use_api)
            except Exception as e:
                print(f"[WS] 处理消息失败: {e}", file=sys.stderr)
                print(f"   原始数据: {raw!r}", file=sys.stderr)
            finally:
                signal_queue.task_done()

    worker = threading.Thread(target=_ws_worker, daemon=True)
    worker.start()

    def on_open(ws):
        print(f"[WS] 已连接: {ws_url}", file=sys.stderr)

    def on_message(ws, message):
        try:
            raw = message
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            obj = _extract_json(raw)
            if obj and obj.get("type") == "heartbeat":
                ws.send(
                    json.dumps(
                        {
                            "type": "pong",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
                print("[WS] 心跳 -> pong", file=sys.stderr)
                return
            signal_queue.put(message)
            # unfinished_tasks = 队列中等待数 + 当前 worker 正在处理的一条
            ut = signal_queue.unfinished_tasks
            if ut > 1:
                print(
                    f"[WS] 当前积压 {ut} 条（含正在处理的一条），将严格按顺序逐条执行",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[WS] 入队失败: {e}", file=sys.stderr)

    def on_error(ws, error):
        print(f"[WS] 错误: {error}", file=sys.stderr)

    def on_close(ws, close_status_code, close_msg):
        print(f"[WS] 已关闭: {close_status_code} {close_msg!r}", file=sys.stderr)

    ws = WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever(ping_interval=25, ping_timeout=10)


def start_websocket_daemon(use_api: bool) -> None:
    """后台线程跑 WebSocket，与定时任务共用进程。"""
    t = threading.Thread(target=run_websocket_forever, args=(use_api,), daemon=True)
    t.start()
    print("[INFO] WebSocket 已在后台线程启动（MAIN_WS_URL）", file=sys.stderr)


# 第3部分：定时任务和主入口
def parse_time_range(time_range_str):
    """解析时间区间字符串，如 '1:00-3:00'"""
    try:
        start_str, end_str = time_range_str.split('-')
        start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
        end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
        return start_time, end_time
    except Exception as e:
        print(f"[ERROR] 时间区间格式错误 '{time_range_str}': {e}")
        return None, None

def is_in_time_ranges():
    """检查当前时间是否在配置的时间区间内"""
    from config import TIME_RANGES
    
    # 如果没有配置时间区间，返回 True（全天执行）
    if not TIME_RANGES:
        return True
    
    current_time = datetime.now().time()
    
    for time_range_str in TIME_RANGES:
        start_time, end_time = parse_time_range(time_range_str)
        if start_time is None or end_time is None:
            continue
        
        # 处理跨天的情况，如 22:00-2:00
        if start_time <= end_time:
            # 正常情况：1:00-3:00
            if start_time <= current_time <= end_time:
                return True
        else:
            # 跨天情况：22:00-2:00
            if current_time >= start_time or current_time <= end_time:
                return True
    
    return False

def run_analysis_with_time_check():
    """带时间检查的分析函数"""
    global USE_API_MODE
    if is_in_time_ranges():
        run_analysis(use_api=USE_API_MODE)
    else:
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"[INFO] 当前时间 {current_time} 不在执行时间区间内，跳过本次执行")

def setup_scheduler():
    """设置定时任务"""
    from config import RUN_INTERVAL_MINUTES, TIME_RANGES
    
    # 每N分钟执行一次（带时间区间检查）
    schedule.every(RUN_INTERVAL_MINUTES).minutes.do(run_analysis_with_time_check)
    
    if TIME_RANGES:
        print(f"[INFO] 定时任务已设置：")
        print(f"  - 执行时间区间: {', '.join(TIME_RANGES)}")
        print(f"  - 执行间隔: 每 {RUN_INTERVAL_MINUTES} 分钟")
    else:
        print(f"[INFO] 定时任务已设置：全天执行，每 {RUN_INTERVAL_MINUTES} 分钟执行一次")

def main():
    """主入口"""
    import sys
    global USE_API_MODE
    
    # 解析命令行参数（默认：常驻定时任务 + 后台 WebSocket，等价于原 --ws-daemon）
    use_api = False
    run_once = False
    ws_only = False
    no_ws = False
    
    for arg in sys.argv[1:]:
        if arg == '--once':
            run_once = True
        elif arg == '--api':
            use_api = True
            USE_API_MODE = True
        elif arg == '--ws':
            ws_only = True
        elif arg == '--no-ws':
            no_ws = True
        elif arg == '--ws-daemon':
            # 兼容旧参数：与默认行为相同，无需再写
            pass
        elif arg == '--help' or arg == '-h':
            print("使用方法:")
            print("  python main.py [选项]")
            print("")
            print("默认（无参数）：定时任务 + 后台 WebSocket 监听（MAIN_WS_URL）")
            print("")
            print("选项:")
            print("  --no-ws      不要后台 WebSocket，仅定时任务（爬 tophub 等）")
            print("  --once       只立即执行一次 tophub 分析后退出（不启定时、不启后台 WS）")
            print("  --api        已废弃：图分析固定走本地 OLLAMA_CHAT_IMAGE_URL，此参数无效果")
            print("  --ws         仅阻塞运行 WebSocket + TradingView 流程（无定时任务）")
            print("  环境变量 MAIN_WS_URL 可覆盖默认 WSS 地址")
            print("  --help       显示此帮助信息")
            print("")
            print("示例:")
            print("  python main.py                       # 默认：定时 + 后台 WS")
            print("  python main.py --no-ws               # 仅定时，无 WS")
            print("  python main.py --api                 # --api 无效果（兼容旧脚本）")
            print("  python main.py --once                # 单次 tophub 分析后退出")
            print("  python main.py --ws                  # 仅前台 WebSocket（阻塞）")
            print("  python main.py --ws --api            # 前台 WS（--api 无效果）")
            return
    
    if ws_only:
        print("[INFO] WebSocket 模式（阻塞），按 Ctrl+C 退出...")
        run_websocket_forever(use_api)
        return

    if run_once:
        run_analysis(use_api=use_api)
        return

    # 常驻：定时任务；默认附带后台 WebSocket
    if not no_ws:
        start_websocket_daemon(use_api)
    else:
        print("[INFO] 已禁用后台 WebSocket（--no-ws），仅定时任务", file=sys.stderr)

    setup_scheduler()
    if use_api:
        print("[INFO] 定时任务模式：--api 已废弃，图分析使用本地 OLLAMA_CHAT_IMAGE_URL")
    else:
        print("[INFO] 定时任务模式：图分析使用本地 OLLAMA_CHAT_IMAGE_URL（默认）")
    print("程序运行中，按 Ctrl+C 退出...")
    try:
        while True:
            schedule.run_pending()
            time.sleep(10)  # 每10秒检查一次，确保及时响应时间区间变化
    except KeyboardInterrupt:
        print("\n程序已退出")

if __name__ == '__main__':
    main()
