# CryptoPulse (`news_mornitor`)

交易所广场 + 社区影响力帖聚合。  
**存储：JSON 文件缓存**（无 PostgreSQL / Redis）。Schema 见 [`SCHEMA.md`](./SCHEMA.md)。

**默认只展示真实抓取结果**：`CRYPTO_PULSE_USE_MOCK` 默认为 `0`；抓取失败不回退演示数据，前端为空直到有过门槛真帖。

## 模块

| 模块 | 说明 |
|------|------|
| `fetchers/` | 多源抓取；`FetcherManager` 按 `CRYPTO_PULSE_SOURCES` 启用 |
| `pipeline/` | 热度打分 + AI/规则摘要与垃圾过滤 |
| `fetchers/macro_calendar.py` | **优先** `getinfo/calendar_akshare`（华尔街见闻）；金十 HTTP 兜底 |
| `store.py` | `posts.json` / `tickers.json` / `macro_events.json` |
| `api/server.py` | FastAPI |
| `frontend/public/` | 左宏观时间轴 + 右多源影响力榜 |
| `scheduler.py` | 默认每 **30 分钟** 一轮（web 后台 / `daemon`） |

## 内容源

| 源 | 模块 | 拉取方式 | 说明 |
|----|------|----------|------|
| 币安广场 | `binance_square` | bapi → **CDP 9222** → 本地 JSON | 真帖真链 |
| Bitget Insights | `bitget_square` | HTTP 404 → **CDP `/zh-CN/insights`** | 默认启用 |
| Reddit | `reddit_crypto` | PullPush 近 14 天 → **CDP hot** | 陈年高赞会丢弃 |
| TradingView | `tradingview_ideas` | Ideas 页 `likes_count` → **CDP** | 解析字段已对齐 |
| Farcaster | `farcaster` | Hub casts | 无赞评时仍可上榜（按抓取时间） |
| OKX / Bybit | 对应模块 | HTTP → **CDP 9222** | 默认关；加进 `CRYPTO_PULSE_SOURCES` |

**CDP 回退（默认开）**：公开 API 404 时，用 **纯 WebSocket CDP**（不经 Selenium）连本机 Chrome `--remote-debugging-port=9222`：`Target.createTarget(background=true)` 后台 worker 标签（带 `#cryptopulse-cdp-worker`，会复用），`Page.navigate` + 页内 `fetch`/DOM，**不** `activate`/`bringToFront`。若仍闪一下 Dock，结束时会把 macOS 前台还回去。

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
# 建议已登录币安/Bitget/OKX；CRYPTO_PULSE_CDP_FALLBACK=0 可关掉
```

默认门槛：**赞 ≥ 200 或 评 ≥ 30**（TradingView：agree≥30 或 评≥10）。

## 快速启动

```bash
cd news_mornitor
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Web：http://127.0.0.1:8770 （立刻可读历史；后台抓取完成后自动更新）
python run.py

python run.py once
python run.py daemon
```

可选：

```bash
# 仅本地调试才开 mock（正式浏览不要开）
# CRYPTO_PULSE_USE_MOCK=1

CRYPTO_PULSE_FETCH_INTERVAL_SEC=1800
# CRYPTO_PULSE_CRYPTOPANIC_TOKEN=你的免费token
# HTTPS_PROXY=http://127.0.0.1:7890
```

## API

- `GET /api/v1/boards?time_range=3d` — 过门槛真帖榜
- `GET /api/v1/posts?...` — 同上
- `GET /api/v1/macro/timeline` — 宏观 ±3 天（北京时间）
- `GET /api/v1/fetch/status` — 定时开关 / 是否在抓 / 距下次间隔
- `POST /api/v1/fetch/stop` — 停止定时抓取
- `POST /api/v1/fetch/start` — 开始定时抓取
- `POST /api/v1/fetch/now` — 立即抓一轮（忽略开关与间隔）
- `POST /api/v1/ingest` — 兼容旧接口

前端约 60s 只刷新展示，**不自动抓取**；定时默认每 **30 分钟**一轮。顶栏：**停止获取 / 开始获取 / 立即获取**、历史。

## 热度公式

```
Score = (Likes*1 + Comments*3 + Shares*5) / (HoursPassed + 2)^1.5
```
