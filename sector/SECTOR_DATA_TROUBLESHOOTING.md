# 板块数据获取问题排查指南

## 常见问题

### 1. 网络连接错误（ProxyError / ConnectionError）

**错误信息：**
```
ProxyError('Unable to connect to proxy', ...)
或
ConnectionError: ('Connection aborted.', RemoteDisconnected(...))
```

**原因：**
- 系统配置了代理，但代理不可用
- 网络连接不稳定
- AKShare的数据源服务器暂时不可用

**解决方案：**

#### 方案1: 禁用代理（已自动处理）
代码已自动设置 `NO_PROXY='*'`，如果仍有问题，可以手动设置：

```python
import os
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
```

#### 方案2: 配置正确的代理
如果需要使用代理：

```python
import os
os.environ['HTTP_PROXY'] = 'http://your-proxy:port'
os.environ['HTTPS_PROXY'] = 'http://your-proxy:port'
```

#### 方案3: 添加重试机制
代码已包含多个备用接口，如果所有接口都失败，可以：
1. 检查网络连接
2. 稍后重试
3. 使用VPN（如果在受限网络环境中）

### 2. 接口返回数据格式不匹配

**错误信息：**
```
KeyError: 'date'
或
未找到收盘价列
```

**原因：**
- AKShare接口返回的列名可能不同
- 接口版本更新导致数据结构变化

**解决方案：**

代码已自动检测多种可能的列名：
- 日期列：'日期', 'date', '时间', 'time'
- 收盘价列：'收盘', 'close', '收盘价', 'CLOSE'

如果仍然失败，可以：
1. 运行 `test_akshare.py` 查看实际返回的列名
2. 根据实际列名修改代码
3. 更新AKShare到最新版本：`pip install --upgrade akshare`

### 3. 指数代码格式错误

**错误信息：**
```
无法获取 XXX 的价格数据
```

**原因：**
- 指数代码格式不正确
- 需要添加市场前缀（如 sh、sz）

**解决方案：**

#### A股指数代码格式：
- 上海市场：`sh000300` 或 `000300`
- 深圳市场：`sz399006` 或 `399006`
- 代码已自动处理市场前缀

#### 常用指数代码：
- 沪深300: `000300` 或 `sh000300`
- 上证50: `000016` 或 `sh000016`
- 中证500: `000905` 或 `sh000905`
- 创业板指: `399006` 或 `sz399006`
- 科创50: `000688` 或 `sh000688`

### 4. 数据为空

**错误信息：**
```
[WARNING] XXX 的价格数据为空
```

**原因：**
- 请求的时间范围内没有数据
- 指数代码不存在
- 数据源暂时不可用

**解决方案：**
1. 检查指数代码是否正确
2. 尝试使用不同的时间范围
3. 检查是否是交易日（非交易日可能没有数据）

## 测试步骤

### 步骤1: 测试基础连接

```bash
python test_akshare.py
```

### 步骤2: 测试单个指数

```python
from sector_data_fetcher import get_sector_price_data

# 测试沪深300
data = get_sector_price_data('000300', periods=['1m'])
print(data)
```

### 步骤3: 检查网络环境

```python
import requests

# 测试是否能访问数据源
try:
    response = requests.get('https://www.akshare.xyz', timeout=5)
    print("网络连接正常")
except:
    print("网络连接异常，可能需要配置代理或VPN")
```

## 调试技巧

### 1. 启用详细日志

修改 `sector_data_fetcher.py`，添加更多调试信息：

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 检查返回的数据结构

```python
import akshare as ak

# 获取数据
data = ak.index_zh_a_hist(symbol="000300", period="daily", start_date="20240101", end_date="20240213")

# 查看数据结构
print("列名:", list(data.columns))
print("数据类型:", data.dtypes)
print("前5行:", data.head())
```

### 3. 测试不同的接口

```python
import akshare as ak

# 方法1
try:
    data1 = ak.index_zh_a_hist(symbol="000300", period="daily", start_date="20240101", end_date="20240213")
    print("方法1成功")
except Exception as e:
    print(f"方法1失败: {e}")

# 方法2
try:
    data2 = ak.stock_zh_index_daily(symbol="sh000300")
    print("方法2成功")
except Exception as e:
    print(f"方法2失败: {e}")
```

## 更新AKShare

如果接口不可用，尝试更新到最新版本：

```bash
pip install --upgrade akshare
```

## 联系支持

如果问题仍然存在：
1. 检查 [AKShare GitHub Issues](https://github.com/akfamily/akshare/issues)
2. 查看 [AKShare 官方文档](https://akshare.readthedocs.io/)
3. 确认网络环境是否正常

