# 币安订单簿 + 强平监控

单文件：`binance_orderbook_liquidation_monitor.py`（U 本位永续 `fapi` / `fstream`）。

## 环境

```bash
cd d:\frontend\main\python\auto-deal-eth
pip install websockets aiohttp
```

需能访问 `fapi.binance.com`、`fstream.binance.com`。

**代理（推荐）**：在仓库根目录 [`.env`](../.env) 里写（与项目其它脚本一致）：

```env
HTTPS_PROXY=http://127.0.0.1:7890
```

脚本启动时会 `load_dotenv` 加载该文件；启动日志里会显示 `代理=http://127.0.0.1:7890` 或 `(未设置，直连)`。  
也可在 PowerShell 里临时设置：`$env:HTTPS_PROXY="http://127.0.0.1:7890"`（不必改 `.env`）。

**WebSocket 路由（2025 后）**：深度走 `/public`，聚合成交与强平走 `/market`。旧地址 `wss://fstream.binance.com/ws/!forceOrder@arr` 会 **HTTP 404**。

| 数据 | 正确示例 |
|------|----------|
| 深度 | `wss://fstream.binance.com/public/stream?streams=ethusdt@depth@100ms` |
| 成交核对 | `wss://fstream.binance.com/market/stream?streams=ethusdt@aggTrade` |
| 全市场强平 | `wss://fstream.binance.com/market/ws/!forceOrder@arr` |

## 一、单币种运行

默认 **ETHUSDT**：

```bash
python volumn/binance_orderbook_liquidation_monitor.py
```

指定币种：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --symbol BTCUSDT
```

### 正常时你会看到

| 日志前缀 | 含义 |
|----------|------|
| `[订单簿][ETHUSDT] 快照就绪` | REST 100 档快照成功 |
| `[订单簿] 连接 WebSocket` | 已订阅 `ethusdt@depth@100ms` |
| `[状态][ETHUSDT] ... synced=True` | 增量已与快照对齐 |
| `[OBI 预警]` | 前 5 档 OBI 超过 ±0.7（有 2 秒冷却） |
| `[强平大单预警]` | 全市场强平流里过滤到该币且金额 > 5 万 USD |

约每 **30 秒** 一行 `[状态]`（可用 `--status-interval 10` 改短）。

按 **Ctrl+C** 退出。

---

## 二、多币种运行

一条 **组合深度流** + **一条强平流**（强平按币种过滤，无需每个币一条 WS）：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --symbols ETHUSDT,BTCUSDT,SOLUSDT
```

日志里会带 `[订单簿][ETHUSDT]`、`[状态][BTCUSDT]` 等前缀区分。

建议先 **2～3 个** 主流币验证，币种过多会增加组合流体积与 CPU。

---

## 三、测试（推荐顺序）

### 1. 只测 REST 快照（最快，约 1～3 秒）

不连 WebSocket，确认网络和 REST 正常：

```bash
# 单币种
python volumn/binance_orderbook_liquidation_monitor.py --test-snapshot --symbol ETHUSDT

# 多币种
python volumn/binance_orderbook_liquidation_monitor.py --test-snapshot --symbols ETHUSDT,BTCUSDT,SOLUSDT
```

期望：每个币一行 `[OK][SYMBOL] lastUpdateId=... bids=100 asks=100 ... OBI=...`  
失败：`[FAIL][SYMBOL]` + 异常信息 → 查代理、防火墙、DNS。

### 2. 短时测深度 WebSocket（约 20 秒）

确认能收增量并完成 `synced=True`：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --test-ws 20 --symbol ETHUSDT
```

多币种：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --test-ws 25 --symbols ETHUSDT,BTCUSDT
```

期望：

- `ws_seen` > 0（收到深度包）
- `synced=True`（首包对齐成功）
- `applied` > 0（已应用增量）

若 `ws_seen=0`：网络 / WS 被墙。  
若 `synced=False`：加长 `--test-ws 40` 或检查是否频繁断线。

### 3. 正式长跑

通过 1、2 后再：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --symbols ETHUSDT,BTCUSDT
```

---

## 四、强平测试说明

强平流 `!forceOrder@arr` 为 **全市场**，只有出现 **单笔名义价值 > 50000 USD** 且币种在监控列表里才会打 `[强平大单预警]`。

无法人为触发时：

- 保持程序运行，等待市场波动；或
- 临时把脚本里 `LIQUIDATION_NOTIONAL_USD` 调低做联调（测完改回）。

---

## 五、常见报错

### `[强平] HTTP 404`

强平流必须用 **`/market/ws/!forceOrder@arr`**。若仍 404，可先跳过强平只测订单簿：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --skip-liquidation
```

### `asyncio.exceptions.CancelledError`（在 `fetch_depth_snapshot`）

多为 **Ctrl+C 退出**，或拉 `fapi.binance.com/fapi/v1/depth` 时网络超时/被墙。请配置代理后重试，或先：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --test-snapshot --symbol ETHUSDT
```

---

## 六、参数一览

| 参数 | 说明 |
|------|------|
| `--symbol` | 单币种，默认 ETHUSDT |
| `--symbols` | 多币种逗号分隔（优先于 `--symbol`） |
| `--status-interval` | 状态日志秒数，默认 30 |
| `--test-snapshot` | 仅 HTTP 快照测试 |
| `--test-ws SECONDS` | 短时 WS 测试 |
| `--skip-liquidation` | 不连强平流 |

---

## 七、日志与主力撤墙（`QuantEngine`）

Logger 名：**`QuantEngine`**。平稳时每 `--status-interval` 秒（默认 30）一行汇总；未同步时限流每 10 秒一条警告。

**平稳示例：**

```text
2026-05-20 18:05:00 | INFO | [📊盘面汇总] ethusdt | 现价: 2130.31 | 5档总买盘: 1240.00 | 5档总卖盘: 1550.00 | OBI: -0.11 (多空平衡) | 状态: 🟢数据已完全对齐
```

**撤墙示例（`CRITICAL` 多行框 + `INFO` 行动建议）：**

```text
2026-05-20 18:05:24 | CRITICAL | 🔥🔥🔥 [🚨主力撤墙预警] ...
┌────────────────────────────────────────────────────────────────────────┐
│ 🔴 异常位置：Bids 关键支撑位 $2130.00
│ ...
└────────────────────────────────────────────────────────────────────────┘
2026-05-20 18:05:24 | INFO | [🚀行动][ethusdt] 拒绝市价追空。建议在低位 $2087.40 挂限价多单 ...
```

正式监控订阅 **`@depth@100ms`** + **`market` 路由下的 `@aggTrade`**（成交核对）。

逻辑概要：

1. `recent_trades` 滑动窗口（默认 3 秒内、最多 2000 条成交）。
2. 增量深度里：某档 **买单量 ≥ 墙阈值** 且本帧 **归零** → 核对该价位近 3 秒真实成交量。
3. 若成交量 **< 撤单量 × 20%** 且 **OBI ≤ -0.7** → `CRITICAL` 框线预警 + `execute_hunting_plan`（默认仅日志，在撤墙价下方 2% 建议挂限价多单）。

环境变量 / 参数：

| 名称 | 默认 | 说明 |
|------|------|------|
| `WALL_VOLUME_THRESHOLD` / `--wall-threshold` | 3000 | 认定大单墙的最小挂单量 |
| `OBI_TRIGGER_SHORT` / `--obi-short-trigger` | -0.7 | 触发撤墙做空信号的 OBI 上限 |
| `TRADE_MATCH_WINDOW_MS` | 3000 | 成交核对窗口（毫秒） |
| `WALL_EATEN_RATIO` | 0.2 | 成交量低于撤单量×该比例视为主动撤单 |
| `ENABLE_SHORT_ON_SPOOF` | 0 | 设为 1 仅预留下单钩子（当前仍未实现签名下单） |

示例：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --wall-threshold 800 --obi-short-trigger -0.65
```

---

## 八、多进程方式（可选）

若不想用 `--symbols`，也可开多个终端各跑单币（各一条深度 WS）：

```bash
python volumn/binance_orderbook_liquidation_monitor.py --symbol ETHUSDT
python volumn/binance_orderbook_liquidation_monitor.py --symbol BTCUSDT
```

强平 WS 会重复连接两次；更推荐 **`--symbols` 单进程组合流**。
