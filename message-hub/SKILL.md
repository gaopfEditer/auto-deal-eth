---
name: message-hub
description: 用于连接到外部消息中心服务的 JavaScript 客户端技能，提供 WebSocket 连接、Webhook 支持、心跳机制和 OpenClaw 集成。使用时需要连接到运行在 3123 端口的 JWT 认证系统消息中心，接收 openclaw_next_role 任务并处理，将任务结果发送回 Webhook。
---

# Message Hub 客户端技能

用于连接到外部消息中心服务的 JavaScript 客户端技能。

## 技能描述

当用户需要连接到外部消息中心服务（WebSocket + Webhook）时使用此技能。该技能提供完整的客户端实现，包括连接管理、消息处理、任务执行和结果回调。

## 使用场景

- 连接到运行在 3123 端口的 JWT 认证系统消息中心
- 接收 `openclaw_next_role` 任务并处理
- 将任务结果发送回 Webhook
- 在 OpenClaw 环境中作为执行器节点运行

## 核心文件

### 1. 通用执行器 (`executor.js`)
- 连接到 WebSocket 服务器
- 处理通用任务消息
- 发送心跳保持连接
- 记录详细日志到文件

### 2. OpenClaw 专用执行器 (`openclaw_executor.js`)
- 专为 OpenClaw 环境优化
- 支持 OpenClaw 工具调用
- 处理 `openclaw_next_role` 任务
- 集成 OpenClaw 提示词

### 3. 测试脚本 (`test.js`)
- 测试 WebSocket 连接
- 测试 Webhook 功能
- 验证完整的工作流程

### 4. 启动脚本 (`start.js`)
- 提供多种启动选项
- 管理环境变量
- 简化部署流程

## 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `EXECUTOR_ID` | 执行器唯一标识 | `executor_js` |
| `WS_URL` | WebSocket 服务器地址 | `ws://localhost:3123/api/ws?type=openclaw` |
| `WEBHOOK_URL` | Webhook 回调地址 | `http://localhost:3123/api/openclaw/webhook` |
| `LOG_FILE` | 日志文件路径 | `./message-hub-client.log` |

### 配置文件 (`config.json`)
```json
{
  "ws_host": "0.0.0.0",
  "ws_port": 3123,
  "webhook_host": "0.0.0.0",
  "webhook_port": 3123,
  "webhook_base_url": "http://localhost:3123",
  "auth_token": "",
  "max_concurrent_tasks": 5,
  "task_timeout_seconds": 300
}
```

## 使用示例

### 基本使用

```bash
# 安装依赖
cd C:\Users\eason\openclaw\skills\message-hub
npm install

# 启动通用执行器
npm start

# 或使用环境变量
EXECUTOR_ID=my_executor node executor.js
```

### OpenClaw 集成

```bash
# 启动 OpenClaw 专用执行器
node start.js --openclaw

# 自定义配置
EXECUTOR_ID=openclaw_main \
WS_URL=ws://localhost:3123/api/ws?type=openclaw \
node openclaw_executor.js
```

### 测试连接

```bash
# 运行完整测试
node start.js --test

# 指定端口测试
PORT=3123 node test.js
```

## 消息协议

### WebSocket 连接
- 连接 URL: `ws://host:port/api/ws?type=openclaw`
- 必须包含 `type=openclaw` 查询参数
- 连接后接收 `welcome` 消息获取 `clientId`

### 任务分发
1. 服务端通过 Webhook 发送 `nextRole`
2. 客户端通过 WebSocket 接收 `openclaw_next_role`
3. 客户端处理任务
4. 客户端通过 Webhook 返回结果

### 心跳机制
- 每30秒发送一次心跳
- 心跳包含执行器状态和当前任务
- 服务端通过心跳检测连接状态

## 日志系统

### 日志文件
- `message-hub-client.log` - 通用执行器日志
- `openclaw-executor.log` - OpenClaw 执行器日志
- `test.log` - 测试脚本日志
- `start.log` - 启动脚本日志

### 日志格式
```
[2026-03-16T10:00:00.000Z] [INFO] 连接 WebSocket: ws://localhost:3123/api/ws?type=openclaw
[2026-03-16T10:00:00.100Z] [INFO] WebSocket 连接成功
[2026-03-16T10:00:00.200Z] [INFO] 收到消息: welcome {"clientId":"client_123"}
```

## 故障排除

### 常见问题

1. **连接失败**
   - 检查 WebSocket URL 是否正确
   - 确认服务端是否运行
   - 查看防火墙设置

2. **收不到消息**
   - 检查 `type=openclaw` 参数
   - 确认客户端已收到 `welcome` 消息
   - 查看服务端日志

3. **Webhook 失败**
   - 检查 Webhook URL 是否正确
   - 确认网络连接
   - 查看服务端错误日志

### 调试命令

```bash
# 检查端口
netstat -ano | findstr :3123

# 测试 WebSocket
curl -i http://localhost:3123/api/ws

# 测试 Webhook
curl -X POST http://localhost:3123/api/openclaw/webhook \
  -H "Content-Type: application/json" \
  -d '{"nextRole": "test"}'

# 查看日志
tail -f message-hub-client.log
```

## 扩展开发

### 添加新功能

1. **新的任务类型**
   ```javascript
   // 在 openclaw_executor.js 中添加
   this.toolHandlers['new_action'] = this.handleNewAction.bind(this);
   ```

2. **自定义日志**
   ```javascript
   class CustomLogger extends Logger {
       // 重写日志方法
   }
   ```

3. **额外的 WebSocket 事件**
   ```javascript
   this.ws.on('new_event', (data) => {
       // 处理新事件
   });
   ```

### 集成到其他系统

1. **作为服务运行**
   ```bash
   # 使用 pm2
   pm2 start executor.js --name message-hub-client
   ```

2. **Docker 容器**
   ```dockerfile
   FROM node:18
   WORKDIR /app
   COPY package*.json ./
   RUN npm install
   COPY . .
   CMD ["node", "executor.js"]
   ```

## 注意事项

1. **安全性**
   - 不要在日志中记录敏感信息
   - 使用环境变量存储配置
   - 验证 Webhook 请求来源

2. **性能**
   - 合理设置心跳间隔
   - 控制并发任务数量
   - 监控内存使用

3. **可靠性**
   - 实现自动重连机制
   - 处理网络中断
   - 备份重要数据

## 版本历史

- **v1.0.0** - 初始版本，JavaScript 客户端实现
- **v0.1.0** - Python 版本（已弃用）

## 相关链接

- [OpenClaw 文档](https://docs.openclaw.ai)
- [WebSocket 协议](https://tools.ietf.org/html/rfc6455)
- [Node.js ws 库](https://github.com/websockets/ws)
