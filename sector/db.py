"""
板块数据数据库存储模块
负责将板块数据存储到MySQL数据库
"""
import pymysql
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import sys
import os
import sys as sys_module

# 添加父目录到路径，以便导入config
sys_module.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

# 设置输出编码为UTF-8（Windows，安全方式）
if sys.platform == 'win32':
    try:
        import io
        if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer is not None and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'buffer') and sys.stderr.buffer is not None and not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass


def get_db_connection():
    """
    获取数据库连接
    
    Returns:
        pymysql.Connection: 数据库连接对象
    """
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {e}")
        raise


def init_tables():
    """
    初始化数据库表结构
    创建月份表和价格表
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # 创建月份表
            create_month_table_sql = """
            CREATE TABLE IF NOT EXISTS sector_months (
                id INT AUTO_INCREMENT PRIMARY KEY,
                symbol VARCHAR(50) NOT NULL COMMENT '板块/指数代码',
                symbol_title VARCHAR(100) COMMENT '板块/指数完整名称',
                symbol_type VARCHAR(20) NOT NULL COMMENT '类型: index(指数) 或 sector(板块)',
                year INT NOT NULL COMMENT '年份',
                month INT NOT NULL COMMENT '月份 (1-12)',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                UNIQUE KEY uk_symbol_year_month (symbol, year, month),
                INDEX idx_symbol (symbol),
                INDEX idx_year_month (year, month)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='板块月份表';
            """
            cursor.execute(create_month_table_sql)
            
            # 创建价格表
            create_price_table_sql = """
            CREATE TABLE IF NOT EXISTS sector_prices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                symbol VARCHAR(50) NOT NULL COMMENT '板块/指数代码',
                symbol_title VARCHAR(100) COMMENT '板块/指数完整名称',
                trade_date DATE NOT NULL COMMENT '交易日期',
                open_price DECIMAL(15, 2) COMMENT '开盘价',
                high_price DECIMAL(15, 2) COMMENT '最高价',
                low_price DECIMAL(15, 2) COMMENT '最低价',
                close_price DECIMAL(15, 2) NOT NULL COMMENT '收盘价',
                volume BIGINT COMMENT '成交量',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                UNIQUE KEY uk_symbol_date (symbol, trade_date),
                INDEX idx_symbol (symbol),
                INDEX idx_trade_date (trade_date),
                INDEX idx_symbol_date (symbol, trade_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='板块价格表';
            """
            cursor.execute(create_price_table_sql)
            
            connection.commit()
            print("[OK] 数据库表初始化成功")
            
    except Exception as e:
        print(f"[ERROR] 数据库表初始化失败: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()


def check_month_data_exists(symbol: str, year: int, month: int) -> bool:
    """
    检查指定月份的数据是否已存在
    
    Args:
        symbol: 板块/指数代码
        year: 年份
        month: 月份 (1-12)
    
    Returns:
        bool: 如果数据存在返回 True，否则返回 False
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = """
            SELECT COUNT(*) as count 
            FROM sector_months 
            WHERE symbol = %s AND year = %s AND month = %s
            """
            cursor.execute(sql, (symbol, year, month))
            result = cursor.fetchone()
            return result['count'] > 0
    except Exception as e:
        print(f"[WARNING] 检查月份数据失败: {e}")
        return False
    finally:
        if connection:
            connection.close()


def save_month_record(symbol: str, symbol_title: str, symbol_type: str, year: int, month: int) -> bool:
    """
    保存月份记录
    
    Args:
        symbol: 板块/指数代码
        symbol_title: 板块/指数完整名称
        symbol_type: 类型 ('index' 或 'sector')
        year: 年份
        month: 月份 (1-12)
    
    Returns:
        bool: 保存成功返回 True
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = """
            INSERT INTO sector_months (symbol, symbol_title, symbol_type, year, month)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                symbol_title = VALUES(symbol_title),
                updated_at = CURRENT_TIMESTAMP
            """
            cursor.execute(sql, (symbol, symbol_title, symbol_type, year, month))
            connection.commit()
            return True
    except Exception as e:
        print(f"[ERROR] 保存月份记录失败: {e}")
        if connection:
            connection.rollback()
        return False
    finally:
        if connection:
            connection.close()


def save_price_data(
    symbol: str,
    trade_date: str,
    open_price: Optional[float] = None,
    high_price: Optional[float] = None,
    low_price: Optional[float] = None,
    close_price: float = None,
    volume: Optional[int] = None,
    symbol_title: Optional[str] = None
) -> bool:
    """
    保存价格数据
    
    Args:
        symbol: 板块/指数代码
        trade_date: 交易日期 (格式: 'YYYY-MM-DD')
        open_price: 开盘价
        high_price: 最高价
        low_price: 最低价
        close_price: 收盘价（必需）
        volume: 成交量
    
    Returns:
        bool: 保存成功返回 True
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = """
            INSERT INTO sector_prices 
            (symbol, symbol_title, trade_date, open_price, high_price, low_price, close_price, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                symbol_title = VALUES(symbol_title),
                open_price = VALUES(open_price),
                high_price = VALUES(high_price),
                low_price = VALUES(low_price),
                close_price = VALUES(close_price),
                volume = VALUES(volume),
                updated_at = CURRENT_TIMESTAMP
            """
            cursor.execute(sql, (
                symbol,
                symbol_title if symbol_title else symbol,  # 如果没有提供，使用symbol作为默认值
                trade_date,
                open_price,
                high_price,
                low_price,
                close_price,
                volume
            ))
            connection.commit()
            return True
    except Exception as e:
        print(f"[ERROR] 保存价格数据失败: {e}")
        if connection:
            connection.rollback()
        return False
    finally:
        if connection:
            connection.close()


def save_price_batch(price_data_list: List[Dict]) -> int:
    """
    批量保存价格数据
    
    Args:
        price_data_list: 价格数据列表，每个元素包含:
            {
                'symbol': str,
                'trade_date': str,
                'open_price': float,
                'high_price': float,
                'low_price': float,
                'close_price': float,
                'volume': int
            }
    
    Returns:
        int: 成功保存的记录数
    """
    if not price_data_list:
        return 0
    
    connection = None
    success_count = 0
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = """
            INSERT INTO sector_prices 
            (symbol, symbol_title, trade_date, open_price, high_price, low_price, close_price, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                symbol_title = VALUES(symbol_title),
                open_price = VALUES(open_price),
                high_price = VALUES(high_price),
                low_price = VALUES(low_price),
                close_price = VALUES(close_price),
                volume = VALUES(volume),
                updated_at = CURRENT_TIMESTAMP
            """
            
            for data in price_data_list:
                try:
                    cursor.execute(sql, (
                        data.get('symbol'),
                        data.get('symbol_title'),
                        data.get('trade_date'),
                        data.get('open_price'),
                        data.get('high_price'),
                        data.get('low_price'),
                        data.get('close_price'),
                        data.get('volume')
                    ))
                    success_count += 1
                except Exception as e:
                    print(f"[WARNING] 保存单条价格数据失败: {e}, 数据: {data}")
            
            connection.commit()
            print(f"[OK] 批量保存价格数据: 成功 {success_count}/{len(price_data_list)} 条")
            
    except Exception as e:
        print(f"[ERROR] 批量保存价格数据失败: {e}")
        if connection:
            connection.rollback()
    finally:
        if connection:
            connection.close()
    
    return success_count


def get_current_month_prices_from_db(symbol: str) -> List[Dict]:
    """
    从数据库获取当前月份的价格数据
    
    Args:
        symbol: 板块/指数代码
    
    Returns:
        List[Dict]: 价格数据列表
    """
    now = datetime.now()
    return get_month_prices_from_db(symbol, now.year, now.month)


def get_month_prices_from_db(symbol: str, year: int, month: int) -> List[Dict]:
    """
    从数据库获取指定月份的价格数据
    
    Args:
        symbol: 板块/指数代码
        year: 年份
        month: 月份 (1-12)
    
    Returns:
        List[Dict]: 价格数据列表
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = """
            SELECT trade_date, open_price, high_price, low_price, close_price, volume
            FROM sector_prices
            WHERE symbol = %s 
            AND YEAR(trade_date) = %s 
            AND MONTH(trade_date) = %s
            ORDER BY trade_date ASC
            """
            cursor.execute(sql, (symbol, year, month))
            results = cursor.fetchall()
            return results
    except Exception as e:
        print(f"[ERROR] 获取 {year}年{month}月价格数据失败: {e}")
        return []
    finally:
        if connection:
            connection.close()


def should_fetch_current_month_data(symbol: str) -> bool:
    """
    判断是否需要获取当前月份的数据
    
    Args:
        symbol: 板块/指数代码
    
    Returns:
        bool: 如果需要获取返回 True，否则返回 False
    """
    now = datetime.now()
    year = now.year
    month = now.month
    
    # 检查月份记录是否存在
    if check_month_data_exists(symbol, year, month):
        # 检查是否有价格数据
        prices = get_current_month_prices_from_db(symbol)
        if prices:
            print(f"[INFO] {symbol} {year}年{month}月数据已存在，共 {len(prices)} 条价格记录")
            return False
    
    print(f"[INFO] {symbol} {year}年{month}月数据不存在，需要获取")
    return True


if __name__ == '__main__':
    # 测试数据库连接和表初始化
    print("=" * 60)
    print("测试数据库连接和表初始化")
    print("=" * 60)
    
    try:
        # 初始化表
        init_tables()
        
        # 测试检查月份数据
        print("\n测试检查月份数据...")
        exists = check_month_data_exists('000300', 2026, 2)
        print(f"000300 2026年2月数据存在: {exists}")
        
        # 测试判断是否需要获取数据
        print("\n测试判断是否需要获取数据...")
        should_fetch = should_fetch_current_month_data('000300')
        print(f"是否需要获取000300当前月数据: {should_fetch}")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()

