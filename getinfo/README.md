# getinfo 资讯获取模块

## 1. 宏观经济日历（华尔街见闻 + 金十星级）

- **数据源**：AkShare `macro_info_ws`（华尔街见闻宏观日历，https://wallstreetcn.com/calendar）。
- **重要度映射**：华尔街见闻使用 1～3 星（或颜色条），与金十对应如下：
  - **3 星（红）** = 金十 5 星（高重要度）
  - **2 星（黄）** = 金十 3-4 星（中重要度）
  - **1 星** = 低重要度
- 返回的 DataFrame 会多一列 **「星级」**，格式如：`3星(5星·高)`、`2星(3-4星·中)`、`1星(低)`。
- **筛选**：`importance_value="高"`（默认）只返回 3 星；`"中高"` 或 `"高与中"` 返回 2 星 + 3 星；`"中"` 只返回 2 星。

```python
from getinfo import get_high_impact_calendar, get_high_impact_calendar_columns

# 默认：仅高影响（3 星 = 金十 5 星）
df = get_high_impact_calendar()
# 高 + 中（2 星 + 3 星）
df = get_high_impact_calendar(importance_value="中高")
if df is not None:
    cols = [c for c in get_high_impact_calendar_columns() if c in df.columns]
    print(df[cols].head(10))
```

## 2. AkShare 数据来源说明

AkShare 不生产数据，通过爬虫封装多家财经门户：

| 来源 | 内容 |
|------|------|
| 金十 (Jin10) | 实时快讯、宏观经济日历（含星级/重要度） |
| 东方财富 | 基金、个股、国内宏观指标 |
| 新浪财经 | 股票行情、部分交易日历 |
| Investing.com | 国际宏观指标（非农、美联储决议等）备份 |

## 3. 消息权重判定（三维判定法）

用于路透社、BBC 等快讯的“权重”评估（无直观星级时使用）。

### A. 传播维度 (Propagation Weight)

- **首发**：路透社 "EXCLUSIVE" / "URGENT" → 自动 5 星。
- **交叉验证**：路透社首发后，BBC 在 30 分钟内跟进并开 "Live Update" → 从 3 星提升至 5 星。

### B. 关键词与语义 (NLP Weight)

- 使用 **Gemini API** 对标题做情绪/关键词建模（可选）。
- **5 星特征词**：Escalation, Direct Strike, Nuclear, Sanction, Closed Strait 等。
- **4 星特征词**：Warning, Mobilization, Cyber Attack, Emergency Meeting 等。

### C. 市场联动 (Market Reflexivity)

- **逻辑**：监控消息发布后 1～5 分钟内，布伦特原油或 BTC 的 1 分钟线波动率。
- **判定**：若波动率超过历史标准差的 2 倍（σ×2），则将该新闻标为高权重（5 星）。

### 使用示例

```python
from datetime import datetime
from getinfo import NewsItem, FollowUp, propagation_weight, nlp_weight_gemini, score_news_weight

# 传播维度
item = NewsItem(
    title="URGENT: Fed raises rates by 50bp",
    source="Reuters",
    published_at=datetime.now(),
    is_urgent=True,
)
follow_ups = [FollowUp(source="BBC", published_at=datetime.now(), is_live_update=True)]
print(propagation_weight(item, follow_ups))  # 5

# NLP 权重（本地关键词 + 可选 Gemini）
print(nlp_weight_gemini("Escalation in the Middle East"))  # 5

# 综合三维
result = score_news_weight(item, follow_ups, use_nlp=True, use_market=False)
print(result)  # {"propagation": 5, "nlp": ..., "market": None, "score": 5}
```

市场联动需接入 1 分钟 K 线（BTC/Oil），当前为占位实现，可按项目数据源扩展 `getinfo/weight.py` 中的 `_fetch_crypto_minute` / `_fetch_oil_minute`。
