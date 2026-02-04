"""
查找 Chrome 配置文件的脚本
用于找到特定账号对应的 Profile 目录
"""
import os
import json

def find_profile_by_account(account_name, user_data_dir):
    """根据账号名称查找对应的 Profile"""
    user_data_dir = os.path.expanduser(user_data_dir)
    
    if not os.path.exists(user_data_dir):
        print(f"[ERROR] 用户数据目录不存在: {user_data_dir}")
        return None
    
    print(f"正在搜索账号: {account_name}")
    print(f"搜索目录: {user_data_dir}\n")
    
    # 查找所有 Profile 目录
    profiles = []
    for item in os.listdir(user_data_dir):
        item_path = os.path.join(user_data_dir, item)
        if os.path.isdir(item_path) and (item.startswith('Profile') or item == 'Default'):
            profiles.append(item)
    
    print(f"找到 {len(profiles)} 个配置文件: {', '.join(profiles)}\n")
    
    # 检查每个 Profile 的 Preferences 文件
    for profile_name in profiles:
        profile_path = os.path.join(user_data_dir, profile_name)
        preferences_path = os.path.join(profile_path, 'Preferences')
        
        if os.path.exists(preferences_path):
            try:
                with open(preferences_path, 'r', encoding='utf-8') as f:
                    prefs = json.load(f)
                    
                # 检查账号信息
                account_info = prefs.get('account_info', [])
                profile_info = prefs.get('profile', {})
                
                # 查找账号名称
                found = False
                for account in account_info:
                    account_email = account.get('email', '')
                    account_gaia_id = account.get('gaia_id', '')
                    if account_name.lower() in account_email.lower() or account_name in str(account_gaia_id):
                        print(f"✓ 找到匹配的账号！")
                        print(f"  配置文件: {profile_name}")
                        print(f"  账号邮箱: {account_email}")
                        print(f"  完整路径: {profile_path}\n")
                        found = True
                        return profile_name
                
                # 检查 profile 名称
                profile_name_in_prefs = profile_info.get('name', '')
                if account_name.lower() in profile_name_in_prefs.lower():
                    print(f"✓ 找到匹配的配置文件！")
                    print(f"  配置文件: {profile_name}")
                    print(f"  Profile名称: {profile_name_in_prefs}")
                    print(f"  完整路径: {profile_path}\n")
                    return profile_name
                    
            except Exception as e:
                # 如果读取失败，可能是文件被锁定或格式问题
                pass
    
    # 如果没找到，列出所有 Profile 的账号信息
    print("\n未找到匹配的账号，以下是所有配置文件的账号信息：\n")
    for profile_name in profiles:
        profile_path = os.path.join(user_data_dir, profile_name)
        preferences_path = os.path.join(profile_path, 'Preferences')
        
        if os.path.exists(preferences_path):
            try:
                with open(preferences_path, 'r', encoding='utf-8') as f:
                    prefs = json.load(f)
                    
                account_info = prefs.get('account_info', [])
                profile_info = prefs.get('profile', {})
                
                print(f"配置文件: {profile_name}")
                if account_info:
                    for account in account_info:
                        print(f"  - 邮箱: {account.get('email', 'N/A')}")
                        print(f"  - GAIA ID: {account.get('gaia_id', 'N/A')}")
                else:
                    print(f"  - Profile名称: {profile_info.get('name', 'N/A')}")
                print()
            except:
                print(f"配置文件: {profile_name} (无法读取)\n")
    
    return None

if __name__ == '__main__':
    user_data_dir = r'C:\Users\eason\AppData\Local\Google\Chrome\User Data'
    account_name = 'google-gaopf'
    
    profile = find_profile_by_account(account_name, user_data_dir)
    
    if profile:
        print("\n" + "="*60)
        print("配置建议：")
        print("="*60)
        print(f"\n在 .env 文件中添加以下配置：")
        print(f"CHROME_USER_DATA_DIR={user_data_dir}")
        print(f"CHROME_PROFILE_NAME={profile}")
        print(f"CHROME_HEADLESS=False")
        print("\n" + "="*60)
    else:
        print("\n" + "="*60)
        print("未找到匹配的配置文件")
        print("="*60)
        print("\n请检查：")
        print("1. 账号名称是否正确")
        print("2. 是否已在该账号登录 Chrome")
        print("3. 关闭所有 Chrome 窗口后重试")

