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

如需 Telegram 推送（`tv_ws` / 测试脚本），再配置：

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

8000 润色/派发（`tv_ws`）：

```env
SIGNAL_PUBLISH_URL=http://127.0.0.1:8000/api/publish/signal
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

## 4. 币安 Square / 市场列表（`binance/`）

**前置（抓取与发帖共用）**：Chrome 远程调试 9222，且已登录币安。

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

所有命令需在项目根目录、**已激活 venv** 下执行：

```bash
source venv/bin/activate
pip install -r requirements.txt
```

更多细节见 [binance/README.md](./binance/README.md)、发帖见 [binance/USAGE_publish.md](./binance/USAGE_publish.md)。

### 4.1 完整抓取（关注流 / 直播 / 可选涨跌榜）

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

- `--max-items`：Square 帖子条数上限
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

启用行情榜单（热榜 + 涨跌）：

```bash
python -m binance.market_lists_selenium --include-hot-rank --market-top 20
```

### 4.6 流动性 TOP30 + 涨幅 TOP20（轻量，推荐）

一次 CDP 会话抓取两个榜（DOM 不足时回退 24h API；国内 API 可能超时，优先用 CDP）：

```bash
python -m binance.gainers_top20
# 或：python binance_gainers_top20.py

python -m binance.gainers_top20 --liquidity-top 30 --gainers-top 20 --print-text
python -m binance.gainers_top20 --out binance_market_ranks.json
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--liquidity-top` | 30 | 24h USDT 成交额（流动性） |
| `--gainers-top` | 20 | 涨幅榜 |
| `--api-only` | 关 | 不连 CDP，仅调官方 API（需网络可达 `api.binance.com`） |
| `--print-text` | 关 | 打印可发广场的短文预览 |

### 4.7 广场发帖（短文 / 多图）

```bash
python -m binance.square_publish --text "你的短文" --dry-run
python -m binance.square_publish --text-file ./draft.txt --image ./a.png
# 或：python binance_square_publish.py --text "…"
```

`--dry-run`：只填内容，不点「发布」。

### 4.8 抓榜 + 生成短文 + 发广场（一条龙）

```bash
python -m binance.square_publish_gainers --dry-run
python -m binance.square_publish_gainers
python -m binance.square_publish_gainers --liquidity-top 30 --gainers-top 20
# 或：python binance_square_publish_gainers.py
```

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

### 5.3 文生图（提示词 -> Gemini 网页出图）

与 5.1 / 5.2 **对称**：不上传本地图，只发提示词，让 Gemini 网页版生成图片并保存。

```bash
# 直接传提示词正文
python -m browser_media_runner.tti -p "一只赛博朋克风格的橘猫坐在月球上看K线图，16:9" --prompt-text --tag cat

# 使用 prompts/ 下的文生图模板
python -m browser_media_runner.tti -p tti_crypto_banner.txt --tag banner

# 指定输出目录，并保持浏览器打开便于检查
python -m browser_media_runner.tti -p "深色科技感加密货币海报，无水印" --prompt-text --out ./screenshots/tti --keep-browser
```

- `-p/--prompt`：默认读 `browser_media_runner/prompts/` 文件名；加 `--prompt-text` 则当正文
- `--out`：图片输出目录（默认写到 `browser_media_runner/history/tti_*/images`）
- 需已登录 Gemini 的 Chrome（推荐 `USE_REMOTE_DEBUGGING=True` + 9222）
- 账号需具备网页端出图能力；超时未出图时可能只落整页排查截图

### 5.4 URL 分析（推荐流程）

`runner` 对 URL：下游 `gemini_web_automation` 会先打开页面截图再上传分析（也可自行先截图再走 5.1）。

```bash
python -m browser_media_runner.runner "https://x.com/yangyi/status/2043661337839141187" -p twitter_style_timeline.txt --tag url
```

## 6. TradingView WebSocket 推送 → 润色 → Telegram → 截图（`tv_ws/`）

独立常驻进程：收 WSS 里 `tradingview` 信号（默认仅 **1h / 4h**），POST `publish/signal` 润色，**Telegram 图文**，CDP 截 TradingView 图。

```bash
# 默认：润色(publish=false) + Telegram + 截图，不上广场
python -m tv_ws.pic_push_public
python tv_ws_pic_push_public.py

# 仅 Telegram：不润色、不发广场；15m / 1h / 4h 全部转发
python -m tv_ws.pic_push_public --only-telegram
python tv_ws_pic_push_public.py --only-telegram
python -m tv_ws.pic_push_public_only_telegram
python tv_ws_pic_push_public_only_telegram.py

# 仅 Telegram 文本（不润色、不截图）
python tv_ws_pic_push_public.py --only-telegram --no-screenshot
python -m tv_ws.pic_push_public_only_telegram_text
python tv_ws_pic_push_public_only_telegram_text.py

# 发布到广场
python -m tv_ws.pic_push_public --public

python -m tv_ws.pic_push_public --skip-screenshot   # 不截图
python -m tv_ws.pic_push_public --dry-run           # 仅打印，不 POST / 不 Telegram
```

本地联调（不连 WSS）：

```bash
python -m tv_ws.pic_push_public_test              # 默认不发布广场
python -m tv_ws.pic_push_public_test --public     # 测试也发广场
```

8000 派发接口联调 Demo：`demos/publish_signal_8000_demo.py`（见 [demos/README.md](./demos/README.md)）。

完整说明见 **[tv_ws/USAGE.md](./tv_ws/USAGE.md)**。

## 7. 常见启动顺序（建议）

1. 激活虚拟环境：`source venv/bin/activate`  
2. `pip install -r requirements.txt`  
3. 配置 `.env`（含 Telegram / 8000 等按需）  
4. 启动 Chrome：`--remote-debugging-port=9222`  
5. 币安抓榜/发帖：`python -m binance.gainers_top20 --print-text`  
6. TV 推送：`python -m tv_ws.pic_push_public`（确认后再加 `--public`）  
7. 主程序：`python main.py --once` 验证 → `python main.py` 定时任务
