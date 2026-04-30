"""
测试基金收益率获取功能
"""
import sys
import os

# 添加父目录到路径以便导入sector模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sector import (
    get_fund_return_rate,
    COMMON_FUNDS,
    COMMON_SECTORS
)

print("=" * 60)
print("测试基金收益率获取功能")
print("=" * 60)

# 测试1: 获取指数收益率（使用指数代码）
print("\n【测试1】获取沪深300指数收益率...")
try:
    return_data = get_fund_return_rate('000300', periods=['1m', '3m', '6m', '1y'])
    
    if return_data:
        print(f"\n基金/指数: {return_data.get('symbol_title', 'N/A')} ({return_data.get('symbol', 'N/A')})")
        print(f"类型: {return_data.get('symbol_type', 'N/A')}")
        print("\n收益率数据:")
        for period, data in return_data.get('returns', {}).items():
            print(f"  {period.upper()} 周期:")
            print(f"    收益率: {data.get('return_rate', 0):.2f}%")
            print(f"    当前价格: {data.get('current_price', 0):.2f}")
            print(f"    起始价格: {data.get('start_price', 0):.2f}")
            print(f"    日期范围: {data.get('start_date', 'N/A')} ~ {data.get('end_date', 'N/A')}")
    else:
        print("[WARNING] 未获取到数据")
except Exception as e:
    print(f"[ERROR] 获取失败: {e}")
    import traceback
    traceback.print_exc()

# 测试2: 获取中证2000指数收益率
print("\n【测试2】获取中证2000指数收益率...")
try:
    return_data = get_fund_return_rate('000932', periods=['1m', '3m', '6m', '1y'])
    
    if return_data:
        print(f"\n基金/指数: {return_data.get('symbol_title', 'N/A')} ({return_data.get('symbol', 'N/A')})")
        print("\n收益率数据:")
        for period, data in return_data.get('returns', {}).items():
            print(f"  {period.upper()} 周期: {data.get('return_rate', 0):.2f}%")
    else:
        print("[WARNING] 未获取到数据")
except Exception as e:
    print(f"[ERROR] 获取失败: {e}")

# 测试3: 获取ETF基金收益率（中概互联）
print("\n【测试3】获取中概互联ETF收益率...")
try:
    return_data = get_fund_return_rate('513050', periods=['1m', '3m', '6m', '1y'])
    
    if return_data:
        print(f"\n基金/指数: {return_data.get('symbol_title', 'N/A')} ({return_data.get('symbol', 'N/A')})")
        print("\n收益率数据:")
        for period, data in return_data.get('returns', {}).items():
            print(f"  {period.upper()} 周期: {data.get('return_rate', 0):.2f}%")
    else:
        print("[WARNING] 未获取到数据")
except Exception as e:
    print(f"[ERROR] 获取失败: {e}")
    import traceback
    traceback.print_exc()

# 测试4: 批量获取常用基金收益率
print("\n【测试4】批量获取常用基金收益率...")
funds_to_test = [
    ('沪深300', '000300'),
    ('中证2000', '000932'),
    ('中概互联ETF', '513050'),
]

for name, code in funds_to_test:
    print(f"\n正在获取 {name} ({code}) 的收益率...")
    try:
        return_data = get_fund_return_rate(code, periods=['1y'])
        
        if return_data and '1y' in return_data.get('returns', {}):
            symbol_title = return_data.get('symbol_title', name)
            return_rate = return_data['returns']['1y'].get('return_rate', 0)
            print(f"  [OK] {symbol_title} ({name}) 1年收益率: {return_rate:.2f}%")
        else:
            print(f"  [WARNING] {name} 未获取到数据")
    except Exception as e:
        print(f"  [ERROR] {name} 获取失败: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

