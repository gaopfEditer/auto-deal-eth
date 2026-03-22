# TradingView 截图（Playwright Stealth）

用于缓解 Selenium/自动化访问 TradingView 时出现的 **“Something went wrong… Reconnect”**（WebSocket/风控）问题：

- `playwright-extra` + `playwright-extra-plugin-stealth` 降低自动化指纹
- **默认（dealMsg）**：`connectOverCDP(http://127.0.0.1:9222)`，连接你已用 `--remote-debugging-port=9222` 启动的 **同一 Chrome**，与 Selenium 远程调试一致，**会复用登录态**
- 若显式关闭 CDP：`DEALMSG_PLAYWRIGHT_USE_CDP=0`，则使用 `launchPersistentContext` + 本地 `user_data/`（**不会**走 9222）

## 安装

```bash
cd dealMsg/tv_playwright
npm install
npx playwright install chromium
```

## 确认 9222 真的在监听

若「明明开了远程调试」仍连不上，先在本机执行：

```bash
curl -s http://127.0.0.1:9222/json/version | head
```

应返回 JSON（含 `Browser`、`webSocketDebuggerUrl` 等）。若连接被拒绝：

- Chrome **必须**带 `--remote-debugging-port=9222` 启动；仅「设置里开开发者」不够。
- **Chrome 较新版本**若仍用「默认用户数据目录」启动调试，有时调试端口会不生效，需单独指定 `--user-data-dir`（见项目里 `test_gemini_upload_playwright.py` / `CHROME_USAGE.md` 说明）。

## 单独测试（推荐：连 9222）

```bash
node screenshot.js --cdp http://127.0.0.1:9222 \
  --url "https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT&interval=15m" \
  --out ../../screenshots/test_tv.png
```

不传 `--cdp` 时走独立 `user_data/` 浏览器（与 9222 **无关**）。

## 在 dealMsg 里启用

```bash
export DEALMSG_USE_PLAYWRIGHT=1
# 默认会通过 CDP 连 9222；端口与 config 一致可用 CHROME_DEBUG_PORT
python dealMsg/runner.py
```

关闭 CDP、改用独立持久化目录：

```bash
export DEALMSG_PLAYWRIGHT_USE_CDP=0
```

可选：

- `TV_EXTRA_WAIT_MS`：图表加载后额外等待毫秒，默认 `8000`
- `DEALMSG_PLAYWRIGHT_TIMEOUT_MS`：`goto` 超时（默认 `120000`）
- `CHROME_DEBUG_PORT` / `DEALMSG_CHROME_DEBUG_PORT`：CDP 端口（默认 `9222`）
- `HEADLESS=1`：仅对 **非 CDP**（`launchPersistentContext`）模式有意义
