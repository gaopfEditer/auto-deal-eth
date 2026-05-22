# Usage

本文档专注「项目启动与运行」，不展开功能介绍（功能请看 `README.md`）。

## 1. 环境准备

ssh -L 3308:127.0.0.1:3306 -N -f root@60.205.120.196
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

## 4. 启动市场列表抓取（`binance/market_lists_selenium.py`）

### 4.1 基础运行

```bash
python -m binance.market_lists_selenium
# 或兼容：python binance_market_lists_selenium.py
```

默认效果：
- 标准输出打印可读摘要与分区表格
- 完整结果写入 `binance_market_lists.json`

### 4.2 指定输出文件

```bash
python -m binance.market_lists_selenium --out ./screenshots/binance_lists.json
```

### 4.3 控制抓取与输出行数

```bash
python -m binance.market_lists_selenium --max-items 50 --max-print-rows 30
```

- `--max-items`：每个榜单最多抓取条数
- `--max-print-rows`：每个区块终端最多显示条数（`0` 为全部）

### 4.4 终端附带完整 JSON

```bash
python -m binance.market_lists_selenium --print-json
```

### 4.5 常用附加参数

```bash
python -m binance.market_lists_selenium --watchlist-url "https://www.binance.com/zh-CN/square?tab=Following" --max-profiles 60 --skip-profile-live-probe
```

- `--watchlist-url`：Square Following 页面地址
- `--max-profiles`：关注主页巡检上限
- `--skip-profile-live-probe`：跳过逐个主页直播巡检（更快，但直播命中可能更少）

## 5. 资源分析（`browser_media_runner`）

说明：当前 `browser_media_runner.runner` 的设计是**资源列表（本地文件）+ 提示词输入**，然后交给 Gemini 网页版上传分析。  
它**不负责** URL 截图/下载，也不走 REST。

### 5.1 本地文件分析（通用文件，按图片方式上传）

```bash
python -m browser_media_runner.runner "D:\frontend\main\python\auto-deal-eth\screenshots\tophub_page.png" -p generic_screenshot.txt --tag smoke
```

- `resources`：一个或多个本地文件路径
- `-p/--prompt`：默认按提示词文件名读取（相对 `browser_media_runner/prompts/`）

### 5.2 本地图片分析（直接传提示词正文）

```bash
python -m browser_media_runner.runner "D:\frontend\main\python\auto-deal-eth\screenshots\tophub_page.png" -p "请只输出 JSON，分析图片核心内容" --prompt-text --tag image
```

- `--prompt-text`：表示 `-p` 传入的是提示词正文，而不是文件名

### 5.3 URL 分析（推荐流程）

`runner` 不直接接收 URL。推荐先把 URL 内容变成本地截图，再走 5.1 / 5.2。

**示例流程：**

1) 先截图 URL（可用你现有浏览器自动化逻辑）  
2) 再执行：

```bash
python -m browser_media_runner.runner "https://x.com/yangyi/status/2043661337839141187" -p twitter_style_timeline.txt --tag url
```

如果你希望“直接传 URL 自动打开并截图再分析”，建议单独做一层 URL 预处理脚本，然后把截图路径传给 `runner`。

## 6. TradingView WebSocket 推送 → 截图 → 派发（`tv_ws/`）

独立常驻进程：收 WSS 里 `tradingview` 信号（默认仅 **1h / 4h**），格式化后 POST `publish/signal`，再 CDP 截 TradingView 图。

```bash
python -m tv_ws.pic_push_public
python -m tv_ws.pic_push_public --skip-screenshot   # 只派发、不截图
python -m tv_ws.pic_push_public --dry-run           # 仅打印，不 POST
```

完整说明见 **[tv_ws/USAGE.md](./tv_ws/USAGE.md)**。

## 7. 常见启动顺序（建议）

1. 激活虚拟环境  
2. `pip install -r requirements.txt`  
3. 配置 `.env`  
4. 先执行 `python main.py --once` 验证  
5. 再执行 `python main.py` 进入定时任务
