# OI Monitor — 币安永续动态热钱雷达

免签（无需 API Key）的币安 U 本位永续 **持仓量(OI) 异动雷达**，基于 `asyncio + aiohttp` 异步架构。  
前端：**React 18 + Vite**（组件 memo 优化，SSE 实时推送）。

> **信号 / 拐点 / 扳机线 / Vegas / 锤子完整说明** → [`SIGNAL_LOGIC.md`](./SIGNAL_LOGIC.md)

## 功能

1. **fapi 全市场聚合快照（每分钟 1 次 ticker + 本地差分重排）**
   - `GET /fapi/v1/ticker/24hr` 无 symbol 参数 → 一次返回 300+ 永续 24h 行情
   - 并发补充 `openInterest`（ticker 不含持仓量，用于量级分层）
   - 内存 `deque` 缓存分钟级 OI，本地计算 5m / 15m 差值并重排榜单

2. **OI 量级分层（总持仓 USD = OI × 价格）**
   - **大象级** `heavyweight`：≥ 5000 万美金（机构/大户爆仓波段）
   - **中场级** `midweight`：1000 万～5000 万美金（山寨活火山）
   - **排除**：< 1000 万美金

3. **双周期 OI 变动率 + Taker 主动资金流（分源）**
   - 内存 `deque` 缓存分钟级 OI，本地计算 5m / 15m 及多周期差分
   - **持仓榜**：`oi_by_tf` — Open Interest 变动额（USD）
   - **量级榜**：`rank_by_tf.*.magnitude_usd` — OI 为 |ΔOI|×价格，主力为 Taker 净流
   - **强度榜**：`rank_by_tf.*.intensity_score` — 变动率 24h Z-Score 批次归一化 0–100 分
   - 每 **60s** 拉取 OI 更新缓存；仅到期时评估对应窗口（`OI_POLL_5M_SEC=300`、`OI_POLL_15M_SEC=900`）
   - 触发：`|ΔUSD| ≥ 1,500,000` 或 `|Δ%| ≥ 5%`
   - **冷却状态机**：同币 15 分钟内抑制重复告警，除非 **15m 强度升级** 或 **方向反转**

5. **榜单突破两步状态机（Pandas + SQLite）**
   - 仅对矩阵 16 榜 Top 币种拉取 5m OHLC，执行 `is_valid_breakout` 矩阵过滤
   - **第一步（蓄势）**：带量真突破 → 写入 `data/breakout_state.db`，状态 `BREAKOUT_DETECTED`，**不弹窗**
   - **第二步（扳机）**：回踩 supply_wall 且缩量 → `TRIGGER_SIGNAL` → 右下角 `BreakoutToastStack` 弹窗
   - 可调环境变量：`OI_BREAKOUT_LOOKBACK`、`OI_BREAKOUT_VOL_MULT`、`OI_PULLBACK_VOL_SHRINK` 等

6. **交付形态**
   - `async def get_hot_tickers()` 供形态审计层调用
   - 终端彩色扫描看板
   - React 动态雷达 Web UI（SSE 实时推送）

7. **形态追踪页 `/patterns`**
   - 启动后监听列表为空时，优先从**合约流入榜 + OI 爆发榜**挑选 20 个（`OI_PATTERN_AUTO_PICK=20`），不足再补大象池
   - 每隔 2 小时自动刷新（`OI_PATTERN_WATCHLIST_REFRESH_SEC=7200`）；已进场（LH / 等待 HL / 扳机）与沙盒持仓保留，其余可被替换
   - **雷达联动**：同周期同时上「涨幅榜」与「持仓正榜」（量级或强度）的币，每轮扫描自动加入形态追踪（满员时替换未进场币）
   - 支持手动追加 / 移除；右键**置顶**至少 1 天（`OI_PATTERN_PIN_TTL_SEC=86400`，可手动取消）；**热钱重选** 清空并按流入/OI 重新挑选
   - 阶段 1：次高点 LH + BB-Wicks 上轨插针 / MACD 高位走弱 → `STAGE_1_LH_DETECTED`（不弹窗）
   - 阶段 2：更高低点 HL + 带量突破夹角高点 + MACD 金叉 → `TRIGGER_SIGNAL`（右下角预警）
   - API：`GET /api/patterns`、`POST /api/patterns/watch`、`DELETE /api/patterns/watch?symbol=`
   - 状态持久化：`data/pattern_state.db`
   - **K 线详情**：多周期切换 `5m/15m/30m/1h/4h/1d`；默认加载 500 根；滚轮缩小 K 线间距或左滑至边缘自动分页加载更早历史（最多 1500/次）
   - **K 线来源（部署后）**：浏览器直连币安 `fapi/v1/klines` + 本地算 BB/Vegas/MACD，减轻服务端压力；形态状态/沙盒入出标记走轻量 `GET /api/patterns/chart-meta`。实时 K 线已是前端 WS。设 `VITE_CHART_KLINES_SOURCE=backend` 可整包回退服务端代拉

8. **沙盒纸面交易（形态页「沙盒」Tab）** — 完整规则见 [`SIGNAL_LOGIC.md` §9](./SIGNAL_LOGIC.md#9-沙盒纸面交易什么时候开单--止盈--止损)

   | | 短线猎手 **S** | 长线维加斯 **T** |
   |--|----------------|------------------|
   | **何时开** | 市场 `RANGE`：触布林上轨/LH + 射击之星做空；触下轨/HL + 倒锤/锤子做多 | 市场 `BULL`/`BEAR`：顺势回踩 EMA12/隧道 + 反包或 HL/LH |
   | **初始止损** | 信号 K 极值 ±0.1% | HL/LH 或 EMA169 外 0.2% |
   | **止损上限** | 裁剪到距入场 ≤ **2.5×ATR(14)**（波动大时自动放宽） | 同左 |
   | **止盈** | 收盘到布林中轨或 ≥2×ATR（需持仓≥2 根且有利≥0.25%） | ≥0.75% 保本 → ≥1% 减仓 30% → 极值回撤 1% 全平 |
   | **通用** | 峰值每满 2.2% 阶梯上移 SL（每档锁 +1%）；硬止损击穿立即全平；入场当根不平仓 | 同左 |

   - 执行周期默认 **15m + 1h** 同等扫描（`OI_SANDBOX_INTERVALS`）；同币同周期自动单仓，两周期可并存
   - 日池随机 12 币 / 最多同时 10 仓；保证金 1U；杠杆 100x（BTC·ETH）/ 30x（山寨）；双边手续费默认各 0.04%
   - **手动市价进场**（选 S/T + 多/空 + 15m/1h）→ `POST /api/sandbox/enter`；自动同币同周期单仓，手动可叠仓
   - **卡片信号**：WS `/ws/cards` 或 `POST /api/cards`；沙盒可筛「卡片」；止盈止损按卡片，S/T 逻辑不变

9. **回踩 / Vegas / 射击之星策略（本地 WS + 回测）**
   - 与形态页 **共用 watchlist**（大象随机 20 或手动追加）
   - 阶段 1：带量突破 → `BREAKOUT_DETECTED`；或反转背景 → `REVERSAL_WATCH`（不弹窗）
   - 阶段 2：缩量回踩 **supply_wall / 布林中轨 / Vegas 中线**，或顶部 **射击之星** → `TRIGGER_SIGNAL`
   - OI 过滤：5m OI 变动率低于 `OI_STRATEGY_OI_MIN_CHANGE_PCT`（默认 -2%）则抑制做多扳机
   - 雷达 REST 扫描与形态页 SSE 字段：`pullback_states` / `pullback_alerts`
   - 本地 WS 守护：`python oi_mornitor/scripts/run_coin_monitor.py --from-watchlist`
   - 回测（成本防守 + 推动止损）：`python oi_mornitor/scripts/run_backtest.py --symbols BTCUSDT,ETHUSDT`

## 快速启动

在 **`oi_mornitor/` 目录内**（你已在此创建 venv）：

```bash
cd oi_mornitor
python -m venv venv && source venv/bin/activate   # 首次
pip install -r requirements.txt
pip install -e .    # 注册包，之后可用 python -m oi_mornitor

# 方式 A：run.py（推荐，无需 editable 安装）
python run.py
python run.py --dev

# 方式 B：模块方式（需 pip install -e .）
python -m oi_mornitor
python -m oi_mornitor --dev

# 方式 C：CLI 命令（需 pip install -e .）
oi-mornitor --dev
```

在**仓库根目录** `auto-deal-eth/` 也可：

```bash
pip install -r oi_mornitor/requirements.txt
python -m oi_mornitor
```

| 命令 | 说明 |
|------|------|
| `python run.py` | 一键启动（自动 build 前端 + 后端）→ http://127.0.0.1:8765 |
| `python run.py --dev` | 开发模式：Vite :5173 + API :8765（**自动释放旧进程占用的 8765/5173**） |
| `python run.py --rebuild` | 强制重新构建前端 |
| `python run.py daemon` | 仅终端扫描守护进程 |
| `python run.py once` | 单次扫描 |

## 外部调用

```python
import asyncio
from oi_mornitor import get_hot_tickers, get_market_matrix

async def audit():
    hot = await get_hot_tickers()
    for item in hot:
        print(item["symbol"], item["type"], item["pct_5m"])

    matrix = await get_market_matrix()
    print("涨幅+增仓:", [x["symbol"] for x in matrix["top_gainers_oi"]])
    print("OI 暴增:", [x["symbol"] for x in matrix["oi_pumps"]])

asyncio.run(audit())
```

### 四宫格热钱子榜单 `get_market_matrix()`

每 **60s** 基于雷达最新快照刷新，返回四个分类列表（默认各 Top 7）：

| 字段 | 含义 |
|------|------|
| `top_gainers_oi` | 24h 涨幅前 7，且 5m OI 正向增加 |
| `top_losers_oi` | 24h 跌幅前 7，且 5m OI 负向减少 |
| `oi_pumps` | 5m/15m OI 暴增绝对值前 7（不看价格） |
| `oi_dumps` | 5m/15m OI 暴跌绝对值前 7（不看价格） |

供 Vue 3 四宫格看板消费：`GET /api/matrix` 或 SSE 快照中的 `market_matrix` 字段。

### 全场资金环境 `meta`

每次扫描后，`/api/snapshot` 与 SSE 推送均附带 `meta` 元数据：

| 字段 | 说明 |
|------|------|
| `global_oi_net_inflow` | Top N 币种 5m OI 变动额（USD）全场合计，正=净流入 |
| `long_short_bias` | OI 暴涨币中「增仓+涨价」vs「增仓+跌价」计数与占优方向 |
| `risk_regime` | 衍生环境：`risk_on` / `risk_off` / `mixed` |

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `OI_TOP_N` | 0 | 监控池上限（0=不限制，仅按量级分层） |
| `OI_TIER_MID_MIN_USD` | 10000000 | 中场级下限（USD 总持仓） |
| `OI_TIER_HEAVY_MIN_USD` | 50000000 | 大象级下限（USD 总持仓） |
| `OI_OI_BATCH_CONCURRENCY` | 40 | openInterest 并发拉取数 |
| `OI_USD_LIMIT` | 1500000 | USD 变动阈值 |
| `OI_PCT_LIMIT` | 5.0 | 百分比变动阈值 |
| `OI_REQUEST_INTERVAL_SEC` | 0.1 | 每请求后休眠（限频） |
| `OI_SCAN_INTERVAL_SEC` | 60 | OI 拉取与缓存更新周期 |
| `OI_POLL_5M_SEC` | 300 | 5m 窗口评估间隔（秒） |
| `OI_POLL_15M_SEC` | 900 | 15m 窗口评估间隔（秒） |
| `OI_ALERT_COOLDOWN_SEC` | 900 | 同币告警冷却期（秒） |
| `OI_MATRIX_TOP_N` | 7 | 四宫格子榜单条数 |
| `OI_MATRIX_REFRESH_SEC` | 60 | 矩阵刷新间隔（秒） |
| `OI_WEB_HOST` | 127.0.0.1 | Web 绑定地址 |
| `OI_WEB_PORT` | 8765 | Web 端口 |
| `OI_HTTP_TIMEOUT_SEC` | 30 | 币安 HTTP 超时秒数 |
| `HTTPS_PROXY` | — | 国内访问币安必填，如 `http://127.0.0.1:7890` |
| `OI_STRATEGY_INTERVAL` | 1h | 回踩策略 K 线周期 |
| `OI_STRATEGY_SYMBOLS` | BTC,ETH,SOL,ORDI | WS 默认监控列表 |
| `OI_STRATEGY_PULLBACK_TOL` | 0.005 | 回踩贴近支撑容差 |
| `OI_STRATEGY_PULLBACK_VOL_SHRINK` | 0.6 | 回踩缩量阈值 |
| `OI_STRATEGY_OI_MIN_CHANGE_PCT` | -2.0 | OI 5m 过低抑制做多扳机 |
| `OI_SANDBOX_INTERVALS` | 15m,1h | 沙盒执行周期列表 |
| `OI_SANDBOX_KLINE_LIMIT_1H` | 720 | 沙盒 1h K 线拉取根数 |
| `OI_CARD_WS_ENABLED` | 1 | 卡片 WebSocket / HTTP 接入 |
| `OI_CARD_WS_PATH` | /ws/cards | 卡片 WS 路径 |
| `OI_CARD_NEAR_ENTRY_PCT` | 1.0 | 山寨限价卡近场阈值 %（约 20x/30x） |
| `OI_CARD_NEAR_ENTRY_PCT_MAJOR` | 0.2 | 主流限价卡近场阈值 %（约 100x） |
| `OI_SANDBOX_MAX_CONCURRENT` | 10 | 沙盒最大同时持仓 |
| `OI_SANDBOX_SL_ATR_MULT` | 2.5 | 沙盒初始止损距离上限 = 倍数 × ATR(14) |
| `OI_SANDBOX_FEE_PCT` | 0.04 | 沙盒单边手续费 %（名义） |

## 网络 / 代理

国内直连 `fapi.binance.com` 常会超时，日志类似：

```
WARNING | OI_Radar | 请求超时 (1/3): https://fapi.binance.com/fapi/v1/ticker/24hr
```

在仓库根 `.env` 或 `oi_mornitor/.env` 添加：

```bash
HTTPS_PROXY=http://127.0.0.1:7890
```

然后重启 `python run.py --dev`。此时 `/api/snapshot` 会返回完整候选池数据（而非约 314 字节的空快照）。

## API

- `GET /` — 动态雷达前端
- `GET /api/snapshot` — 完整快照 JSON
- `GET /api/hot` — 仅异动列表
- `GET /api/matrix` — 四宫格热钱子榜单
- `GET /api/stream` — SSE 实时推送

## 冷启动说明

前 5 分钟历史不足时，币种处于「预热」状态，不参与异动判定；约 5 分钟后 5m 窗口生效，15 分钟后 15m 窗口生效。

## 冷却状态机

内存维护 `active_alerts = { symbol: AlertRecord }`。某币触发 5m 异动后进入 **15 分钟冷却**：

| 场景 | 行为 |
|------|------|
| 冷却期内同向 5m 再次触发 | 🔇 抑制，不输出告警 |
| 方向反转（涨→跌 或 跌→涨） | ✅ 立即放行 |
| 15m 同向且强度超过上次 | ✅ 升级放行 |
| 冷却期满 | ✅ 正常放行 |

`get_hot_tickers()` 与终端看板仅统计 `is_alert=True` 的条目；被抑制的币种在 Web UI 显示为「🔇抑制」。
