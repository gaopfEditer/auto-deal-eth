# Message Hub 守护进程配置指南

## 方案选择

根据您的需求，这里有几种保持 message-hub 连接在后台运行的方法：

### 方案1：使用 auto-restart.js（推荐）
最简单的解决方案，自动重启崩溃的进程。

**启动：**
```bash
cd C:\Users\eason\openclaw\skills\message-hub
npm run daemon
```

**停止：**
```bash
npm run daemon:stop
```

### 方案2：使用 Windows 批处理文件
适合 Windows 用户，提供简单的命令行界面。

**启动：**
```bash
start-daemon.bat start
```

**查看状态：**
```bash
start-daemon.bat status
```

### 方案3：使用 pm2（生产环境）
功能最强大，提供进程管理、日志轮转等功能。

**首次使用：**
```bash
npm install pm2 --save-dev
npm run daemon:pm2
```

**查看状态：**
```bash
npm run daemon:pm2:status
```

### 方案4：集成到 OpenClaw cron
使用 OpenClaw 内置的 cron 功能定期检查。

## 配置 OpenClaw Cron 任务

您可以将 message-hub 监控添加到 OpenClaw 的 cron 配置中：

### 1. 创建 cron 任务

```bash
openclaw cron add --name "message-hub-monitor" --schedule "*/5 * * * *" --session-target isolated --payload '{"kind":"agentTurn","message":"检查并确保 message-hub 在运行。运行命令: node C:\\\\Users\\\\eason\\\\openclaw\\\\skills\\\\message-hub\\\\monitor.js"}' --deliver '{"mode":"announce"}'
```

### 2. 或手动编辑 openclaw.json

在您的 `C:\Users\eason\.openclaw\openclaw.json` 文件中添加：

```json
{
  "cron": {
    "jobs": [
      {
        "name": "message-hub-monitor",
        "schedule": {
          "kind": "every",
          "everyMs": 300000  // 每5分钟
        },
        "sessionTarget": "isolated",
        "payload": {
          "kind": "agentTurn",
          "message": "检查并确保 message-hub 在运行。运行命令: node C:\\\\Users\\\\eason\\\\openclaw\\\\skills\\\\message-hub\\\\monitor.js"
        },
        "delivery": {
          "mode": "announce"
        },
        "enabled": true
      }
    ]
  }
}
```

### 3. 使用系统服务（Windows）

创建 Windows 服务来运行 message-hub：

```bash
# 使用 nssm (Non-Sucking Service Manager)
nssm install MessageHub "C:\Program Files\nodejs\node.exe" "C:\Users\eason\openclaw\skills\message-hub\executor.js"
nssm set MessageHub AppDirectory "C:\Users\eason\openclaw\skills\message-hub"
nssm set MessageHub AppEnvironmentExtra "EXECUTOR_ID=message_hub_service"
nssm start MessageHub
```

## 最佳实践

1. **开发环境** - 使用 `auto-restart.js` 或批处理文件
2. **测试环境** - 使用 pm2，便于管理和监控
3. **生产环境** - 使用 Windows 服务或 pm2 作为服务运行
4. **集成监控** - 使用 OpenClaw cron 进行健康检查

## 故障排除

### 查看日志
```bash
# 执行器日志
tail -f message-hub-client.log

# 守护进程日志
tail -f auto-restart.log

# 监控日志
tail -f monitor.log
```

### 检查进程状态
```bash
# Windows
tasklist /FI "IMAGENAME eq node.exe"

# 查看特定进程
tasklist /FI "WINDOWTITLE eq Message Hub Daemon"
```

### 手动测试连接
```bash
node test_3123.js
```

## 自动恢复机制

所有方案都包含自动恢复机制：

1. **进程崩溃检测** - 定期检查进程状态
2. **自动重启** - 进程退出时自动重新启动
3. **重试限制** - 防止无限重启循环
4. **延迟重启** - 避免立即重启导致的资源竞争

选择最适合您需求的方案即可确保 message-hub 连接始终保持在后台运行。