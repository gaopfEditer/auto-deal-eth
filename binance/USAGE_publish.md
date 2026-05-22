# 币安广场发帖脚本

`binance/square_publish.py` 通过 **Selenium** 连接本机已登录的 Chrome，在币安广场填写正文、上传图片并发布。与 `binance/market_lists_selenium.py`（抓取关注流/帖子）使用同一套浏览器前置。

后续可在自己的流水线里把 **文字 + 多张图片** 一并传入 `publish_square_post()`。

---

## 功能

| 功能 | 说明 |
|------|------|
| 发文字 | 自动打开发帖入口，填入 `contenteditable` / `textarea` |
| 发多图 | `--image` 可多次指定；走 `input[type=file]` |
| 仅试填 | `--dry-run` / `--no-submit`：填好内容不点「发布」 |
| 结果 | 尽量解析新帖 URL（`/square/post/{id}`） |
| 代码调用 | `from binance import publish_square_post` |

> 官方 OpenAPI 目前仅支持纯文字；**带图发帖需走本脚本（浏览器 UI）**。

---

## 前置条件

1. 安装依赖：`pip install selenium python-dotenv webdriver-manager`
2. 安装 **Google Chrome**，并已登录币安账号（含广场发帖权限）
3. 用远程调试启动 Chrome（与抓取脚本相同）：

**Windows**

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**macOS**

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

4. 确认调试端口：`http://localhost:9222/json` 能打开

---

## 命令行

在项目根目录：

```bash
# 只发文字
python -m binance.square_publish --text "BTC 短线观点：…"

# 从文件读正文
python -m binance.square_publish --text-file ./draft.txt

# 文字 + 多图（后续常用）
python -m binance.square_publish --text "配图说明" --image ./a.png --image ./b.png

# 试填不发布（检查登录与 UI）
python -m binance.square_publish --text "测试" --dry-run

# JSON 结果（便于脚本对接）
python -m binance.square_publish --text "…" --json
```

---

## Python 调用（图文一起发）

```python
from binance import publish_square_post

result = publish_square_post(
    "今日 ETH 观察：…",
    image_paths=[
        r"D:\frontend\main\python\auto-deal-eth\screenshots\eth_1h.png",
        r"D:\frontend\main\python\auto-deal-eth\screenshots\eth_combined.png",
    ],
    submit=True,   # False = 只填不点发布
)

if result.ok:
    print(result.post_url or "请到浏览器确认")
else:
    print(result.error)
```

返回字段（`PublishResult`）：

- `ok`：流程是否成功走完  
- `submitted`：是否已点击发布  
- `post_url`：解析到的帖子链接（可能为空）  
- `error`：失败原因  
- `steps`：步骤轨迹，如 `compose_entry → editor → text → images:2 → submitted`

---

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `BINANCE_SQUARE_PUBLISH_URL` | `https://www.binance.com/zh-CN/square` | 打开的首页 |
| `BINANCE_SQUARE_PUBLISH_WAIT` | `8` | 进入编辑区后等待秒数 |
| `BINANCE_SQUARE_IMAGE_UPLOAD_WAIT` | `12` | 选图后等待上传秒数 |
| `USE_REMOTE_DEBUGGING` | `True` | 见 `config.py`，须为 True |
| `CHROME_DEBUG_PORT` | `9222` | 远程调试端口 |

---

## 与抓取脚本的关系

| 脚本 | 作用 |
|------|------|
| `binance/market_lists_selenium.py` | 抓 Square 关注流、帖子、配图 |
| `binance/square_publish.py` | **发** 广场动态 |
| `binance/browser.py` | 浏览器等待/日志等小工具（共用） |

---

## 常见问题

### 未找到发帖入口

- 确认 Chrome 里已登录币安，且账号有广场创作者/发帖权限  
- 手动打开 [币安广场](https://www.binance.com/zh-CN/square) 看是否有「发帖」按钮  
- 页面改版时可能需要更新脚本里的入口文案（见 `binance/square_publish.py` 顶部 `_COMPOSE_LABELS`）

### 图片未上传

- 先用 `--dry-run` 看编辑区是否出现  
- 加大 `BINANCE_SQUARE_IMAGE_UPLOAD_WAIT`  
- 部分页面需先点「图片」再出现 `input[type=file]`，脚本会尝试自动点击

### 连接 Chrome 失败

与 `CHROME_USAGE.md` / `binance/README.md` 说明相同：先关干净 Chrome，再用 `--remote-debugging-port=9222` 启动。

---

## 后续扩展建议

- 把 TradingView 拼图路径（`capture_all_timeframes_for_symbol` 的 `*_combined.png`）直接作为 `image_paths` 传入  
- 用 `OPENCLAW` / 本地模型生成 `text` 后调用 `publish_square_post`  
- 发布前用 `--dry-run` 做人工确认，确认后再 `submit=True`
