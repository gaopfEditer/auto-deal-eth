# binance — 币安广场与市场列表

本目录集中维护原项目根目录下的 `binance_*` 脚本。

## 目录结构

| 文件 | 说明 |
|------|------|
| `market_lists_selenium.py` | Square 关注流抓取、直播巡检、涨跌榜（完整流水线） |
| `gainers_top20.py` | **流动性 TOP30 + 涨幅 TOP20**（CDP + API 回退，默认一次抓两个榜） |
| `square_publish.py` | 广场发帖（文字 + 多图） |
| `square_publish_gainers.py` | 流动性 TOP30 + 涨幅 TOP20 → 短文 → 发布广场 |
| `posts_state.py` | 帖子状态 JSON、Gemini/本地多空分析 |
| `browser.py` | Selenium 等待/日志工具（抓取与发布共用） |
| `paths.py` | 项目根路径、默认数据文件路径 |
| `USAGE_publish.md` | 发帖脚本详细说明 |

数据文件（默认仍在**项目根目录**，与迁移前一致）：

- `../binance_posts_state.json`
- `../binance_market_lists.json`

## 运行方式（在项目根目录）

```bash
# 抓取市场 / Square 关注流（完整：关注用户、直播、可选涨跌榜）
python -m binance.market_lists_selenium
python -m binance.market_lists_selenium --include-hot-rank --market-top 20

# 流动性 TOP30 + 涨幅 TOP20（轻量，推荐）
python -m binance.gainers_top20
python -m binance.gainers_top20 --liquidity-top 30 --gainers-top 20 --print-text

# 发布广场动态
python -m binance.square_publish --text "今日观点 …"
python -m binance.square_publish --text "说明" --image ./a.png --dry-run

# 涨幅榜 → 短文 → 发广场（一条龙）
python -m binance.square_publish_gainers --dry-run   # 先试填
python -m binance.square_publish_gainers             # 抓榜并发布
```

## Python 调用

```python
from binance import publish_square_post, process_watchlist_posts
from binance.market_lists_selenium import scrape_binance_lists
```

## 兼容旧命令

根目录仍保留薄封装，以下命令可继续使用：

```bash
python binance_market_lists_selenium.py
python binance_gainers_top20.py
python binance_square_publish.py --text "…"
python binance_square_publish_gainers.py --dry-run
```

## 前置条件

- Chrome 远程调试 `--remote-debugging-port=9222`，已登录币安
- 详见项目根目录 `CHROME_USAGE.md`、`USAGE.md` 第 4 节

发帖专项说明见 [USAGE_publish.md](USAGE_publish.md)。
