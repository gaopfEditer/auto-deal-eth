# ETH自动交易策略分析系统

基于浏览器自动化 + Gemini AI 的自动交易策略分析工具

## 功能特性

- ✅ 自动切换4个周期（15m/30m/1h/2h）截图
- ✅ 使用Playwright自动化浏览器操作
- ✅ 调用Gemini API进行多图分析
- ✅ 输出JSON格式的交易策略
- ✅ 支持钉钉/Telegram机器人通知

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

### 3. 安装Playwright浏览器

```bash
playwright install chromium
```

### 3. 配置环境变量

创建 `.env` 文件（参考 `.env.example`）：

```env
# Gemini API配置
GEMINI_API_KEY=your_gemini_api_key_here

# TradingView配置
TRADINGVIEW_URL=https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT

# 通知配置（至少配置一个）
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=your_token
# 或
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 定时任务配置
RUN_INTERVAL_MINUTES=15
```

## 使用方法

### 立即执行一次

```bash
python main.py --once
```

### 启动定时任务

```bash
python main.py
```

程序会按照配置的时间间隔自动执行分析。

## 工作流程

1. **截图阶段**：自动打开TradingView，切换4个周期（15m/30m/1h/2h）并截图
2. **分析阶段**：将截图上传到Gemini API，使用AI分析K线图
3. **通知阶段**：将分析结果格式化为JSON，通过钉钉/Telegram发送

## 注意事项

- 需要有效的Gemini API密钥
- TradingView可能需要登录，请根据实际情况调整
- 截图选择器可能需要根据实际页面结构调整
- 建议在服务器或24小时运行的机器上部署

## 技术栈

- **Python 3.8+**
- **Playwright** - 浏览器自动化
- **Google Gemini API** - AI图像分析
- **Schedule** - 定时任务
- **Requests** - HTTP请求
