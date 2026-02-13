"""
板块数据获取模块 - 使用AKShare获取国内和港股板块的估值、价格数据
支持获取1月、3月、6月、1年、3年、5年的历史数据
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import time
import os
import sys
import warnings
warnings.filterwarnings('ignore')

# 导入数据库模块
try:
    from .db import (
        init_tables,
        should_fetch_current_month_data,
        save_month_record,
        save_price_batch,
        get_current_month_prices_from_db
    )
    DB_AVAILABLE = True
except ImportError:
    print("[WARNING] 数据库模块未导入，将跳过数据库存储功能")
    DB_AVAILABLE = False

# 设置输出编码为UTF-8（Windows，安全方式）
if sys.platform == 'win32':
    try:
        import io
        if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer is not None and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

# 禁用代理（避免代理错误）
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'
# 尝试禁用urllib3的代理
try:
    import urllib3
    urllib3.disable_warnings()
except:
    pass


# 时间周期映射（月数）
TIME_PERIODS = {
    '1m': 1,      # 1个月
    '3m': 3,      # 3个月
    '6m': 6,      # 6个月
    '1y': 12,     # 1年
    '3y': 36,     # 3年
    '5y': 60,     # 5年
}


def fetch_data_by_months(
    symbol: str,
    mode: str = 'period',
    period: str = None,
    start_month: str = None,
    end_month: str = None,
    symbol_type: str = 'index'
) -> Dict:
    """
    按月批量获取数据并存储到数据库
    
    Args:
        symbol: 板块/指数代码
        mode: 获取模式
            - 'period': 倒推模式，使用 period 参数（如 '1m', '3m', '1y' 等）
            - 'range': 指定区间模式，使用 start_month 和 end_month 参数（如 '202101', '202103'）
        period: 倒推周期（仅在 mode='period' 时使用）
            - '1m': 今天向前倒推1个月
            - '3m': 今天向前倒推3个月
            - '6m': 今天向前倒推6个月
            - '1y': 今天向前倒推1年
            - '3y': 今天向前倒推3年
            - '5y': 今天向前倒推5年
        start_month: 起始月份，格式 'YYYYMM'（如 '202101'），仅在 mode='range' 时使用
        end_month: 结束月份，格式 'YYYYMM'（如 '202103'），仅在 mode='range' 时使用。如果为None，则到当前月
        symbol_type: 类型，'index' 或 'sector'，默认 'index'
    
    Returns:
        包含获取结果的字典
    """
    result = {
        'symbol': symbol,
        'symbol_title': get_symbol_title(symbol),
        'mode': mode,
        'total_months': 0,
        'fetched_months': 0,
        'skipped_months': 0,
        'failed_months': 0,
        'months_detail': []
    }
    
    try:
        # 初始化数据库表
        if DB_AVAILABLE:
            init_tables()
        
        # 确定要获取的月份列表
        months_to_fetch = []
        
        if mode == 'period':
            # 倒推模式
            if period not in TIME_PERIODS:
                raise ValueError(f"不支持的周期: {period}，支持的周期: {list(TIME_PERIODS.keys())}")
            
            months_back = TIME_PERIODS[period]
            today = datetime.now()
            start_date = today - timedelta(days=months_back * 30)
            
            # 生成月份列表（从开始月份到当前月份）
            current = datetime(start_date.year, start_date.month, 1)
            end = datetime(today.year, today.month, 1)
            
            while current <= end:
                months_to_fetch.append((current.year, current.month))
                # 移动到下一个月
                if current.month == 12:
                    current = datetime(current.year + 1, 1, 1)
                else:
                    current = datetime(current.year, current.month + 1, 1)
        
        elif mode == 'range':
            # 指定区间模式
            if not start_month:
                raise ValueError("指定区间模式需要提供 start_month 参数")
            
            # 解析起始月份
            try:
                start_year = int(start_month[:4])
                start_month_num = int(start_month[4:6])
                if not (1 <= start_month_num <= 12):
                    raise ValueError(f"月份必须在1-12之间: {start_month}")
            except (ValueError, IndexError):
                raise ValueError(f"起始月份格式错误: {start_month}，应为 YYYYMM 格式（如 202101）")
            
            # 解析结束月份
            if end_month:
                try:
                    end_year = int(end_month[:4])
                    end_month_num = int(end_month[4:6])
                    if not (1 <= end_month_num <= 12):
                        raise ValueError(f"月份必须在1-12之间: {end_month}")
                except (ValueError, IndexError):
                    raise ValueError(f"结束月份格式错误: {end_month}，应为 YYYYMM 格式（如 202103）")
            else:
                # 如果没有指定结束月份，则到当前月
                today = datetime.now()
                end_year = today.year
                end_month_num = today.month
            
            # 生成月份列表
            current = datetime(start_year, start_month_num, 1)
            end = datetime(end_year, end_month_num, 1)
            
            while current <= end:
                months_to_fetch.append((current.year, current.month))
                # 移动到下一个月
                if current.month == 12:
                    current = datetime(current.year + 1, 1, 1)
                else:
                    current = datetime(current.year, current.month + 1, 1)
        else:
            raise ValueError(f"不支持的模式: {mode}，支持的模式: 'period', 'range'")
        
        result['total_months'] = len(months_to_fetch)
        print(f"[INFO] 准备获取 {symbol} ({result['symbol_title']}) 共 {len(months_to_fetch)} 个月的数据")
        
        # 逐月获取数据
        for year, month in months_to_fetch:
            month_str = f"{year}年{month}月"
            try:
                # 检查该月数据是否已存在
                if DB_AVAILABLE:
                    from .db import check_month_data_exists, get_month_prices_from_db
                    if check_month_data_exists(symbol, year, month):
                        prices = get_month_prices_from_db(symbol, year, month)
                        if prices and len(prices) > 0:
                            print(f"[INFO] {month_str} 数据已存在，跳过（共 {len(prices)} 条记录）")
                            result['skipped_months'] += 1
                            result['months_detail'].append({
                                'year': year,
                                'month': month,
                                'status': 'skipped',
                                'records': len(prices)
                            })
                            continue
                
                # 获取该月数据
                print(f"[INFO] 正在获取 {month_str} 的数据...")
                month_data = _fetch_single_month_data(symbol, year, month, symbol_type)
                
                if month_data and month_data.get('success'):
                    records = month_data.get('records', 0)
                    print(f"[OK] {month_str} 获取成功，共 {records} 条记录")
                    result['fetched_months'] += 1
                    result['months_detail'].append({
                        'year': year,
                        'month': month,
                        'status': 'success',
                        'records': records
                    })
                else:
                    error_msg = month_data.get('error', '未知错误') if month_data else '获取失败'
                    print(f"[ERROR] {month_str} 获取失败: {error_msg}")
                    result['failed_months'] += 1
                    result['months_detail'].append({
                        'year': year,
                        'month': month,
                        'status': 'failed',
                        'error': error_msg
                    })
                
                # 避免请求过快
                time.sleep(0.5)
                
            except Exception as e:
                print(f"[ERROR] {month_str} 处理失败: {e}")
                result['failed_months'] += 1
                result['months_detail'].append({
                    'year': year,
                    'month': month,
                    'status': 'failed',
                    'error': str(e)
                })
        
        print(f"\n[INFO] 完成！总计: {result['total_months']} 个月，成功: {result['fetched_months']}，跳过: {result['skipped_months']}，失败: {result['failed_months']}")
        
        return result
        
    except Exception as e:
        print(f"[ERROR] 批量获取数据失败: {e}")
        import traceback
        traceback.print_exc()
        result['error'] = str(e)
        return result


def _fetch_single_month_data(
    symbol: str,
    year: int,
    month: int,
    symbol_type: str = 'index'
) -> Dict:
    """
    获取单个月份的数据（内部函数）
    
    Args:
        symbol: 板块/指数代码
        year: 年份
        month: 月份 (1-12)
        symbol_type: 类型
    
    Returns:
        包含获取结果的字典
    """
    result = {
        'success': False,
        'records': 0,
        'error': None
    }
    
    try:
        # 计算该月的日期范围
        start_date = datetime(year, month, 1)
        # 计算该月最后一天
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)
        
        # 确保不超过今天
        today = datetime.now()
        if end_date > today:
            end_date = today
        
        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = end_date.strftime('%Y%m%d')
        
        # 获取数据
        price_df = None
        
        # 方法1: 使用 index_zh_a_hist
        try:
            price_df = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start_date_str, end_date=end_date_str)
            if not price_df.empty:
                print(f"[DEBUG] 方法1成功，获取 {len(price_df)} 条记录")
        except Exception as e:
            price_df = None
        
        # 方法2: 使用 stock_zh_index_daily（需要添加市场前缀）
        if price_df is None or price_df.empty:
            try:
                if symbol.startswith('000'):
                    symbol_with_prefix = f"sh{symbol}"
                elif symbol.startswith('399'):
                    symbol_with_prefix = f"sz{symbol}"
                else:
                    symbol_with_prefix = f"sh{symbol}"
                
                price_df = ak.stock_zh_index_daily(symbol=symbol_with_prefix)
                if not price_df.empty:
                    # 过滤出该月的数据
                    price_df['日期'] = pd.to_datetime(price_df.get('date', price_df.get('日期', price_df.index)))
                    price_df = price_df[
                        (price_df['日期'].dt.year == year) & 
                        (price_df['日期'].dt.month == month)
                    ]
                    if not price_df.empty:
                        print(f"[DEBUG] 方法2成功，获取 {len(price_df)} 条记录")
            except Exception as e:
                price_df = None
        
        if price_df is None or price_df.empty:
            result['error'] = '无法获取数据'
            return result
        
        # 处理日期列
        date_col = None
        for col in price_df.columns:
            col_str = str(col).lower()
            if '日期' in col_str or 'date' in col_str:
                date_col = col
                break
        
        if date_col:
            price_df[date_col] = pd.to_datetime(price_df[date_col], errors='coerce')
            if date_col != '日期':
                price_df.rename(columns={date_col: '日期'}, inplace=True)
        else:
            result['error'] = '无法识别日期列'
            return result
        
        price_df = price_df.dropna(subset=['日期'])
        price_df = price_df.sort_values('日期')
        
        # 找到收盘价列
        close_col = None
        for col in price_df.columns:
            col_str = str(col).lower()
            if '收盘' in col_str or 'close' in col_str:
                close_col = col
                break
        
        if not close_col:
            result['error'] = '无法识别收盘价列'
            return result
        
        # 存储到数据库
        if DB_AVAILABLE:
            from .db import save_price_batch, save_month_record
            
            price_data_list = []
            for _, row in price_df.iterrows():
                open_val = row.get('open') if 'open' in row.index else (row.get('开盘') if '开盘' in row.index else None)
                high_val = row.get('high') if 'high' in row.index else (row.get('最高') if '最高' in row.index else None)
                low_val = row.get('low') if 'low' in row.index else (row.get('最低') if '最低' in row.index else None)
                volume_val = row.get('volume') if 'volume' in row.index else (row.get('成交量') if '成交量' in row.index else None)
                
                symbol_title = get_symbol_title(symbol)
                price_data = {
                    'symbol': symbol,
                    'symbol_title': symbol_title,
                    'trade_date': row['日期'].strftime('%Y-%m-%d'),
                    'open_price': float(open_val) if pd.notna(open_val) else None,
                    'high_price': float(high_val) if pd.notna(high_val) else None,
                    'low_price': float(low_val) if pd.notna(low_val) else None,
                    'close_price': float(row[close_col]) if pd.notna(row[close_col]) else None,
                    'volume': int(volume_val) if pd.notna(volume_val) else None,
                }
                if price_data['close_price'] is not None:
                    price_data_list.append(price_data)
            
            if price_data_list:
                saved_count = save_price_batch(price_data_list)
                symbol_title = get_symbol_title(symbol)
                save_month_record(symbol, symbol_title, symbol_type, year, month)
                result['records'] = saved_count
                result['success'] = True
            else:
                result['error'] = '没有有效数据'
        else:
            result['records'] = len(price_df)
            result['success'] = True
        
        return result
        
    except Exception as e:
        result['error'] = str(e)
        return result


def get_sector_valuation_data(
    symbol: str,
    periods: List[str] = ['1m', '3m', '6m', '1y', '3y', '5y']
) -> Dict[str, Dict]:
    """
    获取板块估值数据（PE、PB等）的历史分位数
    
    Args:
        symbol: 板块代码，如 "中证消费"、"中证医药"、"恒生科技" 等
        periods: 时间周期列表，默认获取所有周期
    
    Returns:
        包含各周期估值数据的字典
    """
    result = {}
    
    try:
        # 获取板块估值历史数据
        print(f"[INFO] 正在获取 {symbol} 的估值数据...")
        
        # 方法1: 使用 index_value_hist_funddb 获取估值历史
        try:
            valuation_df = ak.index_value_hist_funddb(symbol=symbol)
            print(f"[OK] 成功获取 {symbol} 的估值数据，共 {len(valuation_df)} 条记录")
        except Exception as e:
            print(f"[WARNING] 方法1失败: {e}，尝试其他方法...")
            try:
                valuation_df = ak.tool_trade_date_hist_sina()
                raise Exception("需要根据实际板块代码调整接口")
            except Exception as e2:
                print(f"[ERROR] 无法获取 {symbol} 的估值数据: {e2}")
                return result
        
        if valuation_df.empty:
            print(f"[WARNING] {symbol} 的估值数据为空")
            return result
        
        # 确保日期列为datetime类型
        if '日期' in valuation_df.columns:
            valuation_df['日期'] = pd.to_datetime(valuation_df['日期'])
        elif 'date' in valuation_df.columns:
            valuation_df['date'] = pd.to_datetime(valuation_df['date'])
            valuation_df.rename(columns={'date': '日期'}, inplace=True)
        
        # 按日期排序
        valuation_df = valuation_df.sort_values('日期')
        
        # 获取当前日期
        today = datetime.now()
        
        # 计算各周期的数据
        for period in periods:
            if period not in TIME_PERIODS:
                continue
            
            months = TIME_PERIODS[period]
            cutoff_date = today - timedelta(days=months * 30)  # 近似计算
            
            # 筛选该周期内的数据
            period_data = valuation_df[valuation_df['日期'] >= cutoff_date].copy()
            
            if period_data.empty:
                print(f"[WARNING] {period} 周期内无数据")
                continue
            
            # 提取PE和PB数据（列名可能不同，需要适配）
            pe_col = None
            pb_col = None
            
            # 尝试找到PE列
            for col in valuation_df.columns:
                col_lower = str(col).lower()
                if 'pe' in col_lower or '市盈率' in col_lower:
                    pe_col = col
                if 'pb' in col_lower or '市净率' in col_lower:
                    pb_col = col
            
            period_result = {
                'data_points': len(period_data),
                'start_date': period_data['日期'].min().strftime('%Y-%m-%d'),
                'end_date': period_data['日期'].max().strftime('%Y-%m-%d'),
            }
            
            # 计算PE统计信息
            if pe_col and pe_col in period_data.columns:
                pe_values = pd.to_numeric(period_data[pe_col], errors='coerce').dropna()
                if not pe_values.empty:
                    current_pe = pe_values.iloc[-1] if len(pe_values) > 0 else None
                    min_pe = pe_values.min()
                    max_pe = pe_values.max()
                    percentile = (pe_values <= current_pe).sum() / len(pe_values) if current_pe else None
                    
                    period_result['pe'] = {
                        'current': float(current_pe) if current_pe else None,
                        'min': float(min_pe),
                        'max': float(max_pe),
                        'percentile': float(percentile) if percentile else None,
                        'mean': float(pe_values.mean()),
                        'median': float(pe_values.median()),
                    }
            
            # 计算PB统计信息
            if pb_col and pb_col in period_data.columns:
                pb_values = pd.to_numeric(period_data[pb_col], errors='coerce').dropna()
                if not pb_values.empty:
                    current_pb = pb_values.iloc[-1] if len(pb_values) > 0 else None
                    min_pb = pb_values.min()
                    max_pb = pb_values.max()
                    percentile = (pb_values <= current_pb).sum() / len(pb_values) if current_pb else None
                    
                    period_result['pb'] = {
                        'current': float(current_pb) if current_pb else None,
                        'min': float(min_pb),
                        'max': float(max_pb),
                        'percentile': float(percentile) if percentile else None,
                        'mean': float(pb_values.mean()),
                        'median': float(pb_values.median()),
                    }
            
            result[period] = period_result
            print(f"[OK] {period} 周期数据: {len(period_data)} 个数据点")
        
        return result
        
    except Exception as e:
        print(f"[ERROR] 获取 {symbol} 估值数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return result


def get_sector_price_data(
    symbol: str,
    periods: List[str] = ['1m', '3m', '6m', '1y', '3y', '5y']
) -> Dict[str, Dict]:
    """
    获取板块价格数据（指数点位、涨跌幅等）
    
    Args:
        symbol: 板块代码，如 "000300" (沪深300)、"399006" (创业板指) 等
        periods: 时间周期列表
    
    Returns:
        包含各周期价格数据的字典
    """
    result = {}
    
    try:
        print(f"[INFO] 正在获取 {symbol} 的价格数据...")
        
        # 检查是否需要获取当前月份数据
        need_fetch = True
        if DB_AVAILABLE:
            try:
                # 初始化数据库表（如果不存在）
                init_tables()
                # 检查当前月份数据是否存在
                need_fetch = should_fetch_current_month_data(symbol)
            except Exception as e:
                print(f"[WARNING] 数据库检查失败，将继续获取数据: {e}")
                need_fetch = True
        
        if not need_fetch:
            print(f"[INFO] 当前月份数据已存在，从数据库读取")
            # 从数据库读取数据并计算收益率
            if DB_AVAILABLE:
                try:
                    # 获取所有历史数据（从数据库和API）
                    # 先尝试从数据库获取足够的历史数据
                    db_prices = get_current_month_prices_from_db(symbol)
                    if db_prices:
                        # 如果有数据库数据，仍然需要获取历史数据来计算收益率
                        # 所以继续执行下面的获取逻辑
                        print(f"[INFO] 从数据库读取到 {len(db_prices)} 条当前月数据，继续获取历史数据以计算收益率")
                    else:
                        print(f"[INFO] 数据库中没有数据，继续获取")
                except Exception as e:
                    print(f"[WARNING] 从数据库读取失败: {e}，继续获取数据")
            # 继续执行获取逻辑，因为需要历史数据来计算收益率
        
        # 获取指数历史行情数据
        max_months = max([TIME_PERIODS[p] for p in periods if p in TIME_PERIODS], default=60)
        days_back = max_months * 30
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
        end_date = datetime.now().strftime('%Y%m%d')
        
        price_df = None
        
        # 方法1: 使用 index_zh_a_hist 接口（最常用）
        try:
            print(f"[INFO] 尝试方法1: index_zh_a_hist (日期范围: {start_date} ~ {end_date})")
            price_df = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date)
            if not price_df.empty:
                print(f"[OK] 方法1成功，获取 {len(price_df)} 条记录")
        except Exception as e:
            print(f"[WARNING] 方法1失败: {str(e)[:100]}...")
            price_df = None
        
        # 方法2: 使用 stock_zh_index_daily（需要添加市场前缀）
        if price_df is None or price_df.empty:
            try:
                print(f"[INFO] 尝试方法2: stock_zh_index_daily")
                if symbol.startswith('000'):
                    symbol_with_prefix = f"sh{symbol}"
                elif symbol.startswith('399'):
                    symbol_with_prefix = f"sz{symbol}"
                elif symbol.startswith('00') and len(symbol) == 6:
                    symbol_with_prefix = f"sh{symbol}"
                else:
                    symbol_with_prefix = f"sh{symbol}"
                
                print(f"[DEBUG] 使用市场前缀: {symbol_with_prefix}")
                price_df = ak.stock_zh_index_daily(symbol=symbol_with_prefix)
                if not price_df.empty:
                    print(f"[OK] 方法2成功，获取 {len(price_df)} 条记录")
            except Exception as e:
                print(f"[WARNING] 方法2失败: {str(e)[:100]}...")
                try:
                    if symbol_with_prefix.startswith('sh'):
                        symbol_with_prefix = f"sz{symbol}"
                    else:
                        symbol_with_prefix = f"sh{symbol}"
                    print(f"[INFO] 尝试另一个市场: {symbol_with_prefix}")
                    price_df = ak.stock_zh_index_daily(symbol=symbol_with_prefix)
                    if not price_df.empty:
                        print(f"[OK] 方法2（备用市场）成功，获取 {len(price_df)} 条记录")
                except Exception as e2:
                    print(f"[WARNING] 备用市场也失败: {str(e2)[:100]}...")
                    price_df = None
        
        # 方法3: 使用 index_zh_a_hist_min_em
        if price_df is None or price_df.empty:
            try:
                print(f"[INFO] 尝试方法3: index_zh_a_hist_min_em")
                if hasattr(ak, 'index_zh_a_hist_min_em'):
                    price_df = ak.index_zh_a_hist_min_em(symbol=symbol, period="daily", adjust="")
                    if not price_df.empty:
                        print(f"[OK] 方法3成功，获取 {len(price_df)} 条记录")
            except Exception as e:
                print(f"[WARNING] 方法3失败: {str(e)[:100]}...")
                price_df = None
        
        # 方法4: 使用实时数据接口
        if price_df is None or price_df.empty:
            try:
                print(f"[INFO] 尝试方法4: 通过实时数据接口")
                spot_data = ak.stock_zh_index_spot()
                if spot_data is not None and not spot_data.empty:
                    price_df = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date="", end_date="")
                    if not price_df.empty:
                        print(f"[OK] 方法4成功，获取 {len(price_df)} 条记录")
            except Exception as e:
                print(f"[WARNING] 方法4失败: {str(e)[:100]}...")
                price_df = None
        
        if price_df is None or price_df.empty:
            print(f"[ERROR] 所有方法都失败，无法获取 {symbol} 的价格数据")
            return result
        
        # 处理日期列
        date_col = None
        for col in price_df.columns:
            col_str = str(col).lower()
            if '日期' in col_str or 'date' in col_str or '时间' in col_str or 'time' in col_str:
                date_col = col
                break
        
        if date_col:
            price_df[date_col] = pd.to_datetime(price_df[date_col], errors='coerce')
            if date_col != '日期':
                price_df.rename(columns={date_col: '日期'}, inplace=True)
        else:
            first_col = price_df.columns[0]
            print(f"[WARNING] 未找到日期列，使用第一列: {first_col}")
            price_df.rename(columns={first_col: '日期'}, inplace=True)
            price_df['日期'] = pd.to_datetime(price_df['日期'], errors='coerce')
        
        price_df = price_df.dropna(subset=['日期'])
        price_df = price_df.sort_values('日期')
        today = datetime.now()
        
        # 找到收盘价列
        close_col = None
        for col in price_df.columns:
            col_str = str(col).lower()
            if '收盘' in col_str or 'close' in col_str or '收' in col_str:
                close_col = col
                break
        
        if not close_col:
            for possible_col in ['收盘', 'close', '收盘价', 'CLOSE', 'close_price']:
                if possible_col in price_df.columns:
                    close_col = possible_col
                    break
        
        if not close_col:
            numeric_cols = price_df.select_dtypes(include=['float64', 'int64']).columns.tolist()
            if '日期' in numeric_cols:
                numeric_cols.remove('日期')
            if numeric_cols:
                close_col = numeric_cols[0] if numeric_cols else None
                print(f"[WARNING] 未找到明确的收盘价列，使用数值列: {close_col}")
        
        if not close_col:
            print(f"[ERROR] 未找到收盘价列，可用列: {list(price_df.columns)}")
            return result
        
        # 存储数据到数据库（仅存储当前月份的数据）
        if DB_AVAILABLE and need_fetch:
            try:
                now = datetime.now()
                current_year = now.year
                current_month = now.month
                
                current_month_data = price_df[
                    (price_df['日期'].dt.year == current_year) & 
                    (price_df['日期'].dt.month == current_month)
                ].copy()
                
                if not current_month_data.empty:
                    price_data_list = []
                    for _, row in current_month_data.iterrows():
                        open_val = row.get('open') if 'open' in row.index else (row.get('开盘') if '开盘' in row.index else None)
                        high_val = row.get('high') if 'high' in row.index else (row.get('最高') if '最高' in row.index else None)
                        low_val = row.get('low') if 'low' in row.index else (row.get('最低') if '最低' in row.index else None)
                        volume_val = row.get('volume') if 'volume' in row.index else (row.get('成交量') if '成交量' in row.index else None)
                        
                        symbol_title = get_symbol_title(symbol)
                        price_data = {
                            'symbol': symbol,
                            'symbol_title': symbol_title,
                            'trade_date': row['日期'].strftime('%Y-%m-%d'),
                            'open_price': float(open_val) if pd.notna(open_val) else None,
                            'high_price': float(high_val) if pd.notna(high_val) else None,
                            'low_price': float(low_val) if pd.notna(low_val) else None,
                            'close_price': float(row[close_col]) if pd.notna(row[close_col]) else None,
                            'volume': int(volume_val) if pd.notna(volume_val) else None,
                        }
                        if price_data['close_price'] is not None:
                            price_data_list.append(price_data)
                    
                    if price_data_list:
                        saved_count = save_price_batch(price_data_list)
                        print(f"[OK] 已保存 {saved_count} 条当前月份价格数据到数据库")
                        symbol_title = get_symbol_title(symbol)
                        save_month_record(symbol, symbol_title, 'index', current_year, current_month)
                        print(f"[OK] 已保存月份记录: {symbol} {current_year}年{current_month}月")
                        
            except Exception as e:
                print(f"[WARNING] 保存数据到数据库失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 计算各周期的数据
        for period in periods:
            if period not in TIME_PERIODS:
                continue
            
            months = TIME_PERIODS[period]
            if period == '1y':
                target_days = 365
            elif period == '3y':
                target_days = 1095
            elif period == '5y':
                target_days = 1825
            else:
                target_days = months * 30
            
            target_date = today - timedelta(days=target_days)
            period_data = price_df[price_df['日期'] >= target_date].copy()
            
            if period_data.empty:
                print(f"[WARNING] {period} 周期内无价格数据")
                continue
            
            prices = pd.to_numeric(period_data[close_col], errors='coerce').dropna()
            dates = period_data.loc[prices.index, '日期']
            
            if prices.empty or len(prices) < 2:
                print(f"[WARNING] {period} 周期数据点不足")
                continue
            
            current_price = prices.iloc[-1]
            current_date = dates.iloc[-1]
            
            date_diff = (dates - target_date).abs()
            closest_idx = date_diff.idxmin()
            start_price = prices.loc[closest_idx]
            start_date = dates.loc[closest_idx]
            
            if start_date >= current_date:
                print(f"[WARNING] {period} 周期数据不足")
                continue
            
            if current_price < 10 and symbol.startswith('00'):
                print(f"[WARNING] {period} 周期价格异常低 ({current_price:.2f})")
            
            min_price = prices.min()
            max_price = prices.max()
            change_pct = ((current_price - start_price) / start_price * 100) if start_price > 0 else 0
            
            if abs(change_pct) > 100 and period in ['1y', '3y', '5y']:
                print(f"[WARNING] {period} 周期涨跌幅异常 ({change_pct:.2f}%)")
            
            period_result = {
                'current_price': float(current_price),
                'start_price': float(start_price),
                'min_price': float(min_price),
                'max_price': float(max_price),
                'change_pct': float(change_pct),
                'data_points': len(period_data),
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': current_date.strftime('%Y-%m-%d'),
            }
            
            result[period] = period_result
            print(f"[OK] {period} 周期价格数据: 起始 {start_date.strftime('%Y-%m-%d')} ({start_price:.2f}) -> 当前 {current_date.strftime('%Y-%m-%d')} ({current_price:.2f}), 涨跌幅 {change_pct:.2f}%")
        
        return result
        
    except Exception as e:
        print(f"[ERROR] 获取 {symbol} 价格数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return result


def get_sector_comprehensive_data(
    symbol: str,
    symbol_type: str = 'index',
    periods: List[str] = ['1m', '3m', '6m', '1y', '3y', '5y']
) -> Dict:
    """
    获取板块综合数据（估值 + 价格）
    """
    symbol_title = get_symbol_title(symbol, symbol_type)
    result = {
        'symbol': symbol,
        'symbol_title': symbol_title,
        'symbol_type': symbol_type,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'valuation': {},
        'price': {},
    }
    
    if symbol_type == 'sector':
        print(f"\n{'='*50}")
        print(f"获取板块估值数据: {symbol}")
        print(f"{'='*50}")
        result['valuation'] = get_sector_valuation_data(symbol, periods)
        time.sleep(1)
    
    if symbol_type == 'index':
        print(f"\n{'='*50}")
        print(f"获取指数价格数据: {symbol}")
        print(f"{'='*50}")
        result['price'] = get_sector_price_data(symbol, periods)
        time.sleep(1)
    
    return result


def format_analysis_result(data: Dict) -> str:
    """
    格式化分析结果为可读文本
    """
    lines = []
    lines.append(f"\n{'='*60}")
    symbol_title = data.get('symbol_title', data.get('symbol', 'N/A'))
    lines.append(f"板块/指数: {symbol_title} ({data.get('symbol', 'N/A')}) ({data.get('symbol_type', 'N/A')})")
    lines.append(f"更新时间: {data.get('timestamp', 'N/A')}")
    lines.append(f"{'='*60}\n")
    
    if data.get('valuation'):
        lines.append("【估值数据】")
        for period, period_data in data['valuation'].items():
            lines.append(f"\n  {period.upper()} 周期 ({period_data.get('start_date')} ~ {period_data.get('end_date')}):")
            lines.append(f"    数据点数: {period_data.get('data_points', 0)}")
            
            if 'pe' in period_data:
                pe = period_data['pe']
                lines.append(f"    PE (市盈率):")
                lines.append(f"      当前值: {pe.get('current', 'N/A'):.2f}")
                lines.append(f"      历史分位: {pe.get('percentile', 0)*100:.1f}%")
                lines.append(f"      范围: {pe.get('min', 'N/A'):.2f} ~ {pe.get('max', 'N/A'):.2f}")
                lines.append(f"      均值: {pe.get('mean', 'N/A'):.2f}, 中位数: {pe.get('median', 'N/A'):.2f}")
            
            if 'pb' in period_data:
                pb = period_data['pb']
                lines.append(f"    PB (市净率):")
                lines.append(f"      当前值: {pb.get('current', 'N/A'):.2f}")
                lines.append(f"      历史分位: {pb.get('percentile', 0)*100:.1f}%")
                lines.append(f"      范围: {pb.get('min', 'N/A'):.2f} ~ {pb.get('max', 'N/A'):.2f}")
                lines.append(f"      均值: {pb.get('mean', 'N/A'):.2f}, 中位数: {pb.get('median', 'N/A'):.2f}")
    
    if data.get('price'):
        lines.append("\n【价格数据】")
        for period, period_data in data['price'].items():
            lines.append(f"\n  {period.upper()} 周期 ({period_data.get('start_date')} ~ {period_data.get('end_date')}):")
            lines.append(f"    数据点数: {period_data.get('data_points', 0)}")
            lines.append(f"    当前价格: {period_data.get('current_price', 'N/A'):.2f}")
            lines.append(f"    起始价格: {period_data.get('start_price', 'N/A'):.2f}")
            lines.append(f"    涨跌幅: {period_data.get('change_pct', 0):.2f}%")
            lines.append(f"    价格范围: {period_data.get('min_price', 'N/A'):.2f} ~ {period_data.get('max_price', 'N/A'):.2f}")
    
    lines.append(f"\n{'='*60}\n")
    return "\n".join(lines)


def get_fund_return_rate(
    fund_code: str,
    periods: List[str] = ['1m', '3m', '6m', '1y', '3y', '5y']
) -> Dict:
    """
    获取基金收益率数据（支持ETF基金和指数）
    
    Args:
        fund_code: 基金代码或指数代码
            - ETF基金代码，如 "513050" (中概互联ETF), "510300" (沪深300ETF)
            - 指数代码，如 "000300" (沪深300), "000016" (上证50)
        periods: 时间周期列表，默认获取所有周期
    
    Returns:
        包含各周期收益率数据的字典，包含 symbol, symbol_title, symbol_type 等字段
    """
    result = {
        'symbol': fund_code,
        'symbol_title': get_symbol_title(fund_code),
        'symbol_type': 'etf' if (len(fund_code) == 6 and fund_code.isdigit() and fund_code.startswith(('51', '15', '16'))) else 'index',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'returns': {}
    }
    
    try:
        print(f"[INFO] 正在获取 {fund_code} ({result['symbol_title']}) 的收益率数据...")
        
        # 判断是指数还是基金
        # 如果是6位数字代码，可能是ETF基金
        is_etf = len(fund_code) == 6 and fund_code.isdigit() and fund_code.startswith(('51', '15', '16'))
        
        if is_etf:
            # 获取ETF基金数据
            etf_data = _get_etf_return_rate(fund_code, periods)
            result['returns'] = etf_data
        else:
            # 获取指数数据（使用现有的价格数据函数，收益率就是涨跌幅）
            price_data = get_sector_price_data(fund_code, periods)
            
            # 转换为收益率格式
            for period, period_data in price_data.items():
                result['returns'][period] = {
                    'return_rate': period_data.get('change_pct', 0),  # 收益率百分比
                    'current_price': period_data.get('current_price', 0),
                    'start_price': period_data.get('start_price', 0),
                    'start_date': period_data.get('start_date', ''),
                    'end_date': period_data.get('end_date', ''),
                    'data_points': period_data.get('data_points', 0),
                }
            
        return result
            
    except Exception as e:
        print(f"[ERROR] 获取 {fund_code} 收益率数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return result


def _get_etf_return_rate(
    etf_code: str,
    periods: List[str] = ['1m', '3m', '6m', '1y', '3y', '5y']
) -> Dict[str, Dict]:
    """
    获取ETF基金收益率数据（内部函数）
    """
    result = {}
    etf_df = None
    date_col = None
    close_col = None
    
    try:
        # 方法1: 使用 fund_etf_hist_sina 获取ETF历史数据（不传period参数）
        try:
            print(f"[INFO] 尝试方法1: fund_etf_hist_sina")
            etf_df = ak.fund_etf_hist_sina(symbol=etf_code)
            
            if etf_df.empty:
                raise Exception("数据为空")
            
            # 标准化列名
            date_col = None
            close_col = None
            
            for col in etf_df.columns:
                col_lower = str(col).lower()
                if 'date' in col_lower or '日期' in col_lower or 'time' in col_lower or '时间' in col_lower:
                    date_col = col
                if 'close' in col_lower or '收盘' in col_lower or '净值' in col_lower or 'net' in col_lower:
                    close_col = col
            
            if date_col is None or close_col is None:
                raise Exception(f"无法识别日期列或收盘价列，列名: {list(etf_df.columns)}")
            
            # 转换日期列
            etf_df[date_col] = pd.to_datetime(etf_df[date_col])
            etf_df = etf_df.sort_values(date_col)
            
            # 转换价格列
            etf_df[close_col] = pd.to_numeric(etf_df[close_col], errors='coerce')
            etf_df = etf_df.dropna(subset=[date_col, close_col])
            
            if etf_df.empty:
                raise Exception("数据清洗后为空")
            
            print(f"[OK] 方法1成功，获取 {len(etf_df)} 条记录")
            
        except Exception as e1:
            print(f"[WARNING] 方法1失败: {e1}，尝试其他方法...")
            
            # 方法2: 使用股票接口获取ETF数据（ETF也是可交易的）
            try:
                print(f"[INFO] 尝试方法2: 使用股票接口获取ETF数据")
                # ETF代码需要添加市场前缀
                if etf_code.startswith('51'):
                    symbol_with_prefix = f"sh{etf_code}"
                elif etf_code.startswith('15') or etf_code.startswith('16'):
                    symbol_with_prefix = f"sz{etf_code}"
                else:
                    symbol_with_prefix = f"sh{etf_code}"
                
                etf_df = ak.stock_zh_a_hist(symbol=symbol_with_prefix, period="daily", adjust="")
                
                if etf_df.empty:
                    raise Exception("数据为空")
                
                # 标准化列名
                date_col = None
                close_col = None
                
                for col in etf_df.columns:
                    col_lower = str(col).lower()
                    if 'date' in col_lower or '日期' in col_lower:
                        date_col = col
                    if 'close' in col_lower or '收盘' in col_lower:
                        close_col = col
                
                if date_col is None or close_col is None:
                    raise Exception(f"无法识别日期列或收盘价列，列名: {list(etf_df.columns)}")
                
                # 转换日期列
                etf_df[date_col] = pd.to_datetime(etf_df[date_col])
                etf_df = etf_df.sort_values(date_col)
                
                # 转换价格列
                etf_df[close_col] = pd.to_numeric(etf_df[close_col], errors='coerce')
                etf_df = etf_df.dropna(subset=[date_col, close_col])
                
                if etf_df.empty:
                    raise Exception("数据清洗后为空")
                
                print(f"[OK] 方法2成功，获取 {len(etf_df)} 条记录")
                
            except Exception as e2:
                print(f"[WARNING] 方法2失败: {e2}，尝试方法3...")
                
                # 方法3: 使用基金净值接口（适用于QDII基金等）
                try:
                    print(f"[INFO] 尝试方法3: 使用基金净值接口 fund_em_fund_info")
                    # 先获取基金信息，找到基金代码
                    fund_info = ak.fund_em_fund_info(fund=etf_code, indicator="单位净值走势")
                    if not fund_info.empty:
                        # 查找日期和净值列
                        date_col = None
                        close_col = None
                        for col in fund_info.columns:
                            col_lower = str(col).lower()
                            if 'date' in col_lower or '日期' in col_lower or 'time' in col_lower or '时间' in col_lower:
                                date_col = col
                            if '净值' in col_lower or 'net' in col_lower or 'value' in col_lower or '单位净值' in col_lower:
                                close_col = col
                        
                        if date_col and close_col:
                            etf_df = fund_info[[date_col, close_col]].copy()
                            etf_df.rename(columns={date_col: '日期', close_col: '收盘'}, inplace=True)
                            etf_df['日期'] = pd.to_datetime(etf_df['日期'], errors='coerce')
                            etf_df['收盘'] = pd.to_numeric(etf_df['收盘'], errors='coerce')
                            etf_df = etf_df.dropna(subset=['日期', '收盘'])
                            etf_df = etf_df.sort_values('日期')
                            
                            if not etf_df.empty:
                                date_col = '日期'
                                close_col = '收盘'
                                print(f"[OK] 方法3成功，获取 {len(etf_df)} 条记录")
                            else:
                                raise Exception("数据清洗后为空")
                        else:
                            raise Exception(f"无法识别日期列或净值列，列名: {list(fund_info.columns)}")
                    else:
                        raise Exception("数据为空")
                        
                except Exception as e3:
                    print(f"[WARNING] 方法3失败: {e3}，尝试方法4...")
                    
                    # 方法4: 使用基金实时行情接口
                    try:
                        print(f"[INFO] 尝试方法4: 使用基金实时行情接口 fund_etf_spot_em")
                        spot_df = ak.fund_etf_spot_em()
                        if not spot_df.empty:
                            # 查找对应的ETF
                            etf_row = spot_df[spot_df['代码'] == etf_code]
                            if not etf_row.empty:
                                # 获取基金代码（可能是6位数字）
                                fund_code = etf_row.iloc[0].get('基金代码', etf_code)
                                # 再次尝试使用基金净值接口
                                fund_info = ak.fund_em_fund_info(fund=fund_code, indicator="单位净值走势")
                                if not fund_info.empty:
                                    # 处理数据（同方法3）
                                    date_col = None
                                    close_col = None
                                    for col in fund_info.columns:
                                        col_lower = str(col).lower()
                                        if 'date' in col_lower or '日期' in col_lower:
                                            date_col = col
                                        if '净值' in col_lower or 'net' in col_lower or '单位净值' in col_lower:
                                            close_col = col
                                    
                                    if date_col and close_col:
                                        etf_df = fund_info[[date_col, close_col]].copy()
                                        etf_df.rename(columns={date_col: '日期', close_col: '收盘'}, inplace=True)
                                        etf_df['日期'] = pd.to_datetime(etf_df['日期'], errors='coerce')
                                        etf_df['收盘'] = pd.to_numeric(etf_df['收盘'], errors='coerce')
                                        etf_df = etf_df.dropna(subset=['日期', '收盘'])
                                        etf_df = etf_df.sort_values('日期')
                                        
                                        if not etf_df.empty:
                                            date_col = '日期'
                                            close_col = '收盘'
                                            print(f"[OK] 方法4成功，获取 {len(etf_df)} 条记录")
                                        else:
                                            raise Exception("数据清洗后为空")
                                    else:
                                        raise Exception(f"无法识别日期列或净值列")
                                else:
                                    raise Exception("基金净值数据为空")
                            else:
                                raise Exception(f"未找到代码为 {etf_code} 的ETF")
                        else:
                            raise Exception("实时行情数据为空")
                            
                    except Exception as e4:
                        print(f"[WARNING] 方法4失败: {e4}，尝试方法5...")
                        
                        # 方法5: 使用ETF对应的指数代码（最后备选方案）
                        # 中概互联ETF对应中概互联指数，但指数代码可能不同
                        # 这里提供一个映射，如果ETF获取失败，可以尝试使用指数
                        etf_to_index_map = {
                            '513050': 'HSTECH',  # 中概互联ETF -> 恒生科技指数（近似）
                            '510300': '000300',  # 沪深300ETF -> 沪深300
                            '510500': '000905',  # 中证500ETF -> 中证500
                            '159915': '399006',  # 创业板ETF -> 创业板指
                        }
                        
                        if etf_code in etf_to_index_map:
                            index_code = etf_to_index_map[etf_code]
                            print(f"[INFO] 方法5: ETF获取失败，尝试使用对应指数代码 {index_code}")
                            print(f"[WARNING] 注意: 这是指数数据，可能与ETF净值有差异")
                            # 使用指数数据获取函数（避免循环导入，直接调用）
                            index_data = get_sector_price_data(index_code, periods)
                            if index_data:
                                # 转换为ETF格式
                                for period, period_data in index_data.items():
                                    result[period] = {
                                        'return_rate': period_data.get('change_pct', 0),
                                        'current_price': period_data.get('current_price', 0),
                                        'start_price': period_data.get('start_price', 0),
                                        'start_date': period_data.get('start_date', ''),
                                        'end_date': period_data.get('end_date', ''),
                                        'data_points': period_data.get('data_points', 0),
                                    }
                                print(f"[OK] 方法5成功，使用指数数据作为替代")
                                return result
                        
                        print(f"[ERROR] 所有方法都失败，无法获取 {etf_code} 的ETF数据")
                        print(f"[INFO] 提示: 可以尝试使用对应的指数代码，如中概互联ETF(513050)可以使用恒生科技指数(HSTECH)或中概互联指数")
                        return result
        
        # 检查是否成功获取了数据
        if etf_df is None or etf_df.empty or date_col is None or close_col is None:
            print(f"[ERROR] 未能成功获取 {etf_code} 的数据")
            return result
        
        # 计算各周期的收益率
        today = datetime.now()
        
        for period in periods:
            if period not in TIME_PERIODS:
                continue
            
            months = TIME_PERIODS[period]
            if period == '1y':
                target_days = 365
            elif period == '3y':
                target_days = 1095
            elif period == '5y':
                target_days = 1825
            else:
                target_days = months * 30
            
            target_date = today - timedelta(days=target_days)
            period_data = etf_df[etf_df[date_col] >= target_date].copy()
            
            if period_data.empty:
                print(f"[WARNING] {period} 周期内无数据")
                continue
            
            prices = period_data[close_col].values
            dates = period_data[date_col].values
            
            if len(prices) < 2:
                print(f"[WARNING] {period} 周期数据点不足")
                continue
            
            current_price = prices[-1]
            current_date = dates[-1]
            
            # 找到最接近目标日期的价格
            date_diffs = [(abs((d - target_date).days), idx) for idx, d in enumerate(dates)]
            date_diffs.sort()
            start_idx = date_diffs[0][1] if date_diffs else 0
            start_price = prices[start_idx]
            start_date = dates[start_idx]
            
            if start_date >= current_date:
                print(f"[WARNING] {period} 周期数据不足")
                continue
            
            # 计算收益率
            return_rate = ((current_price - start_price) / start_price * 100) if start_price > 0 else 0
            
            result[period] = {
                'return_rate': float(return_rate),
                'current_price': float(current_price),
                'start_price': float(start_price),
                'start_date': pd.Timestamp(start_date).strftime('%Y-%m-%d'),
                'end_date': pd.Timestamp(current_date).strftime('%Y-%m-%d'),
                'data_points': len(period_data),
            }
            
            print(f"[OK] {period} 周期收益率: 起始 {pd.Timestamp(start_date).strftime('%Y-%m-%d')} ({start_price:.4f}) -> 当前 {pd.Timestamp(current_date).strftime('%Y-%m-%d')} ({current_price:.4f}), 收益率 {return_rate:.2f}%")
        
        return result
        
    except Exception as e:
        print(f"[ERROR] 获取ETF收益率数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return result


# 常用板块代码映射
COMMON_SECTORS = {
    '沪深300': {'code': '000300', 'type': 'index'},
    '上证50': {'code': '000016', 'type': 'index'},
    '中证500': {'code': '000905', 'type': 'index'},
    '创业板指': {'code': '399006', 'type': 'index'},
    '科创50': {'code': '000688', 'type': 'index'},
    '中证2000': {'code': '000932', 'type': 'index'},
    '中概互联': {'code': '513050', 'type': 'etf'},  # 中概互联ETF
    '恒生指数': {'code': 'HSI', 'type': 'index'},
    '恒生科技': {'code': 'HSTECH', 'type': 'index'},
    '国企指数': {'code': 'HSCEI', 'type': 'index'},
    '中证消费': {'code': '中证消费', 'type': 'sector'},
    '中证医药': {'code': '中证医药', 'type': 'sector'},
    '中证银行': {'code': '中证银行', 'type': 'sector'},
}

# 常用基金代码映射（ETF）
COMMON_FUNDS = {
    '中概互联': '513050',  # 中概互联ETF
    '沪深300ETF': '510300',  # 沪深300ETF
    '中证500ETF': '510500',  # 中证500ETF
    '创业板ETF': '159915',  # 创业板ETF
    '中证2000ETF': '159531',  # 中证2000ETF（示例，需确认实际代码）
}


def get_symbol_title(symbol: str, symbol_type: str = None) -> str:
    """
    根据代码获取完整名称
    
    Args:
        symbol: 代码
        symbol_type: 类型（可选，用于辅助判断）
    
    Returns:
        完整名称，如果找不到则返回代码本身
    """
    # 先从 COMMON_SECTORS 查找
    for name, info in COMMON_SECTORS.items():
        if info['code'] == symbol:
            return name
    
    # 从 COMMON_FUNDS 查找（反向查找）
    for name, code in COMMON_FUNDS.items():
        if code == symbol:
            return name
    
    # 如果找不到，返回代码本身
    return symbol

