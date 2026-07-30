# CryptoPulse — Data Schema (文件缓存版)

> 生产环境可映射到 PostgreSQL / Prisma；当前用 JSON 文件持久化，无 DB。

## Platform（枚举）

| 值 | 说明 |
|----|------|
| `BINANCE` | 币安广场 Binance Square |
| `BITGET` | Bitget Insights |
| `OKX` | OKX 广场 |
| `TWITTER` | X / Twitter |

## Post

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 内部 ID = MD5(`platform` + `:` + `external_id`) |
| `external_id` | string | 平台侧帖子 ID |
| `platform` | Platform | 来源 |
| `author` | string | 作者昵称 |
| `author_avatar` | string? | 头像 URL |
| `title` | string | 标题（可空） |
| `content` | string | 原文 |
| `summary` | string? | AI 中文摘要（2 句） |
| `mentioned_tickers` | string[] | 如 `["BTC","ETH"]` |
| `like_count` | int | 点赞 |
| `comment_count` | int | 评论 |
| `share_count` | int | 转发/分享 |
| `score` | float | 热度分 |
| `is_spam` | bool | AI/规则判定垃圾帖 |
| `published_at` | ISO8601 | 发布时间 |
| `fetched_at` | ISO8601 | 抓取时间 |
| `source_url` | string | 原文链接 |
| `image_urls` | string[] | 配图 |

**去重键**：`platform + external_id` → MD5 → `id`

## Ticker

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 如 `BTC` |
| `mention_count_24h` | int | 24h 提及次数 |
| `post_ids` | string[] | 关联帖子 id |
| `updated_at` | ISO8601 | |

## 文件布局（data/）

```
data/
  posts.json          # { "posts": { "<id>": Post, ... }, "updated_at": "..." }
  tickers.json        # { "tickers": { "<symbol>": Ticker, ... }, "updated_at": "..." }
  seen_ids.json       # { "ids": ["md5...", ...] }  去重集合
  cache/
    posts_list_*.json # API 响应缓存
```

## Prisma 对照（将来迁移）

```prisma
enum Platform { BINANCE BITGET OKX TWITTER }

model Post {
  id                String   @id
  externalId        String
  platform          Platform
  author            String
  authorAvatar      String?
  title             String   @default("")
  content           String
  summary           String?
  mentionedTickers  String[]
  likeCount         Int      @default(0)
  commentCount      Int      @default(0)
  shareCount        Int      @default(0)
  score             Float    @default(0)
  isSpam            Boolean  @default(false)
  publishedAt       DateTime
  fetchedAt         DateTime
  sourceUrl         String
  imageUrls         String[]
  @@unique([platform, externalId])
  @@index([score])
  @@index([publishedAt])
}

model Ticker {
  symbol            String   @id
  mentionCount24h   Int      @default(0)
  postIds           String[]
  updatedAt         DateTime
}
```
