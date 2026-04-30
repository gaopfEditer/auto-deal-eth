# Message Hub 快速启动指南

## 第一步：启动 Message Hub 服务器

```bash
cd C:\Users\eason\openclaw\skills\message-hub

# 方式 1: 直接运行
python server.py

# 方式 2: 使用启动脚本 (Windows)
start.bat
```

服务器启动后显示：
```
WebSocket server started on ws://0.0.0.0:8765
HTTP server started on http://0.0.0.0:8766
Message Hub is running. Press Ctrl+C to stop.
```

## 第二步：配置执行器

编辑 `config.json`（如果需要修改默认配置）：

```json
{
  "ws_host": "0.0.0.0",
  "ws_port": 8765,
  "webhook_host": "0.0.0.0",
  "webhook_port": 8766,
  "webhook_base_url": "http://192.168.1.100:8766"  // 如果是多机部署，改为实际 IP
}
```

## 第三步：启动执行器

### 方式 A: 使用启动脚本（推荐）

```bash
start_executor.bat
```

按提示输入配置，或直接回车使用默认值。

### 方式 B: 手动设置环境变量

```bash
# Windows
set EXECUTOR_ID=openclaw_main
set WS_URL=ws://localhost:8765
set WEBHOOK_URL=http://localhost:8766/webhook/result
python openclaw_executor.py

# Linux/Mac
export EXECUTOR_ID=openclaw_main
export WS_URL=ws://localhost:8765
export WEBHOOK_URL=http://localhost:8766/webhook/result
python openclaw_executor.py
```

## 第四步：验证连接

### 检查 Hub 状态

```bash
curl http://localhost:8766/status
```

预期响应：
```json
{
  "executors": {
    "openclaw_main": {
      "executor_id": "openclaw_main",
      "state": "PENDING",
      "current_task": null
    }
  },
  "executor_count": 1,
  "available_executors": 1,
  "queue_length": 0
}
```

### 运行测试脚本

```bash
python test.py
```

## 第五步：提交任务

### 使用 curl

```bash
curl -X POST http://localhost:8766/webhook/task \
  -H "Content-Type: application/json" \
  -d '{
    "id": "task_001",
    "payload": {
      "action": "web_search",
      "params": {
        "query": "最新加密货币行情",
        "count": 5
      }
    },
    "priority": 1
  }'
```

### 使用 Python

```python
import requests

response = requests.post(
    "http://localhost:8766/webhook/task",
    json={
        "id": "task_001",
        "payload": {
            "action": "web_search",
            "params": {"query": "test", "count": 3}
        }
    }
)
print(response.json())
```

## 多执行器部署

在多台机器上部署执行器：

### 机器 A (192.168.1.100)
```bash
# 启动 Hub
python server.py

# 启动本地执行器
set EXECUTOR_ID=openclaw_A
python openclaw_executor.py
```

### 机器 B (192.168.1.101)
```bash
# 只启动执行器，连接到机器 A 的 Hub
set EXECUTOR_ID=openclaw_B
set WS_URL=ws://192.168.1.100:8765
set WEBHOOK_URL=http://192.168.1.100:8766/webhook/result
python openclaw_executor.py
```

## 常见问题

### Q: 执行器连接失败
A: 检查：
1. Hub 服务器是否运行
2. 防火墙是否开放 8765 端口
3. WS_URL 是否正确

### Q: 任务提交后无响应
A: 检查：
1. 执行器是否已注册 (`GET /status`)
2. 执行器是否处于 BUSY 状态
3. 查看 `message-hub.log` 日志

### Q: 如何停止服务
A: 按 `Ctrl+C` 终止进程

## 下一步

- 阅读 `SKILL.md` 了解完整的 API 文档
- 阅读 `prompt.md` 配置 OpenClaw 集成
- 自定义 `openclaw_executor.py` 添加新的任务类型
