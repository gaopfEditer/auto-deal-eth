# baoyu-skills 原理与复杂 Skill 实现指南

面向想要理解本仓库工作方式，并自己做一个「功能复杂」Skill（例如看 K 线走势）的开发者。

更细的落地规范见：[creating-skills.md](./creating-skills.md)。官方 Skill 写作通则见 [Claude Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)。

---

## 1. 这个项目在做什么

`baoyu-skills` 不是传统意义上的「可执行应用」，而是一套给 **AI Agent**（Claude Code / Codex / Cursor / OpenClaw 等）用的 **技能说明书 + 可选脚本**。

Agent 平时靠通用能力回答问题；装上 Skill 后，会在相关请求时 **按 `SKILL.md` 规定的流程做事**：问什么、确认什么、调哪个脚本、输出落在哪、失败怎么重试。

可以把它理解成：

```text
用户自然语言
    ↓
Agent Runtime（Cursor / Claude Code / Codex …）
    ↓ 匹配 description，加载对应 Skill
SKILL.md（流程、规则、约束）  ←→  scripts/*.ts（确定性计算 / API / 渲染）
    ↓
产物（图片、Markdown、SVG、发布结果 …）
```

本仓库通过 `.claude-plugin/marketplace.json` 把各个 `skills/baoyu-*` 注册成一个插件；每个 skill 目录也可以被单独复制/安装到别的项目里使用。

---

## 2. 核心原理（为什么这样设计）

### 2.1 Skill = 给模型看的「可执行文档」

`SKILL.md` 的主体不是给人读的 README，而是给 Agent 的 **操作手册**：

| 部分 | 作用 |
|------|------|
| YAML `name` / `description` | 决定 **何时被选中**（触发词、场景） |
| 正文 workflow | 决定 **怎么一步步做**（确认门、输出路径、禁止事项） |
| `references/` | 按需加载的细则（风格库、模板、API 说明） |
| `scripts/` | 模型不擅长或必须确定性的部分（调 API、算数、画图） |

模型负责：理解意图、拆任务、填 prompt、做判断、编排步骤。  
脚本负责：HTTP、鉴权、像素生成、解析二进制、可复现的批处理。

### 2.2 Progressive Disclosure（渐进披露）

Skill 很多，但 **不能全部塞进上下文**。机制是：

1. 平时只暴露很短的 `description`（路由用）
2. 命中后才读完整 `SKILL.md`（控制在约 500 行内）
3. 需要细节时再读 `references/*.md`
4. 需要算力/副作用时再跑 `scripts/`

因此复杂功能不要把所有知识写进 `SKILL.md`，而要拆成「主流程 + 按需参考」。

### 2.3 自包含（Self-Containment）

每个 `skills/baoyu-xxx/` 可能被单独拷走使用。硬规则：

- `SKILL.md` / `references/` **不要**链接到仓库外的 `docs/`、兄弟 skill、仓库根文件
- 跨 skill 的约定（用户提问方式、选图后端）要 **内联抄进** 本 skill，而不是 `../../docs/...`
- 仓库级 `docs/` 只服务 **作者/维护者**，不服务运行时 skill

### 2.4 两类实现形态

| 形态 | 典型 skill | 特点 |
|------|------------|------|
| **流程编排型** | `baoyu-article-illustrator`、`baoyu-infographic` | 几乎没有脚本；Agent 按步骤写 outline、prompt，再委托图后端 |
| **脚本后端型** | `baoyu-image-gen`、`baoyu-url-to-markdown` | `scripts/main.ts` 做重活；`SKILL.md` 教 Agent 如何调 CLI |

复杂业务往往是 **两者组合**：Skill 定义分析流程 + 脚本拉数据/算指标/出图。

### 2.5 你刚用过的链路（文章配图）在原理上怎么走

以「知乎文 → 配图」为例：

1. Agent 匹配到 `baoyu-article-illustrator`（描述里有「为文章配图」等）
2. 读 `EXTEND.md` 偏好（风格、输出目录、图像后端）
3. 分析内容 → **确认** type/density/style（门禁）
4. 写 `outline.md` + `prompts/NN-*.md`（可复现记录，先写后生成）
5. 按 `## Image Generation Tools` 选后端（如 `baoyu-image-gen --provider dashscope`）
6. 落盘 PNG，并插回 Markdown

要点：**Prompt 文件是一等公民**；后端可换（Google / Qwen / Cursor GenerateImage），流程不变。

---

## 3. 仓库结构速览

```text
baoyu-skills/
├── .claude-plugin/marketplace.json   # 插件与 skill 路径注册
├── skills/
│   └── baoyu-<name>/
│       ├── SKILL.md                  # 必填：触发 + 流程
│       ├── scripts/                  # 可选：Bun/TS 入口
│       ├── references/               # 可选：细则，按需加载
│       └── prompts/                  # 可选：模板
├── packages/                         # 可选：跨 skill 共享包
├── docs/                             # 作者向文档（本文件也在此）
└── .baoyu-skills/                    # 本地偏好与密钥（gitignore）
    ├── .env                          # API Key
    └── <skill-name>/EXTEND.md        # 该 skill 的用户偏好
```

运行脚本的惯例（见 `CLAUDE.md`）：

```bash
# 优先 bun；否则 npx -y bun
bun skills/<skill>/scripts/main.ts [options]
```

密钥加载优先级（以 `baoyu-image-gen` 为例）：CLI > EXTEND.md > 环境变量 > `<cwd>/.baoyu-skills/.env` > `~/.baoyu-skills/.env`。

---

## 4. 做一个「普通」Skill 的最小步骤

1. 建目录 `skills/baoyu-<name>/SKILL.md`（前缀必须 `baoyu-`）
2. 写好第三人称 `description`（含「做什么 + 何时用」）
3. 正文写清 workflow；需要脚本则加 `scripts/` 与 Script Directory 段
4. 需要用户选择 → 内联 `## User Input Tools`
5. 需要出位图 → 内联 `## Image Generation Tools`，并强制先写 prompt 文件
6. 支持偏好 → 约定 `EXTEND.md` 路径与 schema
7. 在 `marketplace.json` 的 `skills` 数组里注册路径
8. 更新 README / CHANGELOG（若走正式发布）

详细模板见 [creating-skills.md](./creating-skills.md)。

---

## 5. 复杂 Skill 怎么设计：以「看 K 线走势」为例

目标假设：用户说「帮我看看 000001 最近日线」或「分析这段 K 线」，Skill 能拉行情、算指标、画图、给出结构化解读。

### 5.1 先拆责任：什么归模型，什么归脚本

| 能力 | 谁做 | 原因 |
|------|------|------|
| 解析用户要看哪只标的、周期、区间 | Agent（按 SKILL 问清） | 自然语言歧义 |
| 拉取 OHLCV、算 MA/MACD/RSI | **脚本** | 必须精确、可测 |
| 画蜡烛图 / 叠加指标 | **脚本**（或脚本出数据 + 图后端渲染） | 几何与坐标要稳 |
| 「这是上升通道 / 可能假突破」等解读 | Agent（基于脚本输出的结构化事实） | 需要语言与推理 |
| 免责声明、禁止荐股措辞 | SKILL.md 硬规则 | 合规与一致性 |

**反模式**：让模型「肉眼看」一张糊图就下结论，或让模型手算均线——既不稳也不好测。

### 5.2 推荐目录骨架

```text
skills/baoyu-kline-analysis/
├── SKILL.md
├── scripts/
│   ├── main.ts                 # CLI 入口
│   ├── fetch-ohlcv.ts          # 数据源适配
│   ├── indicators.ts           # MA/MACD/RSI…
│   ├── render-chart.ts         # 出 SVG/PNG
│   └── types.ts
├── references/
│   ├── data-providers.md       # 各行情源参数、限频
│   ├── indicator-glossary.md   # 指标含义（给 Agent 解读用）
│   ├── chart-styles.md         # 配色、周期默认值
│   ├── analysis-rubric.md      # 解读框架：趋势/结构/量价/风险
│   └── config/
│       ├── first-time-setup.md
│       └── preferences-schema.md
└── fixtures/                   # 离线样例 K 线，便于测试
    └── sample-daily.json
```

### 5.3 SKILL.md 主流程建议

写成 Agent 必须遵守的步骤（示意）：

```text
Step 0  加载 EXTEND.md（数据源、默认周期、是否出图、语言）
Step 1  解析输入：代码/名称、市场、周期、区间；缺则 AskUserQuestion
Step 2  调用脚本拉数 + 算指标，得到 JSON 事实包（禁止跳过脚本）
Step 3  （可选）脚本渲染图表到 outputs/...
Step 4  按 references/analysis-rubric.md 解读；只引用 JSON 里存在的事实
Step 5  输出：摘要 + 关键节点 + 图表路径 + 风险提示
```

关键硬约束示例（应写进 SKILL.md）：

- **不得**编造未出现在脚本输出中的价格或指标数值
- **不得**给出买卖建议或目标价；只做结构描述与风险提示
- 脚本失败时展示 stderr，并询问是否换数据源 / 缩小区间
- 若要「AI 插画风」封面另走图像后端；**K 线本体**优先脚本矢量/像素渲染，保证刻度正确

### 5.4 CLI 契约（脚本侧）

让 Agent 调用时参数稳定、输出可解析：

```bash
bun {baseDir}/scripts/main.ts \
  --symbol 000001.SZ \
  --interval 1d \
  --lookback 120 \
  --indicators ma,macd,rsi \
  --out-dir outputs/kline-000001 \
  --format json+svg
```

建议 stdout 最后一行是机器可读 JSON：

```json
{
  "status": "ok",
  "symbol": "000001.SZ",
  "interval": "1d",
  "bars": 120,
  "last_close": 11.23,
  "indicators": { "ma20": 11.01, "rsi14": 58.2 },
  "structure_hints": ["higher_lows_last_20", "volume_shrink_on_pullback"],
  "chart": "outputs/kline-000001/chart.svg",
  "facts_path": "outputs/kline-000001/facts.json"
}
```

`structure_hints` 用 **枚举标签**，由脚本用规则生成；Agent 再翻译成人话。这样复杂功能仍然可测、可回归。

### 5.5 数据源与偏好

`EXTEND.md` 示例字段：

```yaml
---
version: 1
default_provider: eastmoney   # 或 yahoo / tuShare / 自建 API
default_interval: 1d
default_lookback: 120
preferred_chart: svg          # svg | png
language: zh
---
```

`.env` 示例：

```bash
TUSHARE_TOKEN=...
# 或自建代理
KLINE_API_BASE=https://your-gateway.example/ohlcv
```

在 `references/data-providers.md` 写清：鉴权、字段映射、交易时段、复权规则。Agent 只选 provider，不自己拼脆弱 URL。

### 5.6 复杂度升级路径

| 阶段 | 能力 | 做法 |
|------|------|------|
| MVP | 单标的日线 + MA + SVG + 三段解读 | 一个 `main.ts` + 短 SKILL |
| v1 | 多周期、MACD/RSI、对比两标的 | 拆 modules；rubric 加章节 |
| v2 | 用户上传截图辅助 | 脚本出主图；截图仅作参考，数值仍以 OHLCV 为准 |
| v3 | 组合/回测片段 | 另开 `baoyu-*-backtest`，本 skill 只做「看」 |

原则：**一个 skill 一件主任务**。K 线分析不要顺带做自动下单；发布类、回测类拆开，避免 description 抢路由、流程膨胀。

### 5.7 与「出图类 skill」的协作

- **精确 K 线**：本 skill 的 `render-chart.ts`（推荐）
- **封面/情绪插画**：委托 `baoyu-image-gen` / `GenerateImage`，prompt 里写「示意图，非交易刻度」
- **幻灯片汇报**：先完成本 skill，再把结论丢给 `baoyu-slide-deck`

跨 skill 调用时：在 SKILL.md 写「何时委托、传什么路径」，但 **不要**依赖仓库相对路径去读兄弟 skill 的文件内容；假设对方已安装即可。

---

## 6. 复杂 Skill 设计检查清单

- [ ] `description` 能让路由稳定命中，且不与现有 skill 抢词
- [ ] `SKILL.md` < 500 行；细则进 `references/`
- [ ] 数值 / IO / 鉴权进 `scripts/`，有 CLI 与 JSON 输出
- [ ] 有确认门或明确的「直接生成」跳过条件
- [ ] `EXTEND.md` + first-time-setup 路径齐全
- [ ] 用户输入、图像后端等跨运行时约定已内联
- [ ] 失败可重试、错误对用户可读
- [ ] 有 fixtures / 最小测试（脚本单测或 golden JSON）
- [ ] 合规边界写死（金融类尤其重要）
- [ ] 已注册 `marketplace.json`；目录可被单独拷贝使用

---

## 7. 和你这次实践的对应关系

| 你做的事 | 对应原理 |
|----------|----------|
| 选 article-illustrator 配图 | description 路由 + 流程编排型 skill |
| 首次问答写 EXTEND.md | 偏好外置，技能可移植 |
| prompts 先落盘再调 Qwen | 可复现 + 可换后端 |
| Google 额度不够换 DashScope | 同一 skill 契约，换 provider |
| 内容审核改 prompt 再生成 | 脚本/API 约束反馈进流程，而不是改「模型性格」 |

若下一步要做 `baoyu-kline-analysis`，建议顺序：先实现 `fetch + indicators + svg + facts.json`，再写短 SKILL 把 Agent 绑在「只依据 facts 解读」上，最后再加多数据源与 EXTEND。

---

## 8. 相关文档

| 文档 | 用途 |
|------|------|
| [creating-skills.md](./creating-skills.md) | 新建 skill 的格式与必填段 |
| [image-generation-tools.md](./image-generation-tools.md) | 出图后端选择规则（作者向） |
| [user-input-tools.md](./user-input-tools.md) | 向用户提问的约定（作者向） |
| [testing.md](./testing.md) | 测试约定 |
| 仓库根 `CLAUDE.md` | 维护者总览：架构、安全、发布 |
