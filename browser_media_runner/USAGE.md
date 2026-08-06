# browser_media_runner 用法

通过 **CDP / Selenium 控制已登录的 Chrome**，调用 **Gemini 网页版**（`gemini.google.com`）做两件事：

| 模块 | 方向 | 命令 |
|------|------|------|
| `runner` | 图 / URL → 文本分析 | `python -m browser_media_runner.runner ...` |
| `tti` | 提示词 → 生成图片 | `python -m browser_media_runner.tti ...` |

**不是** Gemini REST API；**不**在本模块里做 TradingView 截图业务。底层在 `gemini_web_automation.py`，浏览器初始化在 `browser_automation.init_browser()`（可用远程调试口 9222）。

---

## 前置条件

1. 安装依赖：`pip install -r requirements.txt`（Selenium 等）
2. Chrome 已登录 Gemini（推荐远程调试）：

```bash
# .env
USE_REMOTE_DEBUGGING=True
CHROME_DEBUG_PORT=9222
```

先用调试口启动 Chrome，再跑命令。

---

## 1. 图文分析（runner）

### 1.1 本地文件 + 提示词文件

```bash
python -m browser_media_runner.runner "D:\path\to\chart.png" -p generic_screenshot.txt --tag smoke
```

### 1.2 本地文件 + 提示词正文

```bash
python -m browser_media_runner.runner "D:\path\to\chart.png" -p "请只输出 JSON，分析图片核心内容" --prompt-text --tag image
```

### 1.3 URL（下游会先截图再上传）

```bash
python -m browser_media_runner.runner "https://example.com/page" -p twitter_style_timeline.txt --tag url
```

内置提示词见 `prompts/`：

- `generic_screenshot.txt`
- `kline_analysis_single.txt` / `kline_analysis_multi.txt`
- `twitter_style_timeline.txt`

结果写入 `history/<run_id>/`（`result.json`、`web_result.json`、`prompt.txt`）。

---

## 2. 文生图（tti）

与 runner **对称**：只传提示词，不上传本地图。

### 2.1 提示词正文

```bash
python -m browser_media_runner.tti -p "一只赛博朋克橘猫坐在月球上看K线图，16:9，无水印" --prompt-text --tag cat
```

### 2.2 提示词文件

```bash
python -m browser_media_runner.tti -p tti_crypto_banner.txt --tag banner
```

### 2.3 指定输出目录

```bash
python -m browser_media_runner.tti -p "深色科技感加密货币海报" --prompt-text --out ./screenshots/tti --keep-browser
```

| 参数 | 说明 |
|------|------|
| `-p / --prompt` | 默认当 `prompts/` 文件名；加 `--prompt-text` 当正文 |
| `--out` | 图片目录（默认 `history/tti_*/images`） |
| `--tag` | 文件名前缀 / 业务标签 |
| `--keep-browser` | 结束后不关浏览器 |
| `--no-history` | 不写 history 元数据目录 |

文生图模板示例：`prompts/tti_crypto_banner.txt`。

账号需支持 Gemini 网页出图；若超时未抓到图，可能只保存整页排查截图。

---

## 3. Python 调用

```python
from browser_media_runner import analyze_resources, text_to_image

# 分析
r = analyze_resources(
    [r"D:\path\to\a.png"],
    "generic_screenshot.txt",
    domain_tag="demo",
)

# 文生图
r2 = text_to_image(
    "霓虹灯下的比特币城市，电影感，16:9",
    prompt_is_text=True,
    domain_tag="city",
    out_dir="./screenshots/tti",
)
print(r2.get("images"))
```

---

## 4. 与仓库其它模块的关系

- `run_gemini_analyzer.py`：本地 Ollama chat-image 路径，**不是**本包。
- `dealMsg` / TradingView 截图：业务截图后可把路径交给 `runner` 做二次分析。
- 环境变量（可选）：`GEMINI_WEB_URL`、`GEMINI_WEB_TTI_WAIT`（文生图等待秒数，默认 90）。
