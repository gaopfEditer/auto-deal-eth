# openclaw-project 目录结构

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

生成时间：由 tree 或脚本生成。
