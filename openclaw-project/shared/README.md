# shared 共享模块

供 auditor、operator、trader 共用的工具。

## AgentLogger（双层日志）

- **角色专有**: `logs/{agent_id}/{agent_id}.log`，按天滚动，保留 7 天
- **全局审计**: `logs/audit.log`，仅记录任务流转与结果
- **关键节点 notify=True** → Webhook 上报
- **日志脱敏**：API Key、Token 等自动替换

```python
from shared.logger import AgentLogger
log = AgentLogger("trader")
log.info("分析开始", audit=True, notify=True, stage="gemini")
log.api_response("gemini", raw_json)  # 记录 API 原始响应（脱敏）
log.report_progress("gemini", {"status": "done"})
log.error("失败", stage="error")  # 自动 audit + notify
```

## AgentMonitor

兼容层，内部委托给 AgentLogger。
