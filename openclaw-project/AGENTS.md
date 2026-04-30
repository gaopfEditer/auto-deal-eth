# 流水线 SOP

## 指令触发规则
1. 当用户提到“开始执行视频任务”时，你必须立即启动【视频下载技能】。
2. 任务执行期间，你是一个任务调度员，负责监控 WebSocket 通道 `ws://localhost:3123/api/ws` 的指令。

## 角色流转协议
- **角色 A (operator)**: 现在是测试阶段你需要调用skills中的add.py之后他会完成并且以webhook通知后台，后台再通过ws转发给你。
- **角色 B (auditor)**: 现在是测试阶段你需要调用skills中的add2.py之后他会完成并且以webhook通知后台，后台再通过ws转发给你。
- **终点控制**: 只要脚本返回结果中包含 `[next:stop]` 字符串，必须立即打印“✅ 视频流水线任务已全部完成”并停止所有后续动作。

## WebSocket 行为
- 始终保持与 `ws://localhost:3123/api/ws` 的连接。
- 将收到的 JSON 消息解析为下一个动作指令。

## 下面是各个角色的目录结构，包含其提示词和skills执行脚本
```
openclaw-project/
├── agents/
│   ├── auditor/
│   │   ├── skills/
│   │   │   └── add.py
│   │   ├── config.json
│   │   ├── PROMPTS.md
│   │   └── README.md
│   ├── operator/
│   │   ├── skills/
│   │   │   └── add.py
│   │   ├── config.json
│   │   ├── PROMPTS.md
│   │   └── README.md
│   └── trader/
│       ├── skills/
│       │   ├── gemini_analyze.py
│       │   └── post_analysis.py
│       ├── AGENTS.md
│       ├── config.json
│       ├── IDENTITY.md
│       ├── PROMPTS.md
│       ├── README.md
│       └── SOUL.md
├── shared/
│   ├── __init__.py
│   ├── agent_monitor.py
│   ├── logger.py
│   ├── openclaw_config.py
│   └── README.md
├── skills/
│   └── webhook_push.py
├── agents.json5
├── AGENTS.md
├── cleaner.ps1
├── cleaner.sh
├── config.json
├── README.md
└── requirements.txt
```


