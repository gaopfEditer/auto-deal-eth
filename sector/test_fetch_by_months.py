"""
测试按月批量获取数据功能
"""
import sys
import os

# 添加父目录到路径以便导入sector模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sector import fetch_data_by_months, get_symbol_title

print("=" * 60)
print("测试按月批量获取数据功能")
print("=" * 60)

# 测试1: 倒推模式 - 获取最近1个月的数据
print("\n【测试1】倒推模式 - 获取最近1个月的数据...")
try:
    result = fetch_data_by_months(
        symbol='000300',
        mode='period',
        period='1m',
        symbol_type='index'
    )
    
    print(f"\n结果:")
    print(f"  代码: {result.get('symbol')}")
    print(f"  名称: {result.get('symbol_title')}")
    print(f"  总月数: {result.get('total_months')}")
    print(f"  成功: {result.get('fetched_months')}")
    print(f"  跳过: {result.get('skipped_months')}")
    print(f"  失败: {result.get('failed_months')}")
    
    if result.get('months_detail'):
        print(f"\n月份详情:")
        for detail in result['months_detail'][:5]:  # 只显示前5个
            print(f"  {detail['year']}年{detail['month']}月: {detail['status']} (记录数: {detail.get('records', 0)})")
    
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试2: 指定区间模式 - 获取2021年1月到3月的数据
print("\n【测试2】指定区间模式 - 获取2021年1月到3月的数据...")
try:
    result = fetch_data_by_months(
        symbol='000300',
        mode='range',
        start_month='202101',
        end_month='202103',
        symbol_type='index'
    )
    
    print(f"\n结果:")
    print(f"  代码: {result.get('symbol')}")
    print(f"  名称: {result.get('symbol_title')}")
    print(f"  总月数: {result.get('total_months')}")
    print(f"  成功: {result.get('fetched_months')}")
    print(f"  跳过: {result.get('skipped_months')}")
    print(f"  失败: {result.get('failed_months')}")
    
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试3: 从2021年开始获取到现在（使用指定区间模式）
print("\n【测试3】从2021年1月开始获取到现在...")
try:
    result = fetch_data_by_months(
        symbol='000300',
        mode='range',
        start_month='202101',
        end_month=None,  # None表示到当前月
        symbol_type='index'
    )
    
    print(f"\n结果:")
    print(f"  代码: {result.get('symbol')}")
    print(f"  名称: {result.get('symbol_title')}")
    print(f"  总月数: {result.get('total_months')}")
    print(f"  成功: {result.get('fetched_months')}")
    print(f"  跳过: {result.get('skipped_months')}")
    print(f"  失败: {result.get('failed_months')}")
    
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试4: 倒推模式 - 获取最近1年的数据
print("\n【测试4】倒推模式 - 获取最近1年的数据...")
try:
    result = fetch_data_by_months(
        symbol='000300',
        mode='period',
        period='1y',
        symbol_type='index'
    )
    
    print(f"\n结果:")
    print(f"  代码: {result.get('symbol')}")
    print(f"  名称: {result.get('symbol_title')}")
    print(f"  总月数: {result.get('total_months')}")
    print(f"  成功: {result.get('fetched_months')}")
    print(f"  跳过: {result.get('skipped_months')}")
    print(f"  失败: {result.get('failed_months')}")
    
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

