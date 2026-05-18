# tv_ws_pic_push_public — 使用说明

监听 WebSocket 推送中的 **TradingView** 告警；对 **1h / 4h** 周期信号生成标准文案，**POST** 到本地内容服务 `publish/signal`，再按需用 CDP 打开 TradingView 截图。

相关模块：

| 文件 | 作用 |
|------|------|
| `tv_ws_pic_push_public.py` | 本入口：连接 WSS、心跳 pong、调度处理 |
| `ws_signal_handler.py` | 周期过滤、格式化、截图、派发 |
| `notifier.py` | `format_tv_signal_plain`、`publish_signal_to_hub` |
| `dealMsg/runner.py` | 解析 ticker/period、`capture_tradingview_chart` |

---

## 1. 前置条件

1. **Python 依赖**（在项目 venv 内）：

   ```bash
   pip install -r requirements.txt
   # 需含 websockets
   ```

2. **WebSocket 服务**可访问（默认直连，不走系统 SOCKS 代理）：

   ```text
   wss://bz.a.gaopf.top/api/ws
   ```

3. **内容派发服务**已启动（默认本机 8000）：

   ```text
   http://127.0.0.1:8000/api/publish/signal
   ```

4. **需要截图时**：Chrome 已开远程调试（与 `binance_market_lists_selenium` 相同）：

   ```bash
   # macOS 示例
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
   ```

   环境变量 `USE_REMOTE_DEBUGGING=True`、`CHROME_DEBUG_PORT=9222`（见 `.env` / `config.py`）。

---

## 2. 快速启动

```bash
cd /path/to/auto-deal-eth
source venv/bin/activate

# 默认：收到 1h/4h 信号 → POST publish/signal → TradingView 截图
python tv_ws_pic_push_public.py
```

启动后应看到类似：

```text
[WS] 派发地址: http://127.0.0.1:8000/api/publish/signal
[WS] 连接 wss://bz.a.gaopf.top/api/ws …（直连，POST publish/signal + 截图）
[WS] 已连接，等待消息（Ctrl+C 退出）
```

---

## 3. 命令行参数

| 参数 | 说明 |
|------|------|
| （无） | **默认执行**：格式化 → POST → 截图 |
| `--dry-run` | 仅打印解析结果，**不** POST、**不**截图（调试协议用） |
| `--skip-screenshot` | 仍 POST，不打开 TradingView |
| `--print-raw` | 每条消息先打印原始 JSON |
| `--url <wss>` | 覆盖 WebSocket 地址 |

示例：

```bash
# 只测派发，不截图（需 8000 服务）
python tv_ws_pic_push_public.py --skip-screenshot

# 只看消息结构
python tv_ws_pic_push_public.py --dry-run --print-raw
```

---

## 4. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAIN_WS_URL` | `wss://bz.a.gaopf.top/api/ws` | WebSocket 地址 |
| `WS_ALLOWED_PERIODS` | `1h,4h` | 只处理这些周期，其它跳过 |
| `SIGNAL_PUBLISH_URL` | `http://127.0.0.1:8000/api/publish/signal` | 派发接口 |
| `SIGNAL_PUBLISH_STYLE_IDS` | `style_tianya_classic` | 逗号分隔 |
| `SIGNAL_PUBLISH_STRATEGY_ID` | `strategy_left_ambush` | 策略 ID |
| `SIGNAL_PUBLISH_COMPOSE_MODE` | `manual` |  compose 模式 |
| `SIGNAL_PUBLISH_DO_PUBLISH` | `true` | JSON 里 `publish` 字段 |
| `WS_SKIP_TELEGRAM` | （空） | 设为 `1` 则不推 Telegram |
| `DEALMSG_USE_PLAYWRIGHT` | `0` | 设为 `1` 用 Playwright 截图替代 Selenium |

`.env` 示例：

```env
MAIN_WS_URL=wss://bz.a.gaopf.top/api/ws
WS_ALLOWED_PERIODS=1h,4h
SIGNAL_PUBLISH_URL=http://127.0.0.1:8000/api/publish/signal
SIGNAL_PUBLISH_STYLE_IDS=style_tianya_classic
SIGNAL_PUBLISH_STRATEGY_ID=strategy_left_ambush
USE_REMOTE_DEBUGGING=True
CHROME_DEBUG_PORT=9222
```

---

## 5. 处理流程

```text
WSS message_received (source=tradingview)
    → 解析 metadata.ticker / period
    → 周期 ∈ {1h, 4h}?  否 → 跳过
    → format_tv_signal_plain → 标准纯文本 signal
    → POST /api/publish/signal（与下方 curl 一致）
    → capture_tradingview_chart（CDP 打开 TV 并截图到 screenshots/）
```

**顺序**：先 **POST**，再截图；截图失败不影响已发出的 publish。

---

## 6. 标准 signal 文案格式

示例（BTCUSD 1h 倒锤子）：

```text
📊 BTCUSD 倒锤子

触发信号

💰 交易对: BTCUSD
📈 类型: 倒锤子
⏰ 周期: 1h
⏰ 时间: 2026-05-18 23:00:00
💵 价格: 76348.01
📈 最高: 76425.95
📉 最低: 75992

👤 来源: TradingView
```

该整段字符串作为 JSON 字段 `"signal"` 提交。

---

## 7. 与 curl 等价的派发

脚本内部等价于：

```bash
curl -s -X POST http://127.0.0.1:8000/api/publish/signal \
  -H 'Content-Type: application/json' \
  -d '{
    "signal": "（上节格式化后的全文）",
    "style_ids": ["style_tianya_classic"],
    "strategy_id": "strategy_left_ambush",
    "compose_mode": "manual",
    "publish": true
  }'
```

成功时终端会有：

```text
[publish] POST http://127.0.0.1:8000/api/publish/signal strategy=... styles=...
[publish] 已派发 ...
[执行] ok=True 已处理 BTCUSD 1h，已 POST publish/signal ...
```

---

## 8. 心跳

收到 `{"type":"heartbeat",...}` 时自动回复：

```json
{"type":"pong","timestamp":"<UTC ISO8601>"}
```

连接使用 `proxy=None`，避免本机 `ALL_PROXY=socks5://...` 导致 `python-socks` 报错。

---

## 9. 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 只有 `解析 -> ticker=... [允许]`，无 `[publish]` | 使用了 `--dry-run`；去掉该参数 |
| `ImportError: python-socks` | 未清代理；脚本已 `disable_proxy_env` + `proxy=None`，确认未改回旧版 |
| `[publish] 请求失败` / HTTP 非 2xx | 8000 服务未启动；先用上文 curl 自测 |
| 周期 15m 等被跳过 | 仅处理 `WS_ALLOWED_PERIODS`，默认 `1h,4h` |
| 截图失败但 publish 成功 | 预期行为；检查 Chrome 9222 是否开启 |

---

## 10. 本地联调（不连 WebSocket）

`tv_ws_pic_push_public_test.py` 用内置 **PAXGUSD 1h** 样本（与真实 WSS 结构一致）直接跑 publish + 截图：

```bash
python tv_ws_pic_push_public_test.py
python tv_ws_pic_push_public_test.py --skip-screenshot   # 仅测 8000 派发
python tv_ws_pic_push_public_test.py --ticker BTCUSD --period 4h
```

需先启动 `http://127.0.0.1:8000`；截图时仍需 Chrome `--remote-debugging-port=9222`。

## 11. promat 润色提示词（分行 + 小故事）

8000 服务返回的 `polished.content` 由 Ollama 按 promat 生成。本仓库模板目录：

```text
prompts/promat/
  style_tianya_classic.txt    # 天涯经典文风：短句、分段、易扫读
  strategy_left_ambush.txt    # 左侧埋伏策略 + 必填【小故事】
  tv_signal_compose.txt       # 总装 JSON 输出模板
```

拼装逻辑见 `promat_publish.py`（`build_tv_signal_compose_prompt`）。  
**更新提示词后需重启 8000 publish 服务**；终端里 `[publish] 响应` 会按段落打印，不再挤在一行 JSON 里。

本地预览拼装结果：

```bash
python -c "
from promat_publish import build_tv_signal_compose_prompt
from notifier import format_tv_signal_plain
from tv_ws_pic_push_public_test import SAMPLE_PAXGUSD_1H
sig = format_tv_signal_plain(SAMPLE_PAXGUSD_1H)
print(build_tv_signal_compose_prompt(sig)[:2000])
"
```

## 12. 与 main.py 的关系

`python main.py --ws` 通过 `websocket-client` + `ws_signal_handler` 走同一套「格式化 → publish → 截图」逻辑（`handle_ws_tv_message`）。

本脚本 `tv_ws_pic_push_public.py` 为 **独立常驻进程**，使用 `asyncio` + `websockets`，适合单独跑推送链路，不依赖 `main.py` 的 tophub 定时任务。
