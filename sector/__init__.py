"""
板块数据模块 - 整合价格获取和数据库存储功能
"""
from .db import (
    init_tables,
    check_month_data_exists,
    save_month_record,
    save_price_data,
    save_price_batch,
    get_current_month_prices_from_db,
    get_month_prices_from_db,
    should_fetch_current_month_data
)

from .fetcher import (
    get_sector_price_data,
    get_sector_valuation_data,
    get_sector_comprehensive_data,
    get_fund_return_rate,
    fetch_data_by_months,
    format_analysis_result,
    get_symbol_title,
    TIME_PERIODS,
    COMMON_SECTORS,
    COMMON_FUNDS
)

__all__ = [
    # 数据库相关
    'init_tables',
    'check_month_data_exists',
    'save_month_record',
    'save_price_data',
    'save_price_batch',
    'get_current_month_prices_from_db',
    'get_month_prices_from_db',
    'should_fetch_current_month_data',
    # 数据获取相关
    'get_sector_price_data',
    'get_sector_valuation_data',
    'get_sector_comprehensive_data',
    'get_fund_return_rate',
    'fetch_data_by_months',
    'format_analysis_result',
    'get_symbol_title',
    'TIME_PERIODS',
    'COMMON_SECTORS',
    'COMMON_FUNDS',
]

