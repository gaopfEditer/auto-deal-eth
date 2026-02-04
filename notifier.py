"""
通知模块 - 第1部分：导入和配置
"""
import requests
import json
from config import DINGTALK_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_dingtalk_message(content: str):
    """发送钉钉消息"""
    if not DINGTALK_WEBHOOK:
        print("钉钉Webhook未配置")
        return False
    
    try:
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        response = requests.post(DINGTALK_WEBHOOK, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"钉钉消息发送失败: {e}")
        return False

# 第2部分：Telegram通知
def send_telegram_message(content: str):
    """发送Telegram消息"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram配置未完成")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": content,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram消息发送失败: {e}")
        return False

# 第3部分：格式化消息和统一发送接口
def format_analysis_message(analysis_results: dict):
    """格式化分析结果为消息（支持多币种）"""
    message = "[REPORT] 加密货币交易策略分析报告\n\n"
    
    for symbol, result in analysis_results.items():
        message += f"【{symbol}】\n"
        if result.get('status') == 'success':
            message += f"{result.get('analysis', '')}\n\n"
        else:
            message += f"[ERROR] 分析失败: {result.get('error', '未知错误')}\n\n"
    
    return message

def send_notification(content: str):
    """统一发送通知（尝试所有可用渠道）"""
    success_count = 0
    
    if send_dingtalk_message(content):
        success_count += 1
        print("[OK] 钉钉消息发送成功")
    
    if send_telegram_message(content):
        success_count += 1
        print("[OK] Telegram消息发送成功")
    
    if success_count == 0:
        print("[WARNING] 所有通知渠道都未配置或发送失败")
    
    return success_count > 0
