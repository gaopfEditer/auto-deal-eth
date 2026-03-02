# Auditor 技术审计角色

技术审计、监控 3123 端口与日志。

## 依赖的 API

| API | 用途 | 配置 |
|-----|------|------|
| Webhook | 接收 trader 结果、转发审核 | config.json |

## 输入 / 输出示例

### 输入

- trader 完成后的 Webhook 回调
- `output/` 下的分析结果 JSON

### 输出

- 审核通过 / 驳回
- 触发 operator 发送 Telegram

待完善。
