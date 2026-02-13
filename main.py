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
    
    # 步骤2: Gemini分析
    print(f"\n[步骤2] 开始Gemini分析...")
    if use_api:
        print(f"  [模式] 使用 API 模式进行分析")
    else:
        print(f"  [模式] 使用浏览器网页版模式进行分析（默认）")
    
    analysis_result = None
    try:
        analysis_result = analyze_chart(screenshot_path, "tophub", use_api=use_api)
        if analysis_result and analysis_result.get('status') == 'skipped':
            print("[INFO] AI 分析已跳过（未配置 API key）")
        elif analysis_result and analysis_result.get('status') == 'success':
        print(f"[OK] 分析完成")
            if analysis_result.get('method') == 'web':
                print(f"  [提示] 分析结果已在浏览器中显示，请查看 Gemini 网页版")
        else:
            print("[WARNING] 分析失败，但继续执行")
    except Exception as e:
        print(f"[WARNING] 分析异常: {e}，但继续执行")
    
    # 步骤3: 发送通知（如果有分析结果）
    if analysis_result and analysis_result.get('status') not in ['skipped', 'error']:
    print(f"\n[步骤3] 发送通知...")
    message = format_analysis_message({"tophub": analysis_result})
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
    
    # 解析命令行参数
    use_api = False
    run_once = False
    
    for arg in sys.argv[1:]:
        if arg == '--once':
            run_once = True
        elif arg == '--api':
            use_api = True
            USE_API_MODE = True
        elif arg == '--help' or arg == '-h':
            print("使用方法:")
            print("  python main.py [选项]")
            print("")
            print("选项:")
            print("  --once     立即执行一次（测试模式）")
            print("  --api      使用 API 模式进行分析（需要配置 GEMINI_API_KEY）")
            print("             默认使用浏览器网页版模式进行分析")
            print("  --help     显示此帮助信息")
            print("")
            print("示例:")
            print("  python main.py --once              # 使用浏览器模式立即执行一次")
            print("  python main.py --once --api        # 使用 API 模式立即执行一次")
            print("  python main.py                      # 定时任务模式（浏览器模式）")
            print("  python main.py --api               # 定时任务模式（API 模式）")
            return
    
    if run_once:
        # 立即执行一次
        run_analysis(use_api=use_api)
    else:
        # 设置定时任务
        setup_scheduler()
        if use_api:
            print("[INFO] 定时任务模式：使用 API 模式进行分析")
        else:
            print("[INFO] 定时任务模式：使用浏览器网页版模式进行分析（默认）")
        print("程序运行中，按 Ctrl+C 退出...")
        try:
            while True:
                schedule.run_pending()
                time.sleep(10)  # 每10秒检查一次，确保及时响应时间区间变化
        except KeyboardInterrupt:
            print("\n程序已退出")

if __name__ == '__main__':
    main()
