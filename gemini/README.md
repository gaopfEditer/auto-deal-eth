# Gemini 模块

封装 `google-genai` 客户端，复用 `.env` 中的 `GEMINI_API_KEY` / `GEMINI_MODEL`。

## 环境准备

### 1. 安装依赖

```powershell
# 进入项目目录
cd D:\frontend\main\python\auto-deal-eth

# 安装到 venv
.\venv\Scripts\python.exe -m pip install google-genai
```

### 2. 配置密钥

编辑 `.env` 文件，替换以下两行：

```env
GEMINI_API_KEY=你的新密钥
GEMINI_MODEL=gemini-2.5-flash
```

> ⚠️ 密钥必须从 [Google AI Studio](https://aistudio.google.com/) 创建，GitHub 等公开平台上的密钥会被 Google 封禁（403 leaked）。

## 快速使用

### 文本生成

```python
from gemini import get_default_client

client = get_default_client()

# 同步
text = client.generate_text("用一句话介绍以太坊")
print(text)

# 流式
for chunk in client.generate_text_stream("讲个笑话"):
    print(chunk, end="", flush=True)
```

### 图片生成

```python
from PIL import Image

img = client.generate_image(
    "A red circle on white background",
    model="gemini-2.5-flash-image",
    aspect_ratio="1:1",
)
img.save("output.png")
```

### 图片理解（多模态）

```python
desc = client.analyze_image(
    "chart.png",
    prompt="用一句话描述图表中的趋势",
)
print(desc)
```

## 目录结构

```
gemini/
├── __init__.py    # 导出 GeminiClient / get_default_client
├── client.py      # 核心封装
└── demo.py        # 使用示例
```

## 运行示例脚本

```powershell
# 文本 + 图片生成
.\venv\Scripts\python.exe gemini/demo.py

# 仅文本
.\venv\Scripts\python.exe gemini/demo.py --text-only

# 仅图片
.\venv\Scripts\python.exe gemini/demo.py --img-only

# 图片理解
.\venv\Scripts\python.exe gemini/demo.py --analyze

# 自定义文案（-p / --prompt）
python gemini/demo.py --text-only -p "解释什么是 DeFi"
python gemini/demo.py --img-only -p "A blue sky with white clouds"
python gemini/demo.py --analyze -p "这张图的主要信息是什么？"
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `GEMINI_API_KEY` | Google AI API 密钥 | 必填 |
| `GEMINI_MODEL` | 默认模型 | `gemini-2.5-flash` |
| `GEMINI_REQUEST_TIMEOUT` | 请求超时（秒） | `45` |

## 可用模型参考

| 用途 | 推荐模型 |
|------|----------|
| 文本生成（快/便宜） | `gemini-2.5-flash` |
| 文本生成（更强） | `gemini-3.6-flash` |
| 图片生成 | `gemini-2.5-flash-image` / `gemini-3.1-flash-image` |
