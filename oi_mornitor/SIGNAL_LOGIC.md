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

## 9. 沙盒纸面交易：短线猎手(S) + 长线维加斯(T)

实现：`sandbox/logics.py`（判定）· `sandbox/engine.py`（执行）· `sandbox/tracker.py`（SQLite）  
周期：默认 **15m** 已收盘 K；日池随机 12 币；**最大同时持仓 `SANDBOX_MAX_CONCURRENT=10`**。  
保证金：默认 **1U** / 单；杠杆 BTC·ETH **100x**，山寨 **30x**。  
同一根已收盘 K 每币只评估一次；**入场当根不平仓**（避免影线假平仓）。

### 9.1 Trend_Status 分流（策略不冲突）

```
trend_status(df):
  BULL  = Vegas 慢速通道(EMA576/676) 斜率向上 且 收盘 > 慢速中轨
  BEAR  = 斜率向下 且 收盘 < 慢速中轨
  RANGE = 其余（含 A/B 通道纠缠的横盘）

入场路由：
  RANGE → 只评估模块 S（短线猎手）
  BULL / BEAR → 只评估模块 T（长线维加斯，同向）
```

### 9.2 模块一 · 短线猎手（logic=`S`）

**环境**：震荡 / 趋势末端；价格触及布林上下轨极限，或贴 LH / HL。

| 方向 | 入场触发 | 止损（极小） | 出场（全平，不留尾） |
|------|----------|--------------|----------------------|
| 空 | 触及布林上轨 **或** LH，当根标准射击之星 | 信号 K **最高价 × (1+0.1%)** | 触及布林中轨 **或** 有利波动 ≥ **2×ATR** |
| 多 | 触及布林下轨 **或** HL，当根倒锤子/锤子 | 信号 K **最低价 × (1−0.1%)** | 同上 |

逻辑：止损被直接击穿 = 反转失败，**瞬间离场、绝不扛单**。

配置：`OI_SANDBOX_HUNTER_SL_PAD`（默认 0.001）、`OI_SANDBOX_HUNTER_ATR_MULT`（默认 2）。

### 9.3 模块二 · 长线维加斯（logic=`T`）

**方向过滤**：仅 BULL 做多 / BEAR 做空。

**入场（顺势回踩）**

- 多：回踩 Vegas 过滤线 EMA12 或隧道 EMA144/169 获支撑；确认 = **阳线反包** 或 结构 **HL**  
- 空：回抽过滤线/隧道遇阻；确认 = **阴线反包** 或 结构 **LH**

**初始止损**

- 多：`max(HL×0.9995, EMA169×(1−0.2%))`，且低于入场价  
- 空：对称（LH / EMA169 上方 0.2%）

### 9.4 长线智能化出场（分阶段状态机）

设计基准用「币种实际价格」阈值（对应约 20x 下的 ROE 口述：15% ROE≈0.75% 价、20% ROE≈1% 价）。  
账面 ROE ≈ 价变% × 实际杠杆（100x/30x）。

| 阶段 | 触发（价变有利） | 动作 | 记录事件 `type` |
|------|------------------|------|-----------------|
| **0** 持仓 | 开仓 | 写入入场时间/价/初始 SL | `entry` |
| **1** 首轮防守 | ≥ **0.75%** | SL 移至 **开仓成本（保本）** | `trail`（reason=breakeven） |
| **阶梯锁利**（S/T 全程） | 峰值价变每满 **2.2%** | SL 相对入场再锁定 **+1%**（可叠加：4.4%→+2%，6.6%→+3%…） | `trail`（reason=step_trail） |
| **2** 首批落袋 | ≥ **1.0%** | **市价减仓 30%**，余 70% 开跟踪 | `partial` + `trail` |
| **3** 尾仓追踪 | 自持仓以来极值回撤 **1%** | 强制全平剩余仓位；与阶梯锁利取更优 SL | `exit`（reason=trail）或持续 `trail` 更新 SL |

伪代码（多单尾仓）：

```python
if price > highest_price:
    highest_price = price
    trailing_sl = highest_price * 0.99   # 永远距高点 1%
if low <= trailing_sl:
    close_all()  # 全平离场
```

配置：

| 环境变量 | 默认 | 含义 |
|----------|------|------|
| `OI_SANDBOX_TREND_BE_PRICE_PCT` | 0.75 | 阶段1 保本价变% |
| `OI_SANDBOX_TREND_PARTIAL_PRICE_PCT` | 1.0 | 阶段2 减仓价变% |
| `OI_SANDBOX_TREND_PARTIAL_FRAC` | 0.30 | 减仓比例 |
| `OI_SANDBOX_TREND_TRAIL_PCT` | 1.0 | 尾仓回撤% |
| `OI_SANDBOX_STEP_TRAIL_PROFIT_PCT` | 2.2 | 阶梯：峰值盈利每满该% |
| `OI_SANDBOX_STEP_TRAIL_SL_LIFT_PCT` | 1.0 | 阶梯：每档相对入场锁定的% |
| `OI_SANDBOX_TREND_SL_PAD` | 0.002 | 隧道外安全垫 |
| `OI_SANDBOX_MAX_CONCURRENT` | 10 | 最大同时交易币数 |

### 9.5 单笔交易必须记录的字段（生命周期）

每一单（含减仓腿）在 SQLite `trades` + 持仓 `meta_json.events` + 前端 localStorage（近 3 天）中保留：

| 字段 | 说明 |
|------|------|
| `entry_time` / `entry_price` | 开仓时间（K 收盘秒）与价格 |
| `exit_time` / `exit_price` | 本腿平仓/减仓时间与价格 |
| `side` / `logic`（S\|T） / `leverage` | 方向、模块、杠杆 |
| `sl`（持仓中） | 当前生效止损 |
| `stage` / `partial_done` | 长线阶段；是否已减仓 |
| `highest_price` / `lowest_price` | 跟踪极值 |
| `events[]` | 有序事件链（见下） |
| `pnl_usd` / `pnl_pct` / `roe_pct` | 本腿盈亏 |

**`events[]` 元素约定**

```json
[
  {"type":"entry","time":1710000000,"price":1.23,"sl":1.20,"side":"LONG","logic":"T","message":"..."},
  {"type":"trail","time":1710000900,"price":1.24,"sl":1.23,"stage":1,"reason":"breakeven"},
  {"type":"partial","time":1710001800,"price":1.25,"frac":0.3,"pnl_usd":0.09,"stage":2},
  {"type":"trail","time":1710001800,"price":1.25,"sl":1.2375,"stage":2,"reason":"post_partial_trail"},
  {"type":"exit","time":1710003600,"price":1.24,"reason":"trail","pnl_usd":0.05}
]
```

前端列表展示：**入场时间/价、出场时间/价、盈亏、阶段事件链**（`入@价 → 移 SL → 减@价 → 出@价`）。

### 9.6 并发与资金

- 日池 N 币并行扫描；**先触发先开**，持仓数达到 3 则不再新开。  
- 同币平仓后冷却 `SANDBOX_REENTRY_COOLDOWN_BARS`（默认 8 根 15m）再允许入场。  
- 历史订单：浏览器 `localStorage` 键 `oi_sandbox_trade_history_v1`，**最多保留 3 天**。

### 9.7 为何这样拆更有效

1. **策略不冲突**：RANGE 只玩边界反转，趋势明确才做回踩顺势。  
2. **移动止损更聪明**：先保本 → 再锁 30% → 尾仓才给 1% 回撤空间，避免一开仓就用 1% 跟踪把利润吐光。  
3. **多币并发**：Max=3 提高资金利用率，同时控制风险暴露。
