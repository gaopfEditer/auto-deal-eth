# Sector 模块说明

板块数据获取和存储模块，整合了价格获取和数据库存储功能。

## 模块结构

```
sector/
├── __init__.py      # 模块入口，导出主要接口
├── fetcher.py       # 数据获取功能（价格、估值）
└── db.py            # 数据库存储功能
```

## 使用方法

### 基本导入

```python
from sector import (
    get_sector_price_data,
    get_sector_valuation_data,
    get_sector_comprehensive_data,
    format_analysis_result
)
```

### 获取价格数据

```python
from sector import get_sector_price_data

# 获取沪深300的价格数据
data = get_sector_price_data('000300', periods=['1m', '3m', '6m', '1y'])

# 查看1年涨跌幅
if '1y' in data:
    print(f"1年涨跌幅: {data['1y']['change_pct']:.2f}%")
```

### 数据库操作

```python
from sector import (
    init_tables,
    should_fetch_current_month_data,
    get_current_month_prices_from_db
)

# 初始化数据库表
init_tables()

# 检查是否需要获取数据
if should_fetch_current_month_data('000300'):
    # 获取数据（会自动存储到数据库）
    data = get_sector_price_data('000300')
else:
    # 从数据库读取
    prices = get_current_month_prices_from_db('000300')
```

## 功能说明

### 数据获取功能 (`fetcher.py`)

- `get_sector_price_data()`: 获取指数价格数据
- `get_sector_valuation_data()`: 获取板块估值数据
- `get_sector_comprehensive_data()`: 获取综合数据
- `format_analysis_result()`: 格式化分析结果

### 数据库功能 (`db.py`)

- `init_tables()`: 初始化数据库表
- `should_fetch_current_month_data()`: 检查是否需要获取当前月数据
- `save_price_batch()`: 批量保存价格数据
- `get_current_month_prices_from_db()`: 从数据库读取当前月价格数据

## 向后兼容性

旧的导入方式仍然可用（通过 `sector_data_fetcher.py` 和 `sector_db.py`），但推荐使用新的模块导入方式：

```python
# 旧方式（仍然可用）
from sector_data_fetcher import get_sector_price_data
from sector_db import init_tables

# 新方式（推荐）
from sector import get_sector_price_data, init_tables
```

