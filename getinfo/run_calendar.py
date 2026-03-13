#!/usr/bin/env python3
"""运行示例：获取今日及以后的高影响（4/5 星）宏观经济日历。"""
from getinfo.calendar_akshare import get_high_impact_calendar, get_high_impact_calendar_columns


def main():
    df = get_high_impact_calendar()
    if df is None:
        print("未获取到数据，请检查 akshare 版本或网络。")
        return
    cols = [c for c in get_high_impact_calendar_columns() if c in df.columns]
    if cols:
        print(df[cols].head(10).to_string())
    else:
        print(df.head(10).to_string())


if __name__ == "__main__":
    main()
