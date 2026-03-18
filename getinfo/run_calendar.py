#!/usr/bin/env python3
"""运行示例：近一周（昨天起 7 天）仅 3星(5星·高) 高影响宏观经济日历。"""
from getinfo.calendar_akshare import get_high_impact_calendar, get_high_impact_calendar_columns

# 默认最多显示行数（0 表示全部）
MAX_ROWS = 180


def main():
    # 仅高影响：3星(5星·高)
    df = get_high_impact_calendar(importance_value="高")
    if df is None:
        print("未获取到数据，请检查 akshare 版本或网络。")
        return
    cols = [c for c in get_high_impact_calendar_columns() if c in df.columns]
    subset = df[cols] if cols else df
    if MAX_ROWS and len(subset) > MAX_ROWS:
        print(subset.head(MAX_ROWS).to_string())
        print(f"\n... 共 {len(df)} 条，仅显示前 {MAX_ROWS} 条。")
    else:
        print(subset.to_string())
        if len(df):
            print(f"\n共 {len(df)} 条。")


if __name__ == "__main__":
    main()
