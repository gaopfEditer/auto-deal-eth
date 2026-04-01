#!/usr/bin/env python3
"""从 RSSHub 拉取资讯，可选 Gemini 提纯，生成简报并推送 Telegram。

用法:
  python -m getinfo.run_rsshub

环境变量（可选）:
  GEMINI_API_URL              Gemini 提纯接口（如 https://xxx/gemini/chat）
  RSSHUB_BASE                 RSSHub 基础 URL，默认 https://rsshub.app
  RSSHUB_FEEDS                JSON 数组覆盖订阅，例 [{"name":"x","url":"https://rsshub.app/...","role":"common"}]
  GETINFO_DAILY_FILE          简报追加写入文件，默认 daily_insight.md
  GETINFO_SEND_TELEGRAM       是否推送到 Telegram，默认 1
  GETINFO_RSS_SELENIUM_CDP    设为 1 时与 run_binance_square 相同：Selenium 连 CHROME_DEBUG_PORT（默认 9222）拉 RSS
"""
from getinfo.rsshub_feed import generate_morning_report
from getinfo.run_reporter import log_event, callback_result


if __name__ == "__main__":
    script_key = "run-rsshub"
    print(f"[{script_key}] [start]")
    log_event(script_key, f"{script_key} [start]", "INFO")
    try:
        print(f"[{script_key}] 开始拉取 RSS 并生成简报")
        log_event(script_key, "开始拉取 RSS 并生成简报", "INFO")
        report = generate_morning_report()
        # 以分段标题粗略统计源数量
        feed_count = report.count("【")
        print(f"[{script_key}] 简报生成完成，feeds={feed_count}, report_len={len(report)}")
        log_event(script_key, f"简报生成完成，feeds={feed_count}, report_len={len(report)}", "INFO")
        log_event(script_key, f"抓取完成，feeds={feed_count}", "INFO")
        callback_result(script_key, {"ok": True, "feeds": int(feed_count), "report_len": len(report)})
        print(f"[{script_key}] [end]")
        log_event(script_key, f"{script_key} [end]", "INFO")
    except Exception as e:
        err = f"执行失败: {e}"
        print(err)
        log_event(script_key, err, "ERROR")
        callback_result(script_key, {"ok": False, "error": str(e)})
        print(f"[{script_key}] [end]")
        log_event(script_key, f"{script_key} [end]", "INFO")
