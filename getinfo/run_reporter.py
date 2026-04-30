#!/usr/bin/env python3
"""
运行脚本上报工具：
- 发送执行日志到 /api/log
- 发送结果回调到 /api/callback
"""
from __future__ import annotations

import os
from typing import Any, Dict

import requests


DEFAULT_REPORT_BASE = "http://127.0.0.1:8000"
DEFAULT_CALLBACK_IDENTIFIER = "auto-deal-eth"


def _base_url() -> str:
    return (os.getenv("GETINFO_REPORT_BASE_URL") or DEFAULT_REPORT_BASE).strip().rstrip("/")


def _post_json(path: str, payload: Dict[str, Any], timeout: int = 8) -> bool:
    url = f"{_base_url()}{path}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 300:
            print(f"[WARN] 上报失败 {path} HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[WARN] 上报异常 {path}: {e}")
        return False


def log_event(script_key: str, message: str, level: str = "INFO") -> bool:
    """
    发送日志事件到 /api/log。
    identifier 规则：auto-deal-eth-<script_key>
    """
    payload = {
        "identifier": f"auto-deal-eth-{script_key}",
        "message": message,
        "level": level,
    }
    return _post_json("/api/log", payload)


def callback_result(script_key: str, result: Dict[str, Any]) -> bool:
    """
    发送结果回调到 /api/callback。
    """
    payload = {
        "identifier": os.getenv("GETINFO_CALLBACK_IDENTIFIER", DEFAULT_CALLBACK_IDENTIFIER),
        "script_key": script_key,
        "result": result,
    }
    return _post_json("/api/callback", payload)

