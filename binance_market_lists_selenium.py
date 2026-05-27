#!/usr/bin/env python3
"""兼容入口：完整 Square/关注流抓取见 binance.market_lists_selenium；仅涨幅榜见 binance.gainers_top20"""
from binance.market_lists_selenium import main

if __name__ == "__main__":
    main()
