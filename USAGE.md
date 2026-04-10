# Usage

本文档专注「项目启动与运行」，不展开功能介绍（功能请看 `README.md`）。

## 1. 环境准备

```bash
python -m venv venv
```

Windows PowerShell:

```powershell
.\venv\Scripts\activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

## 2. 配置 `.env`

最少需要配置：

```env
GEMINI_API_KEY=your_gemini_api_key_here
SYMBOLS=ETH,BTC,SOL
```

如需定时运行，再配置：

```env
TIME_RANGES=1:00-3:00,20:00-22:00
RUN_INTERVAL_MINUTES=15
```

## 3. 启动主程序（`main.py`）

### 3.1 立即执行一次（测试）

```bash
python main.py --once
```

### 3.2 启动定时任务

```bash
python main.py
```

程序会按 `TIME_RANGES` + `RUN_INTERVAL_MINUTES` 周期执行。

## 4. 启动市场列表抓取（`binance_market_lists_selenium.py`）

### 4.1 基础运行

```bash
python binance_market_lists_selenium.py
```

默认效果：
- 标准输出打印可读摘要与分区表格
- 完整结果写入 `binance_market_lists.json`

### 4.2 指定输出文件

```bash
python binance_market_lists_selenium.py --out ./screenshots/binance_lists.json
```

### 4.3 控制抓取与输出行数

```bash
python binance_market_lists_selenium.py --max-items 50 --max-print-rows 30
```

- `--max-items`：每个榜单最多抓取条数
- `--max-print-rows`：每个区块终端最多显示条数（`0` 为全部）

### 4.4 终端附带完整 JSON

```bash
python binance_market_lists_selenium.py --print-json
```

### 4.5 常用附加参数

```bash
python binance_market_lists_selenium.py --watchlist-url "https://www.binance.com/zh-CN/square?tab=Following" --max-profiles 60 --skip-profile-live-probe
```

- `--watchlist-url`：Square Following 页面地址
- `--max-profiles`：关注主页巡检上限
- `--skip-profile-live-probe`：跳过逐个主页直播巡检（更快，但直播命中可能更少）

## 5. 常见启动顺序（建议）

1. 激活虚拟环境  
2. `pip install -r requirements.txt`  
3. 配置 `.env`  
4. 先执行 `python main.py --once` 验证  
5. 再执行 `python main.py` 进入定时任务
