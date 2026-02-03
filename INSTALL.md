# 安装指南

## 当前状态

✅ Python依赖包已安装完成
❌ Playwright浏览器驱动未安装（网络问题导致下载失败）

## 解决浏览器安装问题

### 方法1：手动安装（推荐）

在项目目录下运行：

```bash
cd /Users/mac/frontend/code/1.operations/auto-deal-eth
source venv/bin/activate
playwright install chromium
```

### 方法2：使用代理安装

如果网络不稳定，可以设置代理：

```bash
export HTTP_PROXY=http://your-proxy:port
export HTTPS_PROXY=http://your-proxy:port
playwright install chromium
```

### 方法3：手动下载浏览器

1. 访问 Playwright 浏览器下载页面
2. 手动下载 Chromium 浏览器
3. 解压到 `~/Library/Caches/ms-playwright/` 目录

## 配置环境变量

创建 `.env` 文件：

```env
# Gemini API配置（必需）
GEMINI_API_KEY=your_gemini_api_key_here

# TradingView配置（可选）
TRADINGVIEW_URL=https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT

# 通知配置（至少配置一个）
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=your_token
# 或
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 定时任务配置（可选）
RUN_INTERVAL_MINUTES=15
```

## 运行程序

```bash
# 激活虚拟环境
source venv/bin/activate

# 立即执行一次
python3 main.py --once

# 启动定时任务
python3 main.py
```

## 常见错误

### 错误1：浏览器未安装
```
❌ 错误：Playwright浏览器未安装！
```
**解决方法**：运行 `playwright install chromium`

### 错误2：Gemini API密钥未配置
```
❌ 错误：GEMINI_API_KEY 未配置！
```
**解决方法**：在 `.env` 文件中设置 `GEMINI_API_KEY`

### 错误3：网络连接问题
如果下载浏览器时出现网络错误，请：
1. 检查网络连接
2. 使用代理
3. 稍后重试
