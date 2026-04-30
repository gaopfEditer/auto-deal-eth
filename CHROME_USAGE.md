# Chrome 浏览器使用指南

## 两种使用方式

### 方式1：远程调试模式（推荐，使用已打开的Chrome）

连接到已经运行的 Chrome 浏览器，使用当前已登录的账号。

#### 优点
- ✅ 使用当前已登录的账号（包括 TradingView）
- ✅ 不需要关闭 Chrome
- ✅ 不会被 Google 屏蔽
- ✅ 可以看到浏览器操作过程

#### 使用步骤

**Windows:**

1. **关闭所有 Chrome 窗口**（如果正在运行）

2. **以远程调试模式启动 Chrome**：
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
   ```
   
   或者创建快捷方式：
   - 右键 Chrome 快捷方式 → 属性
   - 在"目标"后面添加：` --remote-debugging-port=9222`
   - 例如：`"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222`

3. **登录 TradingView**（如果需要）

4. **运行程序**：
   ```powershell
   python main.py --once
   ```

**Mac:**

1. **关闭所有 Chrome 窗口**（如果正在运行）

2. **以远程调试模式启动 Chrome**：
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
   ```
   
   或者创建别名（添加到 `~/.zshrc` 或 `~/.bash_profile`）：
   ```bash
   alias chrome-debug='/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222'
   ```
   然后运行：`chrome-debug`

3. **登录 TradingView**（如果需要）

4. **运行程序**：
   ```bash
   python main.py --once
   ```

### 方式2：直接打开浏览器模式

直接打开一个新的 Chrome 窗口，使用系统默认配置。

#### 优点
- ✅ 简单，不需要手动启动 Chrome
- ✅ 使用系统默认的 Chrome 配置

#### 缺点
- ⚠️ 如果 Chrome 正在运行，可能会有冲突
- ⚠️ 可能无法使用已登录的账号（取决于系统配置）

#### 使用步骤

1. **配置**（在 `config.py` 或 `.env` 文件中）：
   ```python
   USE_REMOTE_DEBUGGING = False
   ```

2. **运行程序**：
   ```powershell
   python main.py --once
   ```

## 配置说明

### 在 config.py 中配置

```python
# 使用远程调试模式（推荐）
USE_REMOTE_DEBUGGING = True  # 或 False
CHROME_DEBUG_PORT = 9222     # 远程调试端口
CHROME_HEADLESS = False       # 是否无头模式（远程调试时无效）
```

### 在 .env 文件中配置

```env
USE_REMOTE_DEBUGGING=True
CHROME_DEBUG_PORT=9222
CHROME_HEADLESS=False
```

## 常见问题

### Q1: 连接失败 "connection refused"

**原因**：Chrome 未以远程调试模式启动

**解决**：
1. 确保 Chrome 已关闭
2. 使用 `--remote-debugging-port=9222` 参数启动 Chrome
3. 重新运行程序

### Q2: 无法使用已登录的账号

**原因**：直接打开浏览器模式可能无法访问已登录状态

**解决**：使用远程调试模式（方式1）

### Q3: Chrome 启动失败

**原因**：Chrome 正在运行，导致冲突

**解决**：
1. 关闭所有 Chrome 窗口
2. 或使用远程调试模式

### Q4: 如何确认远程调试已启用？

打开 Chrome，访问：`http://localhost:9222/json`

如果能看到 JSON 数据，说明远程调试已启用。

## 推荐配置

**推荐使用远程调试模式**，因为：
- 可以使用已登录的账号
- 不会被 Google 屏蔽
- 更稳定可靠

只需在启动 Chrome 时添加 `--remote-debugging-port=9222` 参数即可。

