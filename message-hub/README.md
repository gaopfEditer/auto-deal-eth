# Message Hub 客户端技能

连接到外部消息中心服务的 JavaScript 客户端，专为 OpenClaw 设计。

## 功能特性

- ✅ **WebSocket 连接** - 连接到外部消息中心
- ✅ **Webhook 支持** - 发送任务结果到回调地址
- ✅ **日志记录** - 详细的连接和消息日志
- ✅ **心跳机制** - 保持连接活跃
- ✅ **多任务处理** - 支持并发任务处理
- ✅ **OpenClaw 集成** - 专为 OpenClaw 环境优化

## 快速开始

### 1. 安装依赖

```bash
cd C:\Users\eason\openclaw\skills\message-hub
npm install
```

### 2. 配置环境变量

```bash
# 执行器标识
export EXECUTOR_ID=my_executor

# WebSocket 连接地址
export WS_URL=ws://localhost:3123/api/ws?type=openclaw

# Webhook 回调地址
export WEBHOOK_URL=http://localhost:3123/api/openclaw/webhook

# 日志文件路径（可选）
export LOG_FILE=./message-hub-client.log
```

### 3. 启动客户端

```bash
# 启动通用执行器
npm start

# 或使用启动脚本
node start.js --executor

# 启动 OpenClaw 专用执行器
node start.js --openclaw

# 运行测试
node start.js --test
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `executor.js` | 通用执行器客户端 |
| `openclaw_executor.js` | OpenClaw 专用执行器 |
| `test.js` | 测试脚本 |
| `start.js` | 启动脚本 |
| `package.json` | Node.js 依赖配置 |
| `config.json` | 服务端配置（参考） |

## 使用示例

### 连接到外部消息中心

```javascript
// 使用默认配置
const executor = new Executor();
executor.run();

// 自定义配置
const executor = new Executor({
    executorId: 'my_custom_executor',
    wsUrl: 'ws://example.com/api/ws?type=openclaw',
    webhookUrl: 'http://example.com/api/openclaw/webhook'
});
```

### 处理 OpenClaw 任务

当收到 `openclaw_next_role` 消息时，执行器会自动处理：

1. 解析任务类型和参数
2. 调用相应的 OpenClaw 工具处理器
3. 发送结果到 Webhook
4. 更新执行器状态

### 守护进程模式

保持 WebSocket 连接在后台运行，自动重启崩溃的进程：

#### Windows:
```bash
# 启动守护进程
start-daemon.bat start

# 停止守护进程
start-daemon.bat stop

# 重启守护进程
start-daemon.bat restart

# 查看状态
start-daemon.bat status
```

#### 所有平台:
```bash
# 启动守护进程
node auto-restart.js start

# 重启子进程
node auto-restart.js restart

# 停止守护进程
node auto-restart.js stop
```

#### 使用 pm2（高级）:
```bash
# 首次使用需要安装 pm2
npm install pm2 --save-dev

# 启动守护进程
node daemon.js start

# 查看状态
node daemon.js status

# 停止守护进程
node daemon.js stop
```

### 日志查看

所有连接和消息都会记录到日志文件：

```bash
# 查看实时日志
tail -f message-hub-client.log

# 查看守护进程日志
tail -f auto-restart.log

# 查看 OpenClaw 执行器日志
tail -f openclaw-executor.log

# 查看测试日志
tail -f test.log
```

## 协议说明

### WebSocket 消息格式

**客户端发送：**
```json
{
  "type": "heartbeat",
  "executor_id": "executor_1",
  "client_id": "client_123",
  "timestamp": "2026-03-16T10:00:00Z"
}
```

**服务端发送：**
```json
{
  "type": "welcome",
  "clientId": "client_123"
}
```

```json
{
  "type": "openclaw_next_role",
  "nextRole": "TestRole_1",
  "payload": {
    "action": "web_search",
    "query": "OpenClaw documentation"
  }
}
```

### Webhook 结果格式

```json
{
  "status": "completed",
  "nextRole": "TestRole_1",
  "executor": "openclaw_executor",
  "result": {
    "action": "web_search",
    "query": "OpenClaw documentation",
    "results": "Search results here..."
  },
  "timestamp": "2026-03-16T10:00:00Z"
}
```

## 故障排除

### 连接失败

1. **检查 WebSocket URL**
   ```bash
   curl -i http://localhost:3123/
   ```

2. **检查端口是否开放**
   ```bash
   netstat -ano | findstr :3123
   ```

3. **查看详细日志**
   ```bash
   node executor.js 2>&1 | tee debug.log
   ```

### Webhook 发送失败

1. **检查 Webhook URL**
   ```bash
   curl -X POST http://localhost:3123/api/openclaw/webhook \
     -H "Content-Type: application/json" \
     -d '{"nextRole": "test"}'
   ```

2. **检查网络连接**
   ```bash
   ping localhost
   ```

### 任务处理错误

1. **查看执行器状态**
   ```bash
   # 检查是否忙碌
   ps aux | grep node
   ```

2. **检查日志文件**
   ```bash
   cat message-hub-client.log | grep ERROR
   ```

## 扩展开发

### 添加新的任务处理器

在 `openclaw_executor.js` 中添加新的处理器：

```javascript
class OpenClawExecutor {
    constructor() {
        this.toolHandlers = {
            // ... 现有处理器
            'new_action': this.handleNewAction.bind(this)
        };
    }

    async handleNewAction(params) {
        this.logger.info(`执行新动作: ${params.action}`);
        // 实现处理逻辑
        return {
            action: 'new_action',
            result: '处理完成'
        };
    }
}
```

### 自定义日志格式

修改 `Logger` 类：

```javascript
class CustomLogger extends Logger {
    log(level, message, data = null) {
        // 自定义日志格式
        const timestamp = new Date().toLocaleString();
        const logEntry = `[${timestamp}] [${level.toUpperCase()}] [${EXECUTOR_ID}] ${message}`;
        
        // ... 其他逻辑
    }
}
```

## 许可证

MIT
