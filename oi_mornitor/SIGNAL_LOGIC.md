# oi_mornitor 信号 · 拐点 · 通知逻辑说明

本文档整理 `oi_mornitor` 内全部业务信号、图表标注（次高点 / 扳机线 / Vegas / 射击之星等）、**沙盒纸面交易（短线猎手 S / 长线维加斯 T）** 与通知通道，方便对照 Pine（`tradingview-bollinger-wicks.pine` / Vegas 双通道）与前端图表。

---

## 1. 总览：业务链路 + 形态图 + 沙盒交易

```
RadarService.scan_once (~60s)
  ├─ OI 热钱异动           → hot_tickers（Toast + AlertFeed）
  ├─ 矩阵突破回踩           → breakout_alerts（BreakoutToast）
  ├─ 形态 LH→HL→扳机        → pattern.pattern_alerts（PatternToast）
  ├─ 回踩/Vegas/射击之星    → pattern.pullback_alerts（后端有、前端 Toast 未接）
  └─ 沙盒纸面交易 S/T       → pattern.sandbox_*（SandboxToast + 列表 + localStorage 历史）

图表 /api/patterns/chart
  → candles + BB + Vegas EMA + price_lines(H_max/LH/扳机…) + markers(拐点/锤子/射击之星/沙盒入出)
```

**通知通道速查**

| 信号 | SSE 字段 | 前端 Toast | Telegram |
|------|----------|------------|----------|
| OI 热钱 | `hot_tickers` | 雷达页 ✅ | ❌ |
| 矩阵突破扳机 | `breakout_alerts` | 雷达页 ✅ | ❌ |
| 形态多头爆发 | `pattern.pattern_alerts` | 形态页 ✅ | ❌ |
| 回踩/射击之星 | `pattern.pullback_*` | ❌ 未接 | 仅 `run_coin_monitor --telegram` |
| 沙盒入场/移止损/减仓/平仓 | `pattern.sandbox_alerts` | 形态页 ✅ | ❌ |

---

## 2. 形态拐点逻辑（LH / 扳机线 / HL）

对应引擎：`pattern_detector.py` + `pattern_monitor.py`  
图表：`build_pattern_chart_payload` → 前端 `PatternChartPanel`

### 2.1 关键价位定义

| 代号 | 中文 | 如何得到 | 图表表现 |
|------|------|----------|----------|
| **H_max** | 绝对高点 | 最近两个 pivot high 中的较高者（或状态机写入） | 红色水平线 + ① 箭头 |
| **LH** | 次高点 | 第二个 pivot high，且 `LH < H_max` | 黄色水平线 + ② 箭头 |
| **L₁** | 洗盘低点 | LH 之后第一个（或最近）pivot low | 浅红水平线 + 上箭头 |
| **HL** | 更高低点 | 第二个 pivot low，且 `HL > L₁` | 绿色水平线 + ③ 箭头 |
| **扳机线 / 夹角高点** | Trigger | L₁→HL 区间内的 **最高价** | 蓝色虚线水平线 + 「夹角高点」圆点 |
| **HH** | 多头爆发收盘 | 收盘突破扳机线后的确认价 | 绿色 ④ 箭头 |

Pivot 窗口：`PATTERN_PIVOT_WINDOW`（默认 11，居中 rolling max/min）。

### 2.2 状态机

```
SEARCHING_TOP
    │  detect_stage1_lh：两高点形成 LH + (BB 上轨插针 或 MACD 高位走弱)
    ▼
STAGE_1_LH_DETECTED（次高点确认）
    │  继续找 HL
    ▼
WAITING_FOR_HL（等待更高低点）
    │  detect_stage2_trigger：
    │    HL > L₁
    │    收盘 > 扳机线（夹角高点）
    │    量 ≥ vol_sma20 × PATTERN_STAGE2_VOL_MULT(1.5)
    │    MACD 金叉且柱扩大
    ▼
TRIGGER_SIGNAL（多头爆发）→ trigger_emitted=true，本币不再评估
    超时 PATTERN_WATCH_MAX_SEC(14400) → EXPIRED
```

### 2.3 阶段细节

**阶段 1 — 次高点（LH）**

- 条件：最近两 pivot high 满足后高 < 前高 → 记为 LH / H_max  
- 滤波（满足其一即可）：
  - **BB-Wicks 上轨插针**：`high > bb_upper` 且收盘回到轨内，上影线/实体 ≥ `PATTERN_WICK_RATIO`(0.3)
  - **MACD 高位走弱**：死叉或红柱缩短

**阶段 2 — 更高低点 + 扳机**

1. 形成 **HL > L₁**  
2. 计算 **扳机线** = L₁～HL 之间最高价（夹角反弹高点）  
3. 收盘 **带量突破** 扳机线  
4. MACD 金叉放大 → 发 `pattern_bull_continuation` 告警

### 2.4 去重 / 持久化

- DB：`data/pattern_state.db`  
- 同 `kline_close_time` 不重复写  
- `trigger_emitted` 后不再扫该币（需 `reset_symbol` 或清库）

---

## 3. Vegas 双通道（与 Pine 对齐）

Pine 参考：

```pine
study("Vegas双通道", overlay=true)
a=12   // 过滤线 绿
b=144  // A组1 蓝
c=169  // A组2 蓝
d=576  // B组1 红
e=676  // B组2 红
```

| 线 | 周期 | 颜色 | 用途 |
|----|------|------|------|
| 过滤线 | EMA 12 | 绿 `#00e676` | 短周期过滤（策略 mid 可不计入） |
| A 组 | EMA 144 / 169 | 蓝 `#2196f3` | 中轨通道 |
| B 组 | EMA 576 / 676 | 红 `#ef5350` | 长轨通道 |

**配置**：`OI_STRATEGY_VEGAS_FILTER=12`，`OI_STRATEGY_VEGAS_PERIODS=144,169,576,676`  
**策略用法**（`strategy/pullback.py`）：回踩锚点候选含 `vegas_mid`（A/B 四线均值，不含过滤线）  
**BB-Wicks Pine**：信号名「V」前缀表示价格贴近 A/B 通道（容差占布林带宽 %），过滤线不参与 V 判定。

图表 API 字段：`vegas: { filter, a1, a2, b1, b2 }`（`{time,value}[]`）。

---

## 4. 射击之星 / 倒锤子（对齐 BB-Wicks Pine）

实现：`strategy/indicators.py`  
图标注：`pattern_detector.build_pattern_chart_payload` → markers `kind=shooting_star|inverted_hammer`

### 4.1 射击之星（看跌）

```
上影线 ∈ [实体×1.5, 实体×max_ratio]   # STRATEGY_SHOOT_WICK_RATIO / MAX
下影线无 或 下影线×2 < 上影线
at_lower（近布林下轨）时必须收阴，其它位置阴阳皆可
```

### 4.2 倒锤子（看涨，射击之星倒置）

```
下影线 ≥ 实体 × ratio(1.5)
上影线 < 下影线 / 3
须在布林中轨之下；若已是射击之星外形则不再标倒锤子
```

图例：射击之星品红下行箭头；倒锤子青色上行箭头。

---

## 5. 其它三条信号机（通知侧）

### 5.1 OI 热钱

- 阈值：`|ΔUSD|≥OI_USD_LIMIT` 或 `|Δ%|≥OI_PCT_LIMIT`（5m/15m 门控评估）  
- 冷却 900s：同向抑制；反向或 15m 升级放行  
- Toast：`ToastStack`（会话内按 symbol 永久 seen）

### 5.2 矩阵突破回踩

- Stage1 真突破写库不弹；Stage2 缩量回踩 supply_wall → `breakout_trigger`  
- Toast：`BreakoutToastStack`

### 5.3 回踩 / Vegas / 射击之星策略

- Stage1：`is_valid_breakout` 或反转背景  
- Stage2：缩量贴 wall / BB 中轨 / Vegas 中线 → 多；或顶部射击之星 → 空  
- 可选：`python -m oi_mornitor.scripts.run_coin_monitor --telegram`

---

## 6. 图表标注图例（形态页）

| kind | 含义 | 视觉 |
|------|------|------|
| `h_max` | 绝对高点 | 红线 + ↓ |
| `lh` | 次高点 | 黄线 + ↓ |
| `l1` | 洗盘低 | 粉线 + ↑ |
| `hl` | 更高低点 | 绿线 + ↑ |
| `mid_peak` / `trigger` | 夹角高点 / 扳机线 | 蓝虚线 + ○ |
| `hh` | 爆发确认 | 绿 ↑ |
| `bb_wick` | BB 上插针 | 紫 ○ |
| `shooting_star` | 射击之星 | 品红 ↓ |
| `inverted_hammer` | 倒锤子 | 青 ↑ |
| Vegas EMA | 过滤/A/B | 绿/蓝/红折线 |
| `sandbox_entry` / `sandbox_exit` | 沙盒开/平仓 | 绿/橙标记 |

---

## 7. 关键文件

| 内容 | 路径 |
|------|------|
| 形态拐点 / 扳机 / 图表 payload | `pattern_detector.py` |
| 形态状态机 + watchlist（每 2h 合约流入+OI 爆发刷新，未进场可替换） | `pattern_monitor.py` / `pattern_state_tracker.py` |
| Vegas / 射击之星 / 倒锤子指标 | `strategy/indicators.py` |
| 回踩策略 | `strategy/pullback.py` |
| **沙盒 S/T 策略** | `sandbox/logics.py` + `sandbox/engine.py` + `sandbox/tracker.py` |
| 配置 | `config.py`（`PATTERN_*` / `STRATEGY_*` / `SANDBOX_*`） |
| 图表 UI | `frontend/src/components/PatternChartPanel.tsx` |
| 沙盒历史（localStorage 3 天） | `frontend/src/utils/sandboxHistory.ts` |
| Pine 对照 | 仓库根目录 `tradingview-bollinger-wicks.pine` |

---

## 8. 已知缺口

1. Pullback 告警进了 SSE，形态页尚无 Toast。  
2. 主雷达不发 Telegram。  
3. 形态 / 回踩 TRIGGER 后不自动重置。  
4. `_last_alerts` 仅本轮，非历史 inbox（沙盒成交另有 SQLite + 前端 localStorage）。

---

## 9. 沙盒纸面交易：什么时候开单 / 止盈 / 止损

实现：`sandbox/logics.py`（判定）· `sandbox/engine.py`（执行）· `sandbox/tracker.py`（SQLite）  
前端：形态页「沙盒」Tab · Toast · 持仓/历史表（`sandboxHistory.ts`，本地约 **90 天**）。

> 以下阈值均为**币种价格变动 %**（不是 ROE）。账面 ROE ≈ 价变% × 杠杆（BTC/ETH 100x，山寨 30x）。

### 9.0 资金与执行约定

| 项 | 默认 | 说明 |
|----|------|------|
| K 线周期 | **15m + 1h** 已收盘 K（同等扫描） | `OI_SANDBOX_INTERVALS`（默认 `15m,1h`）；单周期可设 `15m` |
| 日扫描池 | 随机 **12** 币 | `OI_SANDBOX_DAILY_COUNT`；可「重抽」 |
| 最大同时持仓 | **10** | `OI_SANDBOX_MAX_CONCURRENT`；先触发先开（跨周期合计） |
| 单笔保证金 | **1U** | `OI_SANDBOX_NOTIONAL_USD`；名义 = 保证金 × 杠杆 |
| 杠杆 | BTC/ETH **100x**，其余 **30x** | `OI_SANDBOX_LEVERAGE_*` |
| 手续费 | 单边 **0.04%** 名义 | 开+平各一次，从 PnL 扣除（`OI_SANDBOX_FEE_PCT`） |
| 再入场冷却 | 平仓后再等 **8** 根**该仓位周期** K | `OI_SANDBOX_REENTRY_COOLDOWN_BARS`；按 `symbol|interval` |
| 评估节奏 | 同币+同周期同一根已收盘 K 只评一次 | **入场当根不平仓**（`held_bars≤0` 直接跳过） |

开单来源：

- **自动 `auto`**：日池在每个启用周期上扫描，命中 S/T 入场条件  
- **手动 `manual`**：形态页「手动市价进场」→ `POST /api/sandbox/enter`（可选 `interval`；不校验形态扳机，仍按所选 S/T 算初始 SL，后续出场规则相同）
- **卡片 `card`（logic=`C`）**：WebSocket `OI_CARD_WS_PATH`（默认 `/ws/cards`）或 `POST /api/cards` 推送卡片；**不改 S/T 规则**，额外监听卡片币种。市价卡立即纸面入场；限价卡近场提醒并挂单——**主流（BTC/ETH 或杠杆≥80，约 100x）距入场区 ≤0.2%**，**山寨小杠杆（约 20x/30x）≤1%**——触价后入场。出场只用卡片 SL / 多级 TP（分批），不用阶梯/维加斯。同步回卡片系统时带 `card_id`。

自动：同币**同周期**同时仅允许 1 笔开仓（15m 与 1h 可并存）；手动/卡片：同币可叠多笔。持仓/平仓/冷却均按仓位自己的 `interval` 取对应 K 线（卡片仓 interval=`card`）。

---

### 9.1 什么时候开单（Trend_Status 分流）

先判市场状态，再决定用哪套入场逻辑（两套互斥，避免震荡里硬做趋势、趋势里硬抄底）：

```
trend_status(15m df):
  BULL  = Vegas 慢速通道(EMA576/676) 斜率向上 且 收盘 > 慢速中轨
  BEAR  = 斜率向下 且 收盘 < 慢速中轨
  RANGE = 其余（含快慢通道纠缠的横盘）

入场路由：
  RANGE      → 只评估模块 S（短线猎手）
  BULL/BEAR  → 只评估模块 T（长线维加斯，且必须同向）
```

#### 9.1.1 短线猎手 S — 开多 / 开空

**环境**：`RANGE`（震荡或趋势末端纠缠）。

| 方向 | 开单条件（当根已收盘 K，需同时满足） |
|------|--------------------------------------|
| **空** | 触及布林**上轨**或结构 **LH**，且当根为标准**射击之星** |
| **多** | 触及布林**下轨**或结构 **HL**，且当根为**倒锤子 / 锤子** |

入场价 = 该根**收盘价**。

#### 9.1.2 长线维加斯 T — 开多 / 开空

**环境**：仅 `BULL` 做多 / 仅 `BEAR` 做空。

| 方向 | 开单条件（当根，需同时满足） |
|------|------------------------------|
| **多** | ① 回踩触及 Vegas **过滤线 EMA12** 或隧道（EMA144/169）下沿；② 收盘重新站上过滤线/隧道；③ 确认 = **阳线反包** 或 结构 **HL** |
| **空** | ① 回抽触及过滤线或隧道上沿；② 收盘仍在过滤线/隧道下方；③ 确认 = **阴线反包** 或 结构 **LH** |

---

### 9.2 初始止损（开仓立刻写入）

#### 结构止损（算出来的原始 SL）

| 模块 | 多单 | 空单 |
|------|------|------|
| **S 猎手** | 信号 K 最低价 × (1−0.1%) | 信号 K 最高价 × (1+0.1%) |
| **T 维加斯** | `max(HL×0.9995, EMA169×(1−0.2%))`，且必须低于入场价；无结构位时用入场×(1−0.2%) | 对称（LH / EMA169 上方 0.2%） |

#### 距离上限（ATR 动态，取代百分比硬裁剪）

入场后一律 `apply_entry_sl_cap`：用 **`2.5 × ATR(14)`** 作为距入场的最大止损距离（`OI_SANDBOX_SL_ATR_MULT`，默认 2.5）。

- 多：结构 SL 过远则**上移**到 `入场 − 2.5×ATR`  
- 空：结构 SL 过远则**下移**到 `入场 + 2.5×ATR`  
- ATR 无效时**不裁剪**（保留结构 SL）  
- OI 暴增时波动率升高 → ATR 变大 → 允许更宽止损，避免被噪音扫损  
- 已开仓位不会因改配置自动重算；仅**新开仓**生效  

硬止损击穿（多：`low≤SL` / 空：`high≥SL`）→ **立即全平**，不受最短持仓限制。

---

### 9.3 止盈与移损（持仓后）

**通用（S / T 都有）— 阶梯锁利**

- 持仓以来极值相对入场的有利价变，每满 **2.2%** → SL 相对入场再锁定 **+1%**（可叠加：4.4%→+2%，6.6%→+3%…）  
- 事件：`trail` / `reason=step_trail`；若当根已触及新 SL → `exit` / `step_sl`

#### 9.3.1 短线 S — 主动止盈（全平，不留尾）

在**硬止损未触发**时，需同时满足软出场门槛，才允许主动止盈：

1. 持仓已满至少 **2** 根 15m（`OI_SANDBOX_MIN_HOLD_BARS`）  
2. 收盘价相对入场已有 ≥ **0.25%** 有利波动（`OI_SANDBOX_SOFT_EXIT_MIN_MOVE_PCT`）

| 止盈方式 | 条件 | 出场码 |
|----------|------|--------|
| 布林中轨 | 收盘触及/越过中轨（不用影线） | `bb_mid` |
| ATR | 收盘有利波动 ≥ **2×ATR14** | `atr2` |

逻辑：止损被打穿 = 反转失败，瞬间离场；中轨/ATR 用来落袋，避免影线秒平。

#### 9.3.2 长线 T — 分阶段（保本 → 减仓 → 跟踪）

| 阶段 | 触发（价变有利） | 动作 | 事件 |
|------|------------------|------|------|
| **0** | 开仓 | 写入入场价 / 初始 SL | `entry` |
| **1** | ≥ **0.75%** | SL 移至**开仓成本（保本）** | `trail` / `breakeven` |
| **阶梯** | 峰值每满 **2.2%** | 相对入场锁定 +1%/+2%/…（与 S 相同） | `trail` / `step_trail` |
| **2** | ≥ **1.0%** | **市价减仓 30%**，余 70% 进入跟踪 | `partial` + `trail` |
| **3** | 自持仓极值回撤 **1%** | 剩余仓位全平；跟踪 SL 与阶梯取更优 | `exit` / `trail` |

伪代码（多单尾仓）：

```python
if high > highest_price:
    highest_price = high
trail_sl = max(highest_price * 0.99, step_trail_sl)  # 距高点 1%，或更优阶梯锁
if low <= trail_sl:
    close_all()
```

---

### 9.4 出场原因码（复盘用）

| code | 含义 |
|------|------|
| `sl` | 硬止损 |
| `step_sl` | 阶梯锁定止损被打穿 |
| `bb_mid` | 短线：布林中轨止盈 |
| `atr2` | 短线：2×ATR 止盈 |
| `breakeven` / `step_trail` / `trailing_update` | 移损（未平仓） |
| `partial` | 长线减仓 30% |
| `trail` | 长线跟踪止损全平 |

前端历史表：partial + 最终全平合并为一行，阶段事件用 `;` 连接。

---

### 9.5 配置一览（沙盒交易相关）

| 环境变量 | 默认 | 含义 |
|----------|------|------|
| `OI_SANDBOX_INTERVALS` | 15m,1h | 交易执行周期列表（逗号分隔） |
| `OI_SANDBOX_INTERVAL` | （列表首项） | 兼容旧变量；未设 `INTERVALS` 时仍可用单值思路，以 `INTERVALS` 为准 |
| `OI_SANDBOX_KLINE_LIMIT` | 200 | 15m 等周期拉取根数 |
| `OI_SANDBOX_KLINE_LIMIT_1H` | 720 | 1h 拉取根数（够 Vegas EMA676） |
| `OI_SANDBOX_DAILY_COUNT` | 12 | 日池币数 |
| `OI_SANDBOX_MAX_CONCURRENT` | 10 | 最大同时持仓 |
| `OI_SANDBOX_NOTIONAL_USD` | 1 | 单笔保证金 U |
| `OI_SANDBOX_LEVERAGE_MAJOR` / `_ALT` | 100 / 30 | BTC·ETH / 山寨杠杆 |
| `OI_SANDBOX_FEE_PCT` | 0.04 | 单边手续费 %（名义） |
| `OI_SANDBOX_HUNTER_SL_PAD` | 0.001 | S：信号 K 极值外垫 |
| `OI_SANDBOX_HUNTER_ATR_MULT` | 2 | S：ATR 止盈倍数 |
| `OI_SANDBOX_SL_ATR_MULT` | 2.5 | 初始止损距离上限 = 该值 × ATR(14) |
| `OI_SANDBOX_TREND_SL_PAD` | 0.002 | T：EMA169 外垫 |
| `OI_SANDBOX_TREND_BE_PRICE_PCT` | 0.75 | T：保本触发价变% |
| `OI_SANDBOX_TREND_PARTIAL_PRICE_PCT` | 1.0 | T：减仓触发价变% |
| `OI_SANDBOX_TREND_PARTIAL_FRAC` | 0.30 | T：减仓比例 |
| `OI_SANDBOX_TREND_TRAIL_PCT` | 1.0 | T：尾仓回撤% |
| `OI_SANDBOX_STEP_TRAIL_PROFIT_PCT` | 2.2 | 阶梯：峰值每满该% |
| `OI_SANDBOX_STEP_TRAIL_SL_LIFT_PCT` | 1.0 | 阶梯：每档锁定% |
| `OI_SANDBOX_MIN_HOLD_BARS` | 2 | 软止盈最短持仓根数 |
| `OI_SANDBOX_SOFT_EXIT_MIN_MOVE_PCT` | 0.25 | 软止盈最小有利价变% |
| `OI_SANDBOX_REENTRY_COOLDOWN_BARS` | 8 | 同币再开冷却根数 |

---

### 9.6 单笔生命周期字段

SQLite `trades` + 持仓 `meta_json.events` + 前端 localStorage：

| 字段 | 说明 |
|------|------|
| `entry_time` / `entry_price` | 开仓时间（K 收盘秒）与价格 |
| `exit_time` / `exit_price` | 平仓/减仓时间与价格 |
| `side` / `logic`（S\|T） / `leverage` / `source` | 方向、模块、杠杆、手动/自动 |
| `sl` | 当前生效止损 |
| `stage` / `partial_done` | 长线阶段；是否已减仓 |
| `highest_price` / `lowest_price` | 跟踪极值 |
| `events[]` | 有序事件链 |
| `pnl_usd` / `pnl_pct` / `roe_pct` | 扣费后盈亏 |

```json
[
  {"type":"entry","time":1710000000,"price":1.23,"sl":1.221,"side":"LONG","logic":"T","source":"auto"},
  {"type":"trail","time":1710000900,"price":1.24,"sl":1.23,"reason":"breakeven"},
  {"type":"partial","time":1710001800,"price":1.25,"frac":0.3},
  {"type":"exit","time":1710003600,"price":1.24,"reason":"trail"}
]
```

---

### 9.7 设计要点

1. **策略不冲突**：RANGE 只做边界反转（S）；趋势明确才做回踩顺势（T）。  
2. **止损先紧后活**：结构位 + 硬上限 → 开仓风险可控；盈利后再阶梯上移 / 保本 / 跟踪。  
3. **短线防抖**：中轨用收盘判定 + 最短持仓 + 最小有利波动，减少影线假平仓。  
4. **长线分阶段**：先保本 → 减仓 30% 落袋 → 尾仓才给 1% 回撤空间。  
5. **多币并发**：日池 12、上限 10，先触发先开；平仓后冷却防反复扫损。
