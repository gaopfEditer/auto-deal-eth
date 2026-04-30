# Trader 代理工具权限

## 身份

- **Agent ID**: `trader`
- **角色**: 战神 Ares，加密货币交易分析

## 工具权限

| 工具 | 允许 | 说明 |
|------|------|------|
| `exec` | ✅ | 执行 shell，用于查看日志、运行分析脚本 |
| `read` | ✅ | 读取配置文件、K 线数据、历史分析 |
| `write` | ⚠️ 受限 | 仅允许写入 `output/`、`logs/` 目录 |
| `edit` | ⚠️ 受限 | 仅允许编辑 `agents/trader/` 下文件 |
| `web` | ✅ | HTTP 请求，用于调用 Webhook、TradingView API |
| `web.search` (Google) | ❌ | 不开启，避免干扰分析专注度 |
| `browser` | ❌ | 不开启，截图由外部系统完成 |

## 沙箱与执行

- **sandbox.mode**: `non-main`（群聊/线程用沙箱，主 DM 可用 host）
- **elevated**: 仅 `allowFrom` 中指定用户可请求 elevated，用于查看生产日志

## 允许执行的操作

- 运行 `skills/post_analysis.py` 将分析结果 POST 到指定 Webhook
- 读取 `screenshots/`、`output/` 等分析相关目录
- 查看 `logs/` 下的运行日志
- 调用 `https://bz.a.gaopf.top/api/tradingview/receive` 等配置的 Webhook

## 禁止的操作

- 直接修改 `config.py`、`.env` 等敏感配置
- 执行 `rm -rf`、`sudo` 等危险命令（除非 elevated 且用户确认）
- 在未授权群组中执行脚本
