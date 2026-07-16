# oi_mornitor 信号 · 拐点 · 通知逻辑说明

本文档整理 `oi_mornitor` 内全部业务信号、图表标注（次高点 / 扳机线 / Vegas / 射击之星等）与通知通道，方便对照 Pine（`tradingview-bollinger-wicks.pine` / Vegas 双通道）与前端图表。

---

## 1. 总览：四条业务链路 + 一张形态图

```
RadarService.scan_once (~60s)
  ├─ OI 热钱异动           → hot_tickers（Toast + AlertFeed）
  ├─ 矩阵突破回踩           → breakout_alerts（BreakoutToast）
  ├─ 形态 LH→HL→扳机        → pattern.pattern_alerts（PatternToast）
  └─ 回踩/Vegas/射击之星    → pattern.pullback_alerts（后端有、前端 Toast 未接）

图表 /api/patterns/chart
  → candles + BB + Vegas EMA + price_lines(H_max/LH/扳机…) + markers(拐点/锤子/射击之星)
```

**通知通道速查**

| 信号 | SSE 字段 | 前端 Toast | Telegram |
|------|----------|------------|----------|
| OI 热钱 | `hot_tickers` | 雷达页 ✅ | ❌ |
| 矩阵突破扳机 | `breakout_alerts` | 雷达页 ✅ | ❌ |
| 形态多头爆发 | `pattern.pattern_alerts` | 形态页 ✅ | ❌ |
| 回踩/射击之星 | `pattern.pullback_*` | ❌ 未接 | 仅 `run_coin_monitor --telegram` |

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

---

## 7. 关键文件

| 内容 | 路径 |
|------|------|
| 形态拐点 / 扳机 / 图表 payload | `pattern_detector.py` |
| 形态状态机 + watchlist | `pattern_monitor.py` / `pattern_state_tracker.py` |
| Vegas / 射击之星 / 倒锤子指标 | `strategy/indicators.py` |
| 回踩策略 | `strategy/pullback.py` |
| 配置 | `config.py`（`PATTERN_*` / `STRATEGY_VEGAS_*` / `STRATEGY_SHOOT_*`） |
| 图表 UI | `frontend/src/components/PatternChartPanel.tsx` |
| Pine 对照 | 仓库根目录 `tradingview-bollinger-wicks.pine` |

---

## 8. 已知缺口

1. Pullback 告警进了 SSE，形态页尚无 Toast。  
2. 主雷达不发 Telegram。  
3. 形态 / 回踩 TRIGGER 后不自动重置。  
4. `_last_alerts` 仅本轮，非历史 inbox。
