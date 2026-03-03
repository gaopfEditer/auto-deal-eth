#!/usr/bin/env python3
"""获取 OpenClaw 公共配置（如 webhook_url）。"""
import json
import os
from pathlib import Path


def get_openclaw_webhook_url() -> str:
    """从 config.json 的 openclaw.webhook_url 读取，供各 agent 统一使用。"""
    # shared 在 openclaw-project/shared/，根目录为 parents[1]
    root = Path(__file__).resolve().parents[1]
    cfg_path = root / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                url = json.load(f).get("openclaw", {}).get("webhook_url")
                if url:
                    return url
        except Exception:
            pass
    return os.environ.get("OPENCLAW_WEBHOOK_URL", "http://localhost:3123/api/openclaw/webhook")
