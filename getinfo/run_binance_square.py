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
from getinfo.binance_square_cdp import run_binance_square_once


if __name__ == "__main__":
    run_binance_square_once()
