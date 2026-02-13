# 板块数据分析使用指南

## 概述

本模块使用 AKShare 库获取国内和港股板块的估值、价格数据，支持分析最近1月、3月、6月、1年、3年、5年的历史数据。

## 功能特性

- ✅ 获取板块估值数据（PE、PB等）及其历史分位数
- ✅ 获取指数价格数据（点位、涨跌幅等）
- ✅ 支持多个时间周期分析（1月、3月、6月、1年、3年、5年）
- ✅ 自动计算统计指标（最小值、最大值、均值、中位数、分位数）
- ✅ 支持批量分析多个板块/指数
- ✅ 提供格式化的分析结果输出

## 安装依赖

```bash
pip install akshare pandas
```

或使用 requirements.txt：

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 基本使用

```python
from sector_data_fetcher import get_sector_price_data, get_sector_valuation_data

# 获取沪深300指数的价格数据
price_data = get_sector_price_data('000300', periods=['1m', '3m', '6m', '1y'])

# 获取板块估值数据（需要根据实际可用的板块名称）
valuation_data = get_sector_valuation_data('中证消费', periods=['1m', '3m', '6m', '1y', '3y', '5y'])
```

### 2. 综合数据分析

```python
from sector_data_fetcher import get_sector_comprehensive_data, format_analysis_result

# 获取综合数据（价格 + 估值）
data = get_sector_comprehensive_data(
    symbol='000300',
    symbol_type='index',  # 'index' 或 'sector'
    periods=['1m', '3m', '6m', '1y', '3y', '5y']
)

# 格式化输出
formatted = format_analysis_result(data)
print(formatted)
```

### 3. 运行示例脚本

```bash
python sector_analysis_example.py
```

## 支持的板块和指数

### A股主要指数

| 指数名称 | 代码 | 类型 |
|---------|------|------|
| 沪深300 | 000300 | index |
| 上证50 | 000016 | index |
| 中证500 | 000905 | index |
| 创业板指 | 399006 | index |
| 科创50 | 000688 | index |

### 港股主要指数

| 指数名称 | 代码 | 类型 |
|---------|------|------|
| 恒生指数 | HSI | index |
| 恒生科技 | HSTECH | index |
| 国企指数 | HSCEI | index |

### 板块（需要板块名称）

- 中证消费
- 中证医药
- 中证银行
- 中证科技
- 等等...

**注意**: 板块名称需要根据 AKShare 实际支持的名称调整，建议先查看 AKShare 文档或使用示例代码测试。

## API 参考

### get_sector_price_data()

获取指数价格数据。

**参数:**
- `symbol` (str): 指数代码，如 "000300"、"399006" 等
- `periods` (List[str]): 时间周期列表，可选值: '1m', '3m', '6m', '1y', '3y', '5y'

**返回:**
```python
{
    '1m': {
        'current_price': 3500.5,
        'start_price': 3300.0,
        'min_price': 3200.0,
        'max_price': 3600.0,
        'change_pct': 5.2,
        'data_points': 20,
        'start_date': '2024-01-01',
        'end_date': '2024-01-31'
    },
    ...
}
```

### get_sector_valuation_data()

获取板块估值数据（PE、PB等）。

**参数:**
- `symbol` (str): 板块名称，如 "中证消费"、"中证医药" 等
- `periods` (List[str]): 时间周期列表

**返回:**
```python
{
    '1m': {
        'pe': {
            'current': 25.5,
            'percentile': 0.65,  # 历史分位数（0-1）
            'min': 15.0,
            'max': 35.0,
            'mean': 25.0,
            'median': 24.5
        },
        'pb': {
            'current': 3.2,
            'percentile': 0.45,
            'min': 2.0,
            'max': 5.0,
            'mean': 3.0,
            'median': 2.9
        },
        'data_points': 20,
        'start_date': '2024-01-01',
        'end_date': '2024-01-31'
    },
    ...
}
```

### get_sector_comprehensive_data()

获取综合数据（价格 + 估值）。

**参数:**
- `symbol` (str): 板块代码或名称
- `symbol_type` (str): 'index' 或 'sector'
- `periods` (List[str]): 时间周期列表

**返回:**
包含估值和价格数据的综合字典。

### format_analysis_result()

格式化分析结果为可读文本。

**参数:**
- `data` (Dict): 综合数据字典

**返回:**
格式化的文本字符串。

## 配置说明

### 环境变量配置

在 `.env` 文件中可以配置：

```env
# 需要分析的板块/指数列表（用逗号分隔）
SECTORS=000300,000016,中证消费

# 板块分析时间周期（用逗号分隔）
SECTOR_ANALYSIS_PERIODS=1m,3m,6m,1y,3y,5y
```

### 在代码中配置

```python
from config import SECTORS, SECTOR_ANALYSIS_PERIODS

# 使用配置的板块列表
for sector in SECTORS:
    # 判断是指数代码还是板块名称
    if sector.isdigit():
        symbol_type = 'index'
    else:
        symbol_type = 'sector'
    
    data = get_sector_comprehensive_data(sector, symbol_type, SECTOR_ANALYSIS_PERIODS)
```

## 使用示例

### 示例1: 分析单个指数

```python
from sector_data_fetcher import get_sector_price_data

# 获取沪深300的1年数据
data = get_sector_price_data('000300', periods=['1y'])

if data and '1y' in data:
    year_data = data['1y']
    print(f"沪深300 1年涨跌幅: {year_data['change_pct']:.2f}%")
    print(f"当前价格: {year_data['current_price']:.2f}")
    print(f"价格范围: {year_data['min_price']:.2f} ~ {year_data['max_price']:.2f}")
```

### 示例2: 批量分析多个板块

```python
from sector_data_fetcher import get_sector_price_data

sectors = ['000300', '000016', '399006']  # 沪深300、上证50、创业板指

results = []
for symbol in sectors:
    data = get_sector_price_data(symbol, periods=['1y'])
    if data and '1y' in data:
        results.append({
            'symbol': symbol,
            'change_pct': data['1y']['change_pct']
        })

# 按涨跌幅排序
results.sort(key=lambda x: x['change_pct'], reverse=True)

for r in results:
    print(f"{r['symbol']}: {r['change_pct']:.2f}%")
```

### 示例3: 分析估值分位数

```python
from sector_data_fetcher import get_sector_valuation_data

# 获取中证消费的估值数据
valuation = get_sector_valuation_data('中证消费', periods=['3y', '5y'])

if valuation:
    for period in ['3y', '5y']:
        if period in valuation:
            data = valuation[period]
            if 'pe' in data:
                pe = data['pe']
                percentile = pe['percentile'] * 100
                print(f"{period} PE分位数: {percentile:.1f}%")
                
                # 判断估值水平
                if percentile < 20:
                    level = "低估"
                elif percentile < 50:
                    level = "偏低"
                elif percentile < 80:
                    level = "正常"
                else:
                    level = "高估"
                
                print(f"估值水平: {level}")
```

## 注意事项

1. **板块名称**: 板块名称需要根据 AKShare 实际支持的名称调整，建议先测试
2. **数据可用性**: 不同板块的数据可用性可能不同，某些历史数据可能不完整
3. **请求频率**: 为避免请求过快，代码中已添加延迟，但大量请求时仍需注意
4. **错误处理**: 建议在实际使用中添加错误处理和重试机制
5. **数据更新**: AKShare 的数据可能有延迟，建议在交易时间后使用

## 常见问题

### Q: 如何查找板块代码？

A: 可以在 AKShare 文档中查找，或使用以下方法：

```python
import akshare as ak

# 查看可用的指数列表
# 具体方法请参考 AKShare 文档
```

### Q: 为什么某些板块数据获取失败？

A: 可能的原因：
1. 板块名称不正确
2. 该板块数据在 AKShare 中不可用
3. 网络问题
4. AKShare 接口变更

建议：
- 先测试常用的指数代码（如 000300）
- 查看 AKShare 文档确认板块名称
- 添加错误处理和日志记录

### Q: 如何获取港股数据？

A: 使用港股指数代码，如：

```python
# 恒生指数
price_data = get_sector_price_data('HSI', periods=['1y'])

# 恒生科技
price_data = get_sector_price_data('HSTECH', periods=['1y'])
```

**注意**: 港股代码可能需要根据 AKShare 的实际接口调整。

## 集成到主程序

可以将板块数据分析集成到主程序 `main.py` 中：

```python
from sector_data_fetcher import get_sector_comprehensive_data, format_analysis_result
from config import SECTORS, SECTOR_ANALYSIS_PERIODS

def analyze_sectors():
    """分析配置的板块列表"""
    if not SECTORS:
        return
    
    for sector in SECTORS:
        # 判断类型
        symbol_type = 'index' if sector.isdigit() else 'sector'
        
        # 获取数据
        data = get_sector_comprehensive_data(
            sector, 
            symbol_type, 
            SECTOR_ANALYSIS_PERIODS
        )
        
        # 格式化输出
        result = format_analysis_result(data)
        print(result)
        
        # 可以发送通知
        # send_notification(result)
```

## 更多资源

- [AKShare 官方文档](https://akshare.readthedocs.io/)
- [AKShare GitHub](https://github.com/akfamily/akshare)
- 项目 README.md

