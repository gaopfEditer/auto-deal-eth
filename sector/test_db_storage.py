"""
测试数据库存储功能
"""
import sys
import os
from datetime import datetime

# 添加父目录到路径以便导入sector模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sector import (
    init_tables,
    should_fetch_current_month_data,
    save_month_record,
    save_price_batch,
    get_current_month_prices_from_db,
    get_sector_price_data
)

print("=" * 60)
print("测试数据库存储功能")
print("=" * 60)

# 1. 初始化数据库表
print("\n【步骤1】初始化数据库表...")
try:
    init_tables()
    print("[OK] 数据库表初始化成功")
except Exception as e:
    print(f"[ERROR] 数据库表初始化失败: {e}")
    exit(1)

# 2. 测试检查是否需要获取数据
print("\n【步骤2】检查是否需要获取数据...")
symbol = '000300'
should_fetch = should_fetch_current_month_data(symbol)
print(f"是否需要获取 {symbol} 当前月数据: {should_fetch}")

# 3. 如果需要，获取并存储数据
if should_fetch:
    print(f"\n【步骤3】获取 {symbol} 的价格数据...")
    try:
        # 获取数据（会自动存储到数据库）
        price_data = get_sector_price_data(symbol, periods=['1m'])
        
        if price_data:
            print(f"[OK] 数据获取成功")
            if '1m' in price_data:
                print(f"  1月周期数据:")
                print(f"    当前价格: {price_data['1m']['current_price']:.2f}")
                print(f"    涨跌幅: {price_data['1m']['change_pct']:.2f}%")
        else:
            print(f"[WARNING] 未获取到数据")
    except Exception as e:
        print(f"[ERROR] 获取数据失败: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"\n【步骤3】数据已存在，从数据库读取...")
    try:
        prices = get_current_month_prices_from_db(symbol)
        print(f"[OK] 从数据库读取到 {len(prices)} 条价格记录")
        if prices:
            print(f"  最新价格: {prices[-1]['close_price']:.2f} (日期: {prices[-1]['trade_date']})")
    except Exception as e:
        print(f"[ERROR] 从数据库读取失败: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

