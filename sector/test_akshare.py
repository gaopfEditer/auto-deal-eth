"""
测试AKShare接口可用性
"""
import akshare as ak
import pandas as pd
import os
import sys

# 禁用代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

print("=" * 60)
print("测试AKShare接口可用性")
print("=" * 60)

# 测试1: 测试基础接口
print("\n【测试1】测试基础接口...")
try:
    # 测试获取指数列表
    print("尝试获取指数列表...")
    index_list = ak.index_zh_a_hist(symbol="000300", period="daily", start_date="20240101", end_date="20240213")
    print(f"[OK] 成功获取数据，共 {len(index_list)} 条记录")
    print(f"列名: {list(index_list.columns)}")
    print(f"前5行数据:")
    print(index_list.head())
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

# 测试2: 测试其他接口
print("\n【测试2】测试其他接口...")
try:
    print("尝试使用 stock_zh_index_daily...")
    data = ak.stock_zh_index_daily(symbol="sh000300")
    print(f"[OK] 成功获取数据，共 {len(data)} 条记录")
    print(f"列名: {list(data.columns)}")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

# 测试3: 测试实时数据
print("\n【测试3】测试实时数据接口...")
try:
    print("尝试获取指数实时行情...")
    spot = ak.stock_zh_index_spot()
    print(f"[OK] 成功获取数据，共 {len(spot)} 条记录")
    if '000300' in str(spot.values):
        print("[OK] 找到沪深300数据")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

