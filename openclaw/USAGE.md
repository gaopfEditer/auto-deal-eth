# OpenClaw 客户端使用说明

本目录是 **auto-deal-eth** 项目内的 Python 客户端，用于从脚本或命令行向本机 [OpenClaw](https://github.com/openclaw/openclaw) 网关提问。

与仓库里的 `openclaw-project/`（多角色 Agent 工程）无关；这里只负责 **连接 + 单次问答**。

---

## 功能介绍

| 能力 | 说明 |
|------|------|
| **acpx（ACP）** | 通过 [acpx](https://github.com/openclaw/acpx) 调用 `openclaw exec`，走 Agent Client Protocol，适合本地已跑 OpenClaw 网关的场景。 |
| **交互模式** | 回复直接打印到终端（Windows 默认），避免管道捕获导致 ACP 握手失败。 |
| **捕获模式** | 将 acpx 的 stdout 写入临时文件再读回，便于在代码里拿到字符串返回值。 |
| **自动重试** | 出现 `invalid handshake` 等网关忙错误时，按配置重试若干次。 |
| **中文 prompt** | Windows / 非 ASCII 内容通过 `-f` 临时 UTF-8 文件传给 acpx，避免命令行乱码。 |
| **HTTP 回退** | acpx 失败时可选用 `test/openclawApi.py` 的 webhook + 轮询链路（需网关 HTTP 接口可用）。 |

### 模块结构

```
openclaw/
  __init__.py       # 对外 API：ask、acpx_*、http_*
  client.py         # ask() 统一入口
  acpx.py           # acpx CLI 封装
  http_fallback.py  # HTTP webhook 封装
  _env.py           # 加载项目根目录 .env
  cli.py            # 命令行
```

---

## 前置条件

1. **Node.js**（含 `npx`）
2. **OpenClaw CLI**（本机可执行 `openclaw`，如 OpenClaw-CN）
3. **OpenClaw 网关已运行**（默认 `http://127.0.0.1:18789`）

检查网关：

```bash
openclaw gateway status
```

若 acpx 频繁 `Internal error` / `invalid handshake`：

```bash
openclaw gateway restart
```

并结束残留的 `openclaw acp` 进程后再试。

4. **Python 依赖**（项目根目录）：

```bash
pip install python-dotenv requests
```

acpx 首次运行会自动 `npx acpx@latest`，无需单独安装。

---

## 运行方法

### 1. 命令行（推荐）

在项目根目录执行：

```bash
# 方式 A：模块入口
python -m openclaw.cli 你支持图片分析吗

# 方式 B：等价
python -m openclaw 现在你用的啥模型

# 方式 C：测试脚本（薄封装，逻辑相同）
python test/test_win_qa.py 你的问题
```

无参数时使用默认问题：`你支持图片分析吗`。

### 2. 在 Python 代码中调用

```python
from openclaw import ask

# 推荐：自动选择交互/捕获，并可按环境变量 HTTP 回退
answer = ask("总结一下当前 ETH 走势")
print(answer)
```

仅走 acpx、不要 HTTP 回退：

```python
from openclaw import acpx_openclaw_exec

text = acpx_openclaw_exec("ping", interactive=False)
print(text)
```

仅走 HTTP webhook：

```python
from openclaw import http_ask

text = http_ask("ping")
print(text)
```

### 3. 高级：拆分交互 / 捕获

```python
from openclaw import acpx_openclaw_exec_interactive, acpx_openclaw_exec_capture

# 回复打在终端，函数返回空字符串表示成功
rc = acpx_openclaw_exec_interactive("你好")  # 实际返回 int 退出码的封装在 acpx_openclaw_exec

# 在代码里拿字符串（非 Windows 或 ACPX_INTERACTIVE=0 时）
reply = acpx_openclaw_exec_capture("你好", timeout_sec=120)
```

统一入口仍建议用 `ask()`。

---

## 环境变量

在项目根目录 `.env` 中配置（导入 `openclaw` 时会自动 `load_dotenv`）。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENCLAW_AGENT_TIMEOUT` | `300` | acpx `--timeout`（秒） |
| `OPENCLAW_ACPX_RETRIES` | `3` | acpx 失败重试次数 |
| `ACPX_INTERACTIVE` | （未设） | `1` 强制交互输出；`0` 强制捕获 stdout |
| `ACPX_VERBOSE` | （未设） | `1` 时 acpx 加 `--verbose` |
| `OPENCLAW_HTTP_FALLBACK` | （未设） | `1` 时 acpx 失败后走 HTTP |
| `OPENCLAW_SESSION_HISTORY_KEY` | （未设） | HTTP 回退时 sessions/history 的 sessionKey |
| `OPENCLAW_HISTORY_POLL_INTERVAL` | `3` | HTTP 轮询间隔（秒） |
| `OPENCLAW_BASE_URL` | `http://127.0.0.1:18789` | HTTP 网关地址（见 `test/openclawApi.py`） |
| `OPENCLAW_TOKEN` / `OPENCLAW_WEBHOOK_TOKEN` | （未设） | HTTP Bearer |

### Windows 说明

- 未设置 `ACPX_INTERACTIVE` 时，**默认交互模式**（`interactive=True`），回复在终端显示，`ask()` 可能返回空字符串表示成功。
- 若要在脚本里**拿到返回文本**，请设置：

```bat
set ACPX_INTERACTIVE=0
python -m openclaw.cli 你的问题
```

### macOS / Linux

- 默认使用**捕获模式**（`interactive=False`），便于直接得到字符串返回值。

---

## API 一览

| 函数 | 作用 |
|------|------|
| `ask(prompt, interactive=None, http_fallback=None)` | 统一问答入口 |
| `acpx_openclaw_exec(prompt, interactive=None)` | 仅 acpx |
| `acpx_openclaw_exec_interactive(...)` | acpx，终端输出 |
| `acpx_openclaw_exec_capture(...)` | acpx，返回文本 |
| `openclaw_http_fallback(prompt)` / `http_ask(prompt)` | 仅 HTTP |
| `REPO_ROOT` | 项目根路径常量 |

---

## acpx 命令对照（手动调试）

与包内逻辑等价的手动命令：

```bash
npx acpx@latest --format quiet --approve-all --timeout 300 openclaw exec "你的问题"
```

注意：

- 必须用 **`openclaw exec`**，不能只用 `acpx exec`（默认走 codex）。
- `--format`、`--timeout` 等**全局选项**写在 `openclaw` **之前**。

---

## 常见问题

### 1. `Internal error` / `invalid handshake`

网关连接被占用或状态异常。

1. `openclaw gateway restart`
2. 任务管理器结束多余 `openclaw acp` / node 进程
3. 设置 `ACPX_INTERACTIVE=1` 再试
4. 或 `set OPENCLAW_HTTP_FALLBACK=1` 走 HTTP

### 2. Windows 下 `ask()` 返回空

交互模式成功时回复在终端，不进入返回值。需要字符串时设 `ACPX_INTERACTIVE=0`。

### 3. `未找到 npx`

安装 [Node.js](https://nodejs.org/) 并确认 `npx` 在 PATH 中。

### 4. HTTP 回退报错

确认 `.env` 中 `OPENCLAW_TOKEN`、`OPENCLAW_BASE_URL` 与网关一致；详见 `test/openclawApi.py` 顶部注释。

---

## 相关文件

- `test/test_win_qa.py` — CLI 薄封装示例
- `test/openclawApi.py` — HTTP webhook / history 完整客户端
- `CHROME_USAGE.md` — 浏览器自动化（与 OpenClaw 问答无关）
