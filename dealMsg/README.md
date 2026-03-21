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

