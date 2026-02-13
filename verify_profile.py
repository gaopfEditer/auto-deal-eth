"""
Chrome Profile 配置验证脚本
用于验证 Chrome Profile 配置是否正确
"""
import os
import sys
from browser_automation import verify_chrome_profile
from config import CHROME_USER_DATA_DIR, CHROME_PROFILE_NAME

def main():
    print("="*60)
    print("Chrome Profile 配置验证工具")
    print("="*60)
    print()
    
    # 获取配置
    if CHROME_USER_DATA_DIR and CHROME_USER_DATA_DIR.strip():
        user_data_dir = os.path.expanduser(CHROME_USER_DATA_DIR.strip())
    else:
        # 使用默认路径
        if sys.platform == "win32":
            user_data_dir = os.path.join(os.getenv('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
        elif sys.platform == "darwin":  # Mac
            user_data_dir = os.path.expanduser('~/Library/Application Support/Google/Chrome')
        else:  # Linux
            user_data_dir = os.path.expanduser('~/.config/google-chrome')
    
    profile_name = CHROME_PROFILE_NAME if CHROME_PROFILE_NAME else 'Profile 2'
    
    print(f"配置信息:")
    print(f"  - 用户数据目录: {user_data_dir}")
    print(f"  - Profile 名称: {profile_name}")
    print()
    
    # 检查 Chrome 是否正在运行
    from browser_automation import check_chrome_running
    if check_chrome_running():
        print("[WARNING] 检测到 Chrome 正在运行")
        print("[提示] 使用 Profile 时建议先关闭所有 Chrome 窗口")
        print("[提示] 继续验证...")
        print()
    
    # 执行验证
    success = verify_chrome_profile(user_data_dir, profile_name)
    
    if success:
        print("\n" + "="*60)
        print("验证结果: [OK] 配置正确")
        print("="*60)
        print("\n建议:")
        print("1. 确保 Chrome 已关闭")
        print("2. 运行程序: python main.py --once")
    else:
        print("\n" + "="*60)
        print("验证结果: [ERROR] 配置有误")
        print("="*60)
        print("\n请检查:")
        print("1. CHROME_USER_DATA_DIR 配置是否正确")
        print("2. CHROME_PROFILE_NAME 配置是否正确")
        print("3. 参考 CHROME_PROFILE_SETUP.md 文档进行配置")

if __name__ == '__main__':
    main()

