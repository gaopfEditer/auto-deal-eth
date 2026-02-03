"""
主程序 - 第1部分：导入和主流程函数
"""
import schedule
import time
from browser_automation import capture_all_timeframes
from gemini_analyzer import analyze_all_timeframes
from notifier import format_analysis_message, send_notification

def run_analysis():
    """执行完整的分析流程"""
    print("=" * 50)
    print("开始执行交易策略分析...")
    print("=" * 50)
    
    # 步骤1: 截图所有周期
    print("\n[步骤1] 开始截图...")
    try:
        screenshot_paths = capture_all_timeframes()
    except Exception as e:
        print(f"❌ 截图失败: {e}")
        return
    
    if not screenshot_paths:
        print("❌ 截图失败，终止流程")
        return
    
    print(f"✓ 成功截图 {len(screenshot_paths)} 个周期")
    
    # 步骤2: Gemini分析
    print("\n[步骤2] 开始Gemini分析...")
    analysis_results = analyze_all_timeframes(screenshot_paths)
    
    if not analysis_results:
        print("❌ 分析失败，终止流程")
        return
    
    print(f"✓ 完成分析 {len(analysis_results)} 个周期")
    
    # 步骤3: 发送通知
    print("\n[步骤3] 发送通知...")
    message = format_analysis_message(analysis_results)
    send_notification(message)
    
    print("\n" + "=" * 50)
    print("分析流程完成！")
    print("=" * 50 + "\n")

# 第3部分：定时任务和主入口
def setup_scheduler():
    """设置定时任务"""
    from config import RUN_INTERVAL_MINUTES
    
    # 每N分钟执行一次
    schedule.every(RUN_INTERVAL_MINUTES).minutes.do(run_analysis)
    print(f"定时任务已设置：每 {RUN_INTERVAL_MINUTES} 分钟执行一次")

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
                time.sleep(60)  # 每分钟检查一次
        except KeyboardInterrupt:
            print("\n程序已退出")

if __name__ == '__main__':
    main()
