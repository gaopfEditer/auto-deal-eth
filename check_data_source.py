"""
检查数据源，验证获取的数据是否正确
"""
import akshare as ak
import pandas as pd
import os
import sys

# 设置输出编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 禁用代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

print("=" * 60)
print("检查数据源 - 上证50 (000016)")
print("=" * 60)

try:
    # 获取上证50数据
    symbol = "sh000016"
    print(f"\n使用接口: stock_zh_index_daily")
    print(f"指数代码: {symbol}")
    
    data = ak.stock_zh_index_daily(symbol=symbol)
    
    print(f"\n数据形状: {data.shape}")
    print(f"列名: {list(data.columns)}")
    print(f"\n最新10条数据:")
    print(data.tail(10))
    
    print(f"\n数据统计:")
    print(data.describe())
    
    # 检查价格范围
    if 'close' in data.columns:
        close_prices = data['close']
        print(f"\n收盘价统计:")
        print(f"  最小值: {close_prices.min():.2f}")
        print(f"  最大值: {close_prices.max():.2f}")
        print(f"  最新值: {close_prices.iloc[-1]:.2f}")
        print(f"  平均值: {close_prices.mean():.2f}")
        
        # 检查是否是合理的指数点位
        if close_prices.iloc[-1] < 100:
            print(f"\n[WARNING] 价格异常低 ({close_prices.iloc[-1]:.2f})，可能是:")
            print(f"  1. 数据单位问题（可能是元而不是点）")
            print(f"  2. 获取的不是指数数据，而是ETF或其他数据")
            print(f"  3. 数据源返回的数据格式不正确")
        else:
            print(f"\n[OK] 价格范围正常")
    
    # 尝试其他接口
    print(f"\n" + "=" * 60)
    print("尝试其他接口...")
    print("=" * 60)
    
    # 尝试获取实时行情
    try:
        print(f"\n尝试获取实时行情...")
        spot = ak.stock_zh_index_spot_em()
        if not spot.empty:
            # 查找上证50
            sh50 = spot[spot['代码'].str.contains('000016', na=False)]
            if not sh50.empty:
                print(f"找到上证50实时数据:")
                print(sh50[['代码', '名称', '最新价', '涨跌幅']])
    except Exception as e:
        print(f"实时行情获取失败: {e}")
    
except Exception as e:
    print(f"\n[ERROR] 获取数据失败: {e}")
    import traceback
    traceback.print_exc()

print(f"\n" + "=" * 60)
print("检查完成")
print("=" * 60)

