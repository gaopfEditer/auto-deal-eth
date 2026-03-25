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


if __name__ == "__main__":
    generate_morning_report()
