#!/usr/bin/env python3
"""
通过 CDP 连接本机 Chrome（默认 9222）抓取币安广场热榜，缓存；有新内容时调用 Gemini 聊天接口分析。
抓取结果（含每条标题/链接）追加写入日志：getinfo/logs/binance_square.log

前置：已启动带远程调试的 Chrome，例如：
  "C:\\...\\chrome.exe" --remote-debugging-port=9222

环境变量见 getinfo/binance_square_cdp.py 文档。

用法:
  python -m getinfo.run_binance_square
"""
import json
from getinfo.binance_square_cdp import fetch_hot_and_process_new
from getinfo.run_reporter import log_event, callback_result


if __name__ == "__main__":
    script_key = "run-binance-square"
    print(f"[{script_key}] [start]")
    log_event(script_key, f"{script_key} [start]", "INFO")
    try:
        print(f"[{script_key}] 开始抓取币安广场")
        log_event(script_key, "开始抓取币安广场", "INFO")
        report = fetch_hot_and_process_new()
        keys = ("url", "fetched", "new_count", "seeded", "log_path")
        print(json.dumps({k: report[k] for k in keys if k in report and report[k] is not None}, ensure_ascii=False))
        log_event(
            script_key,
            f"抓取摘要 fetched={report.get('fetched', 0)} new={report.get('new_count', 0)} seeded={report.get('seeded', 0)}",
            "INFO",
        )
        if report.get("log_path"):
            print(f"[INFO] 明细已写入日志: {report['log_path']}")
            log_event(script_key, f"明细日志路径: {report['log_path']}", "INFO")
        if report.get("new_count", 0) == 0 and not report.get("seeded"):
            print("[INFO] 暂无新条目（或页面未解析到链接，可检查 BINANCE_SQUARE_URL / 是否需登录）")
            log_event(script_key, "暂无新条目", "INFO")

        log_event(
            script_key,
            f"抓取完成 fetched={report.get('fetched', 0)} new={report.get('new_count', 0)}",
            "INFO",
        )
        callback_result(
            script_key,
            {
                "ok": True,
                "fetched": int(report.get("fetched", 0) or 0),
                "new_count": int(report.get("new_count", 0) or 0),
                "seeded": int(report.get("seeded", 0) or 0),
                "log_path": report.get("log_path"),
            },
        )
        print(f"[{script_key}] [end]")
        log_event(script_key, f"{script_key} [end]", "INFO")
    except Exception as e:
        err = f"执行失败: {e}"
        print(err)
        log_event(script_key, err, "ERROR")
        callback_result(script_key, {"ok": False, "error": str(e)})
        print(f"[{script_key}] [end]")
        log_event(script_key, f"{script_key} [end]", "INFO")
