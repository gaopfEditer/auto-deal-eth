# dealMsg

监听 `wss://bz.a.gaopf.top/api/ws` 的消息，解析 `ticker` / `period`，截图 TradingView，并调用 `https://bz.d.ezcoin.ink/gemini/chat` 返回结果。

## 运行
source venv/bin/activate
1. 确保依赖已安装：
   ```bash
   pip install -r requirements.txt
   ```

2. 启动监听：
   ```bash
   python dealMsg/runner.py --ws-url wss://bz.a.gaopf.top/api/ws
   ```

收到消息后，命中 `ticker/period` 的那条内容会生成截图到 `screenshots/`，并把 `gemini/chat` 的返回 JSON 打印到控制台。

## Chrome / TradingView 截图说明

### 方式 A：Playwright + Stealth（推荐，缓解 “Reconnect / Something went wrong”）

TradingView 图表依赖 WebSocket，自动化易被风控掐断。可启用独立脚本（`dealMsg/tv_playwright`）：

```bash
cd dealMsg/tv_playwright && npm install && npx playwright install chromium
export DEALMSG_USE_PLAYWRIGHT=1
python dealMsg/runner.py
```详见 [dealMsg/tv_playwright/README.md](tv_playwright/README.md)。

### 方式 B：Selenium + 远程调试 Chrome

- 默认与项目 `USE_REMOTE_DEBUGGING` 一致：连接本机已启动的 Chrome（如 `--remote-debugging-port=9222`）。
- 截图会在**新标签页**打开 TradingView，完成后关闭该标签，减少对当前窗口的影响。
- 环境变量（可选）：
  - `DEALMSG_USE_REMOTE_DEBUGGING`：`true`/`false`，仅 dealMsg 是否走远程调试（不设则跟 `USE_REMOTE_DEBUGGING`）。
  - `DEALMSG_CHART_WAIT_SEC`：等待图表出现的最长时间（秒），默认 `45`。
  - `DEALMSG_REMOTE_SKIP_QUIT`：远程调试时是否**不**调用 `driver.quit()`。默认 `0`（会 quit，便于连续多条消息）；若发现 quit 把整个 Chrome 关掉，可设为 `1`。
  - `DEALMSG_PLAYWRIGHT_TIMEOUT_MS`：仅 Playwright 模式，`goto` 超时（默认 `120000`）。
