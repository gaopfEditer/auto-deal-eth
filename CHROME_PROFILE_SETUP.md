# Chrome 用户配置文件设置指南

## 目的

使用已登录 TradingView 的 Chrome 账号进行截图，而不是使用无痕模式。

## 如何找到 Chrome 用户配置文件路径

### Windows 系统

1. **找到用户数据目录**
   - 默认路径：`C:\Users\你的用户名\AppData\Local\Google\Chrome\User Data`
   - 或者按 `Win + R`，输入 `%LOCALAPPDATA%\Google\Chrome\User Data` 回车

2. **确定要使用的配置文件**
   - 打开 Chrome 浏览器
   - 在地址栏输入：`chrome://version/`
   - 查看 "配置文件路径" 这一行
   - 例如：`C:\Users\eason\AppData\Local\Google\Chrome\User Data\Profile 1`
   - 其中：
     - `C:\Users\eason\AppData\Local\Google\Chrome\User Data` 是用户数据目录
     - `Profile 1` 是配置文件名称

3. **如果有多个账号**
   - 打开 Chrome，点击右上角头像
   - 可以看到所有已添加的账号
   - 每个账号对应一个 Profile（如 Profile 1, Profile 2, Default 等）
   - 找到已登录 TradingView 的那个账号对应的 Profile

## 配置方法

### 方法1：在 .env 文件中配置（推荐）

创建或编辑项目根目录下的 `.env` 文件：

```env
# Chrome用户数据目录（完整路径，包含 User Data）
CHROME_USER_DATA_DIR=C:\Users\你的用户名\AppData\Local\Google\Chrome\User Data

# Chrome配置文件名称（如 Profile 1, Profile 2, Default）
# 如果留空，则使用默认配置文件
CHROME_PROFILE_NAME=Profile 1

# 是否使用无头模式（True=无界面，False=有界面）
# 使用用户配置文件时建议设为 False，方便调试
CHROME_HEADLESS=False
```

### 方法2：直接在 config.py 中修改

编辑 `config.py` 文件，修改以下配置：

```python
CHROME_USER_DATA_DIR = 'C:\\Users\\你的用户名\\AppData\\Local\\Google\\Chrome\\User Data'
CHROME_PROFILE_NAME = 'Profile 1'  # 或 'Profile 2', 'Default' 等
CHROME_HEADLESS = False  # 设为 False 可以看到浏览器窗口
```

## 重要注意事项

### ⚠️ 使用前必须关闭 Chrome

**非常重要**：在使用用户配置文件之前，必须关闭所有 Chrome 浏览器窗口！

如果 Chrome 正在运行，Selenium 无法访问用户配置文件，会报错。

### 步骤

1. **关闭所有 Chrome 窗口**
   - 包括所有标签页
   - 检查任务栏是否有 Chrome 图标
   - 如果任务管理器中还有 Chrome 进程，结束它们

2. **运行程序**
   ```powershell
   python main.py --once
   ```

3. **程序运行完成后，可以重新打开 Chrome**

## 配置示例

### 示例1：使用 Profile 1（第一个账号）

```env
CHROME_USER_DATA_DIR=C:\Users\eason\AppData\Local\Google\Chrome\User Data
CHROME_PROFILE_NAME=Profile 1
CHROME_HEADLESS=False
```

### 示例2：使用 Default 配置文件

```env
CHROME_USER_DATA_DIR=C:\Users\eason\AppData\Local\Google\Chrome\User Data
CHROME_PROFILE_NAME=Default
CHROME_HEADLESS=False
```

### 示例3：使用无痕模式（不登录）

```env
# 留空或删除这两行，程序会自动使用无痕模式
# CHROME_USER_DATA_DIR=
# CHROME_PROFILE_NAME=
CHROME_HEADLESS=True
```

## 验证配置

运行程序后，如果看到以下输出，说明配置成功：

```
[INFO] 使用Chrome用户配置文件: C:\Users\...\User Data
[INFO] 使用配置文件: Profile 1
[INFO] 使用有界面模式（可以看到浏览器窗口）
```

如果看到以下输出，说明使用的是无痕模式：

```
[INFO] 使用无痕模式（未登录状态）
```

## 常见问题

### Q1: 报错 "user data directory is already in use"

**原因**：Chrome 浏览器正在运行

**解决**：关闭所有 Chrome 窗口和进程，然后重新运行程序

### Q2: 找不到配置文件

**原因**：配置文件名称不正确

**解决**：
1. 打开 Chrome，输入 `chrome://version/` 查看实际路径
2. 确认 Profile 名称（可能是 `Profile 1`, `Profile 2`, `Default` 等）
3. 在配置中使用正确的名称

### Q3: 仍然显示未登录状态

**原因**：可能使用了错误的 Profile

**解决**：
1. 确认哪个 Profile 登录了 TradingView
2. 在 Chrome 中切换到该账号，查看 `chrome://version/` 确认 Profile 名称
3. 更新配置中的 `CHROME_PROFILE_NAME`

## 快速查找命令

在 PowerShell 中运行以下命令，可以快速找到 Chrome 用户数据目录：

```powershell
$env:LOCALAPPDATA + "\Google\Chrome\User Data"
```

