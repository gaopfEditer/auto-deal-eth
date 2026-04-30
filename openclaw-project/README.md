# OpenClaw 多角色项目

Cursor 生成模块代码，OpenClaw 运行。

## 目录结构

```
openclaw-project/
├── agents/
│   ├── trader/       # 交易员 Ares：SOUL.md + 交易工具
│   │   ├── SOUL.md
│   │   ├── AGENTS.md
│   │   ├── IDENTITY.md
│   │   └── skills/
│   │       ├── gemini_analyze.py  # 有图=分析K线，无图=获取实时资讯
│   │       └── post_analysis.py   # POST 分析结果到 3123/Webhook
│   ├── operator/     # 运营角色（图片生成、文章撰写）
│   └── auditor/      # 技术审计（监控 3123 端口与日志）
├── skills/           # 通用技能
│   └── webhook_push.py
├── agents.json5      # OpenClaw agents 配置
├── config.json       # 总控配置（Webhook URL、调度等）
└── README.md
```

## 使用步骤

### 1. 在 Cursor 中编辑

- 修改 `agents/trader/SOUL.md` 微调交易员人格
- 修改 `agents/trader/AGENTS.md` 调整工具权限
- 在 `skills/` 下添加新技能脚本

### 2. 注册到 OpenClaw

```bash
# 进入项目根目录（openclaw-project 所在目录）
cd /path/to/openclaw-project

# 注册 trader 模块
openclaw agents add trader --workspace ./agents/trader

# 绑定到 Telegram 群（替换 your_group_id）
openclaw agents bind --agent trader --bind telegram:your_group_id
```

### 3. 配置 openclaw.json

将 `agents.json5` 纳入主配置：

```json5
// ~/.openclaw/openclaw.json
{
  agents: { $include: "/path/to/openclaw-project/agents.json5" },
  channels: {
    telegram: {
      enabled: true,
      botToken: "YOUR_BOT_TOKEN",
      allowFrom: ["tg:123456"],
    },
  },
}
```

### 4. 在 Telegram 中激活

对 Ares 说：

> Ares，从现在起，每天 8 点准时在这个群发分析，Webhook 地址是 https://bz.a.gaopf.top/api/tradingview/receive

OpenClaw 会利用 Scheduled Task 将逻辑固化。

## gemini_analyze 技能

调用 Gemini API，两种模式由是否传入图片和币种自动切换：

| 模式     | 条件           | 功能               |
|----------|----------------|--------------------|
| K 线分析 | 携带图片       | 分析 K 线行情（币种从图中识别） |
| 实时资讯 | 不携带图片     | 获取市场热点、关注方向 |

需配置 `GEMINI_API_KEY`（项目根或父级 `.env`）。

```bash
cd agents/trader/skills

# 分析 K 线（有图，币种由 Gemini 从图中识别）
python3 gemini_analyze.py ./screenshots/chart_15m.png
python3 gemini_analyze.py ./chart.png --role trader

# 获取实时资讯（无图）
python3 gemini_analyze.py
python3 gemini_analyze.py --role trader

# 写入文件
python3 gemini_analyze.py ./chart.png -o output/analysis.json
```

## post_analysis 技能

将分析 JSON POST 到 Webhook：

```bash
# 从 stdin
echo '{"direction":"long","confidence":0.8}' | python agents/trader/skills/post_analysis.py --stdin

# 从文件
python agents/trader/skills/post_analysis.py --file output/analysis.json

# 指定 URL
WEBHOOK_URL=http://127.0.0.1:3123/api/receive python agents/trader/skills/post_analysis.py '{"direction":"long"}'
```

默认 Webhook 在 `config.json` 的 `webhook.url` 中配置。

## 完整流程：角色 + API + 调度

1. **Ares 角色**（SOUL.md）定义交易员人格与输出规范  
2. **gemini_analyze.py** 调用 Gemini API 生成 Ares 格式 JSON  
3. **post_analysis.py** 将结果 POST 到 Webhook（3123 或 TradingView 接收端）  
4. **OpenClaw** 通过 cron / heartbeat 调度执行，或在 Telegram 中触发

## 环境要求

- Node.js v22+（OpenClaw 2026 推荐）
- Python 3.10+（运行 skills 脚本）

安装 Python 依赖（仅 gemini_analyze 需要）：

```bash
pip install -r requirements.txt
```

配置 `GEMINI_API_KEY`：在 openclaw-project 或 auto-deal-eth 的 `.env` 中设置，或导出环境变量。
