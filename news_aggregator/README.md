# 热门资讯聚合服务

一个自动获取国际局势、经济、科技、美国经济事件等热门资讯的 Python 服务。

## 功能特点

- 📰 多源新闻聚合（RSS 订阅）
- 🌍 国际局势
- 💰 全球经济
- 🔬 科技动态
- 🇺🇸 美国经济事件
- 🕐 支持定时自动更新
- 📄 支持 JSON 和文本格式输出

## 使用方法

### 1. 手动获取新闻

```bash
# 获取所有类别新闻
python news_service.py

# 获取特定类别
python news_service.py --category international
python news_service.py --category economy
python news_service.py --category tech
python news_service.py --category us_economy

# 限制新闻数量
python news_service.py --limit 3

# 输出 JSON 格式
python news_service.py --json

# 保存到文件
python news_service.py --output news_$(date +%Y%m%d).txt
```

### 2. 快速获取（包装脚本）

```bash
# 获取今日热门资讯
getnews

# 获取特定类别
getnews -c tech

# 保存到文件
getnews -o ~/news_today.txt
```

### 3. 设置定时任务

已配置自动定时任务，每天早上 8 点和晚上 6 点自动获取最新资讯：

- 8:00 - 早间新闻推送
- 18:00 - 晚间新闻汇总

## 新闻来源

| 类别 | 来源 |
|------|------|
| 国际局势 | BBC中文、路透中文网 |
| 全球经济 | 路透财经、华尔街日报 |
| 科技动态 | TechCrunch、The Verge |
| 美国经济 | Bloomberg、CNBC |

## 文件结构

```
services/news_aggregator/
├── news_service.py    # 主服务脚本
├── get_news.bat       # Windows 快速调用
├── get_news.sh        # macOS/Linux 快速调用
├── README.md          # 说明文档
└── output/            # 输出目录（自动创建）
    └── news_YYYY-MM-DD_HH-MM.txt
```

## 自定义配置

编辑 `news_service.py` 中的 `self.sources` 字典来添加/修改新闻源。
