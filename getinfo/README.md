# getinfo 资讯获取模块

## 1. 宏观经济日历（华尔街见闻 + 金十星级）

- **数据源**：AkShare `macro_info_ws`（华尔街见闻宏观日历，https://wallstreetcn.com/calendar）。
- **重要度映射**：华尔街见闻使用 1～3 星（或颜色条），与金十对应如下：
  - **3 星（红）** = 金十 5 星（高重要度）
  - **2 星（黄）** = 金十 3-4 星（中重要度）
  - **1 星** = 低重要度
- 返回的 DataFrame 会多一列 **「星级」**，格式如：`3星(5星·高)`、`2星(3-4星·中)`、`1星(低)`。
- **筛选**：`importance_value="高"`（默认）只返回 3 星；`"中高"` 或 `"高与中"` 返回 2 星 + 3 星；`"中"` 只返回 2 星。
- **时间范围**：默认「近一周」= 以昨天为起点的 7 天（`start_from_yesterday=True`）；可传 `start_from_yesterday=False` 改为从今天起 7 天，或传 `days=14` 拉取更多天。

```python
from getinfo import get_high_impact_calendar, get_high_impact_calendar_columns

# 默认：近一周（昨天起 7 天）、仅高影响（3 星 = 金十 5 星）
df = get_high_impact_calendar()
# 高 + 中（2 星 + 3 星）
df = get_high_impact_calendar(importance_value="中高")
# 从今天起 7 天
df = get_high_impact_calendar(start_from_yesterday=False)
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

## 4. RSSHub 资讯简报

从 [RSSHub](https://rsshub.app) 拉取多路 RSS，可选 Gemini 提纯后生成简报并推送 Telegram。

**依赖**：`pip install feedparser`

**环境变量（可选）**：

| 变量 | 说明 |
|------|------|
| `GEMINI_API_URL` 或 `RSSHUB_GEMINI_API_URL` | 提纯用 Gemini 聊天接口（如 `https://xxx/gemini/chat`），不设则不做 AI 提纯 |
| `RSSHUB_BASE` | RSSHub 基础 URL，默认 `https://rsshub.app` |
| `RSSHUB_FEEDS` | JSON 数组覆盖默认订阅，格式 `[{"name":"","url":"","role":""}]` |
| `GETINFO_DAILY_FILE` | 简报追加写入的文件路径，默认 `daily_insight.md` |
| `GETINFO_SEND_TELEGRAM` | 是否推送到 Telegram（1/0），默认 1；需配置 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` |

**默认订阅示例**：Reuters 美洲、Github Trending、Hacker News 等；每源取前 3 条，提纯后写入 `daily_insight.md` 并推送 Telegram。

```python
from getinfo import get_rss_feeds, generate_morning_report

# 使用默认或环境变量中的订阅列表
report = generate_morning_report(
    max_entries_per_feed=3,
    use_gemini=True,      # 需配置 GEMINI_API_URL
    save_path="daily_insight.md",
    send_telegram=True,   # 需配置 Telegram
)
```

**命令行**：`python -m getinfo.run_rsshub`

## 5. 币安广场热榜（CDP + 缓存 + Gemini 分析）

通过 **Selenium** 以 `debuggerAddress` 连接本机已启动的 Chrome（默认 **9222** 端口，与 `config.CHROME_DEBUG_PORT` 一致），打开币安广场页面，解析 `/square/` 相关链接；结果缓存在 `getinfo/.cache/binance_square_hot.json`。出现**新条目**时，向 `https://bz.d.ezcoin.ink/gemini/chat` 发送 JSON：`{"role":"common","message":"..."}` 做简要分析。

**前置**：先启动带远程调试的 Chrome，例如：

```text
chrome.exe --remote-debugging-port=9222
```

**环境变量（可选）**：

| 变量 | 说明 |
|------|------|
| `CHROME_DEBUG_PORT` | 远程调试端口，默认 `9222` |
| `BINANCE_SQUARE_URL` | 页面 URL，默认 `https://www.binance.com/zh-CN/square` |
| `BINANCE_SQUARE_CACHE` | 缓存文件路径 |
| `GEMINI_CHAT_URL` | Gemini 聊天接口，默认 `https://bz.d.ezcoin.ink/gemini/chat` |
| `BINANCE_SQUARE_WAIT` | 打开页面后额外等待秒数（等 JS 渲染），默认 `5` |
| `BINANCE_SQUARE_ANALYZE_FIRST` | 设为 `1` 时，首次运行也会对已抓取条目调 Gemini；默认首次只写入缓存、避免刷屏 |
| `BINANCE_SQUARE_LOG` | 是否写日志，默认 `1`；设为 `0` 关闭 |
| `BINANCE_SQUARE_LOG_PATH` | 日志文件路径，默认 `getinfo/logs/binance_square.log` |

**命令行**：`python -m getinfo.run_binance_square`

每次运行会把**本次抓取的条目列表**（标题、链接、id）**追加写入日志**（UTF-8），有新 Gemini 分析时也会写在同一段落之后。无需再用命令行查看明细，直接打开日志文件即可。

缓存 JSON 仍含 `last_snapshot`（`getinfo/.cache/binance_square_hot.json`），便于程序读取。

```python
from getinfo import fetch_hot_and_process_new, call_gemini_chat

# 单次拉取并处理新内容（自动连 CDP，明细写入日志）
fetch_hot_and_process_new()
```

---

**使用方式**：`python -m getinfo.run_calendar` | `python -m getinfo.run_rsshub` | `python -m getinfo.run_binance_square`