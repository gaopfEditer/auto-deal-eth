# Trader 交易员角色

战神 Ares，专注 K 线技术分析与交易建议。

## 依赖的 API

| API | 用途 | 配置 |
|-----|------|------|
| Gemini | K 线分析、资讯获取 | GEMINI_API_KEY |
| Webhook | 推送分析结果 | config.json / WEBHOOK_URL |

## 输入 / 输出示例

### 输入

- **K 线图**: `screenshots/chart_15m.png` 或组合图
- **触发词**: @Ares、分析、策略

### 输出

```json
{
  "symbol": "ETH",
  "direction": "long",
  "confidence": 0.75,
  "entry": "2400-2420",
  "stop_loss": "2350",
  "take_profit": "2550",
  "reason": "15m/1h 共振上行，支撑有效",
  "timestamp": "2025-02-28T12:00:00Z"
}
```

### 运行

```bash
python skills/gemini_analyze.py ./chart.png
python skills/gemini_analyze.py --role trader  # 资讯模式
python skills/post_analysis.py --file output/analysis.json
```
