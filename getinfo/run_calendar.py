#!/usr/bin/env python3
"""运行示例：近一周（昨天起 7 天）仅 3星(5星·高) 高影响宏观经济日历。"""
from getinfo.calendar_akshare import get_high_impact_calendar, get_high_impact_calendar_columns
from getinfo.run_reporter import log_event, callback_result

# 默认最多显示行数（0 表示全部）
MAX_ROWS = 180


def main():
    script_key = "run-calendar"
    print(f"[{script_key}] [start]")
    log_event(script_key, f"{script_key} [start]", "INFO")
    # 仅高影响：3星(5星·高)
    try:
        print(f"[{script_key}] 开始抓取高影响宏观日历")
        log_event(script_key, "开始抓取高影响宏观日历", "INFO")
        df = get_high_impact_calendar(importance_value="高")
        if df is None:
            msg = "未获取到数据，请检查 akshare 版本或网络。"
            print(msg)
            log_event(script_key, msg, "WARNING")
            callback_result(script_key, {"ok": False, "count": 0, "message": msg})
            print(f"[{script_key}] [end]")
            log_event(script_key, f"{script_key} [end]", "INFO")
            return

        cols = [c for c in get_high_impact_calendar_columns() if c in df.columns]
        subset = df[cols] if cols else df
        print(f"[{script_key}] 数据抓取完成，count={len(df)}")
        log_event(script_key, f"数据抓取完成，count={len(df)}", "INFO")
        if MAX_ROWS and len(subset) > MAX_ROWS:
            print(subset.head(MAX_ROWS).to_string())
            print(f"\n... 共 {len(df)} 条，仅显示前 {MAX_ROWS} 条。")
        else:
            print(subset.to_string())
            if len(df):
                print(f"\n共 {len(df)} 条。")

        log_event(script_key, f"抓取完成，count={len(df)}", "INFO")
        callback_result(script_key, {"ok": True, "count": int(len(df))})
        print(f"[{script_key}] [end]")
        log_event(script_key, f"{script_key} [end]", "INFO")
    except Exception as e:
        err = f"执行失败: {e}"
        print(err)
        log_event(script_key, err, "ERROR")
        callback_result(script_key, {"ok": False, "count": 0, "error": str(e)})
        print(f"[{script_key}] [end]")
        log_event(script_key, f"{script_key} [end]", "INFO")


if __name__ == "__main__":
    main()
