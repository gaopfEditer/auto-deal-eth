# 加密货币自动交易策略分析系统

基于浏览器自动化 + Gemini AI 的自动交易策略分析工具

## 功能特性

- ✅ 支持多币种监控（ETH、BTC、SOL等）
- ✅ 自动切换4个周期（15m/30m/1h/2h）截图
- ✅ 智能图片组合，节省75%的API调用和token
- ✅ 使用Selenium自动化浏览器操作
- ✅ 调用Gemini API进行AI分析
- ✅ 输出JSON格式的交易策略
- ✅ 支持钉钉/Telegram机器人通知
- ✅ 灵活的时间区间调度（支持跨天时间段）

## 项目结构

```
auto-deal-eth/
├── config.py              # 配置文件（3部分）
├── browser_automation.py   # 浏览器自动化（3部分）
├── gemini_analyzer.py      # Gemini分析模块（3部分）
├── notifier.py             # 通知模块（3部分）
├── main.py                 # 主程序（3部分）
├── requirements.txt        # 依赖包
└── README.md              # 说明文档
```

## 安装步骤

### 1. 创建虚拟环境（推荐）

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 或
venv\Scripts\activate  # Windows
```

### 2. 安装Python依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

创建 `.env` 文件（参考 `.env.example`）：

```env
# Gemini API配置
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash

# 币种配置（用逗号分隔）
SYMBOLS=ETH,BTC,SOL

# 定时任务配置
# 时间区间（用逗号分隔，留空表示全天执行）
TIME_RANGES=1:00-3:00,20:00-22:00
# 执行间隔（分钟）
RUN_INTERVAL_MINUTES=15

# 通知配置（至少配置一个）
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=your_token
# 或
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Chrome浏览器配置（可选）
USE_REMOTE_DEBUGGING=False
CHROME_HEADLESS=False
```

## 使用方法

### 立即执行一次（测试用）

```bash
python main.py --once
```

立即执行一次分析，不进入定时任务模式。

### 启动定时任务

```bash
python main.py
```

按照配置的时间区间和间隔自动执行。

## 工作流程

### 单币种流程

1. **截图阶段**：切换到指定币种，自动切换4个周期（15m/30m/1h/2h）并截图
2. **组合阶段**：将4张截图组合成一张2x2布局的图片（节省token）
3. **分析阶段**：将组合图片上传到Gemini API，使用AI分析K线图
4. **通知阶段**：将分析结果格式化为JSON，通过钉钉/Telegram发送

### 多币种流程

程序会遍历所有配置的币种，为每个币种执行上述流程，最后汇总所有结果发送通知。

## 配置说明

### 多币种配置

#### 方式1：在 config.py 中配置

```python
# 币种配置
SYMBOLS = ['ETH', 'BTC', 'SOL']  # 监控多个币种
```

#### 方式2：在 .env 文件中配置

```env
SYMBOLS=ETH,BTC,SOL
```

#### 默认配置

如果不配置，默认只监控 ETH：
```python
SYMBOLS = ['ETH']
```

### 定时任务配置

#### 时间区间配置

程序支持在指定时间段内执行，支持多个时间段和跨天时间段。

**方式1：在 config.py 中配置**

```python
# 执行时间区间列表，格式: ["1:00-3:00", "20:00-22:00"]
# 留空或空列表表示全天执行
TIME_RANGES = ["1:00-3:00", "20:00-22:00"]

# 执行间隔（分钟），在时间区间内按照此间隔执行
RUN_INTERVAL_MINUTES = 15
```

**方式2：在 .env 文件中配置**

```env
# 时间区间配置（用逗号分隔）
TIME_RANGES=1:00-3:00,20:00-22:00

# 执行间隔（分钟）
RUN_INTERVAL_MINUTES=15
```

#### 配置示例

**示例1：只在特定时间段执行**

```python
TIME_RANGES = ["1:00-3:00", "20:00-22:00"]
RUN_INTERVAL_MINUTES = 15
```

**效果**：
- 在 1:00-3:00 时间段内，每 15 分钟执行一次
- 在 20:00-22:00 时间段内，每 15 分钟执行一次
- 其他时间段不执行

**示例2：全天执行**

```python
TIME_RANGES = []  # 空列表表示全天执行
RUN_INTERVAL_MINUTES = 15
```

**效果**：全天每 15 分钟执行一次

**示例3：跨天时间段**

```python
TIME_RANGES = ["22:00-2:00"]  # 支持跨天
RUN_INTERVAL_MINUTES = 30
```

**效果**：从 22:00 到次日 2:00，每 30 分钟执行一次

**示例4：交易时段配置**

```python
# 亚洲时段 + 欧美时段
TIME_RANGES = ["1:00-3:00", "8:00-10:00", "20:00-22:00"]
RUN_INTERVAL_MINUTES = 15
```

#### 时间格式说明

- 格式：`HH:MM-HH:MM`
- 示例：`1:00-3:00`、`20:00-22:00`、`22:00-2:00`（跨天）
- 支持 24 小时制
- 支持跨天时间段（如 `22:00-2:00`）

### 图片组合说明

程序会将4个周期的截图组合成一张2x2布局的图片，这样可以：

- **节省75%的API调用**：从4次调用减少到1次
- **节省token消耗**：只发送一张组合图片
- **提高分析效率**：AI可以同时看到4个周期的对比

**布局（2x2）**：
```
┌──────────┬──────────┐
│  15分钟  │  30分钟  │
│          │          │
├──────────┼──────────┤
│  1小时   │  2小时   │
│          │          │
└──────────┴──────────┘
```

**文件命名**：
- 单个周期：`{SYMBOL}_{TIMEFRAME}.png`（如 `ETH_15m.png`）
- 组合图片：`{SYMBOL}_combined.png`（如 `ETH_combined.png`）

## Chrome浏览器配置

### 方式1：直接打开浏览器（默认）

程序会直接打开系统默认的Chrome浏览器，使用系统默认配置。

```python
USE_REMOTE_DEBUGGING = False
```

### 方式2：远程调试模式（推荐，使用已登录的账号）

如果需要使用已登录TradingView的账号，可以使用远程调试模式：

1. **以远程调试模式启动Chrome**：

**Windows:**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**Mac:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

2. **在Chrome中登录TradingView**

3. **配置程序使用远程调试**：

```python
USE_REMOTE_DEBUGGING = True
CHROME_DEBUG_PORT = 9222
```

详细说明请查看 `CHROME_USAGE.md` 文件。

## 注意事项

1. **Gemini API密钥**：需要有效的Gemini API密钥
2. **币种格式**：使用大写字母，如 `ETH`、`BTC`
3. **TradingView支持**：确保币种在TradingView上有对应的交易对（如 ETHUSDT）
4. **执行时间**：多币种会增加执行时间，每个币种大约需要30-60秒
5. **API限制**：注意Gemini API的调用频率限制
6. **时间区间为空**：如果 `TIME_RANGES` 为空列表，程序会全天执行
7. **跨天处理**：程序自动处理跨天的时间段（如 `22:00-2:00`）
8. **时区**：使用系统本地时区

## 技术栈

- **Python 3.8+**
- **Selenium** - 浏览器自动化
- **Google Gemini API** - AI图像分析
- **Schedule** - 定时任务
- **Pillow (PIL)** - 图片处理
- **Requests** - HTTP请求

## 输出示例

### 控制台输出

```
==================================================
开始执行交易策略分析...
==================================================

==================================================
处理币种: ETH
==================================================

[步骤1] 开始截图 ETH...
  正在处理周期: 15m
  正在处理周期: 30m
  正在处理周期: 1h
  正在处理周期: 2h
[OK] ETH 成功截图 4 个周期
  正在组合图片...
[OK] 组合图片已保存: screenshots/ETH_combined.png

[步骤2] 开始Gemini分析 ETH...
  正在分析 ETH 组合图表...
[OK] ETH 分析完成

[步骤3] 发送通知...
[OK] 钉钉消息发送成功

==================================================
分析流程完成！共处理 1 个币种
==================================================
```

### 通知消息格式

```
[REPORT] 加密货币交易策略分析报告

【ETH】
{
    "symbol": "ETH",
    "trend": "上涨",
    "support_level": "3200",
    "resistance_level": "3500",
    "recommendation": "Long",
    "risk_level": "Medium",
    ...
}
```
