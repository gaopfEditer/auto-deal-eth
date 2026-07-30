# CryptoPulse (`news_mornitor`)

交易所广场（Binance Square 等）热门动态聚合与智能筛选。  
**当前存储：JSON 文件缓存**（无 PostgreSQL / Redis）。Schema 见 [`SCHEMA.md`](./SCHEMA.md)。

## 模块

| 模块 | 说明 |
|------|------|
| `fetchers/` | `FetcherManager` + 币安 / Bitget / OKX 广场抓取（默认 mock） |
| `pipeline/` | 热度打分 + AI/规则摘要与垃圾过滤 |
| `fetchers/macro_calendar.py` | 金十风格宏观日历：≥3★、未来 24h、利好/利空 |
| `store.py` | `posts.json` / `tickers.json` / `macro_events.json` + API 缓存 |
| `api/server.py` | FastAPI 只读接口 |
| `frontend/public/` | **左时间轴 + 右交易所榜单** UI |
| `scheduler.py` | 每 5 分钟轮询（文件锁去重） |

## 快速启动

```bash
cd news_mornitor
pip install -r requirements.txt

# Web：http://127.0.0.1:8770 （首次自动 mock 抓取）
python run.py
# 或
python -m news_mornitor

# 单次抓取
python run.py once

# 仅守护定时抓取
python run.py daemon
```

复制 `.env.example` → 仓库根或本目录 `.env`。

## API

- `GET /api/v1/health`
- `GET /api/v1/posts?platform=BINANCE&ticker=BTC&time_range=24h`
- `GET /api/v1/tickers/trending`
- `GET /api/v1/macro/timeline?min_star=3&ahead_hours=24` — 宏观时间轴
- `GET /api/v1/boards` — 按交易所拆分的热帖榜单
- `POST /api/v1/ingest` — 手动触发抓取（含宏观刷新）

## 页面布局

- **左侧**：金十风格宏观时间轴（手动滚动），仅 **≥3★** 且 **未来 24h**；卡片带 **利好 / 利空 / 中性** 标签与简要理由
- **右侧**：币安 / Bitget / OKX 等广场热帖榜单（按 score 排序）

## 热度公式

```
Score = (Likes*1 + Comments*3 + Shares*5) / (HoursPassed + 2)^1.5
```

## AI

默认 `CRYPTO_PULSE_AI_ENABLED=0`，用规则过滤邀请码/喊单并提取 `$TICKER` + 截句摘要。  
开启后走 OpenAI 兼容接口（DeepSeek 等改 `CRYPTO_PULSE_LLM_BASE_URL`）。

## 真实币安广场

```bash
CRYPTO_PULSE_USE_MOCK=0
HTTPS_PROXY=http://127.0.0.1:7890
# 如需 Cookie / clienttype 等：
# CRYPTO_PULSE_BINANCE_HEADERS_JSON={"cookie":"..."}
```

解析失败时自动回退 mock，保证本地可演示。

## 与 `news_aggregator` 关系

| | `news_aggregator` | `news_mornitor` |
|--|-------------------|-----------------|
| 源 | RSS 宏观/科技 | 交易所广场 |
| 存储 | 文本输出 | JSON 文件库 |
| UI | 无 | CryptoPulse Web |
