"""
主程序 - 第1部分：导入和主流程函数
"""
import schedule
import time
from datetime import datetime, time as dt_time
# TradingView相关功能（已注释，暂时不使用）
# from browser_automation import capture_all_timeframes_for_symbol
# from gemini_analyzer import analyze_chart
# from config import SYMBOLS

from browser_automation import capture_target_page
from gemini_analyzer import analyze_chart
from notifier import format_analysis_message, send_notification
from config import TARGET_URL

def run_analysis():
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
    
    # 步骤2: Gemini分析
    print(f"\n[步骤2] 开始Gemini分析...")
    try:
        analysis_result = analyze_chart(screenshot_path, "tophub")
        if not analysis_result:
            print("[ERROR] 分析失败，终止流程")
            return
        
        print(f"[OK] 分析完成")
    except Exception as e:
        print(f"[ERROR] 分析异常: {e}")
        return
    
    # 步骤3: 发送通知
    print(f"\n[步骤3] 发送通知...")
    message = format_analysis_message({"tophub": analysis_result})
    send_notification(message)
    
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
    if is_in_time_ranges():
        run_analysis()
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
    
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        # 立即执行一次
        run_analysis()
    else:
        # 设置定时任务
        setup_scheduler()
        print("程序运行中，按 Ctrl+C 退出...")
        try:
            while True:
                schedule.run_pending()
                time.sleep(10)  # 每10秒检查一次，确保及时响应时间区间变化
        except KeyboardInterrupt:
            print("\n程序已退出")

if __name__ == '__main__':
    main()
