"""
OpenClaw 客户端：acpx（ACP）与 HTTP webhook。

示例：
  from openclaw import ask
  print(ask("你支持图片分析吗"))

CLI：
  python -m openclaw.cli 你的问题
"""
from __future__ import annotations

from openclaw._env import REPO_ROOT, load_env
from openclaw.acpx import (
    acpx_openclaw_exec,
    acpx_openclaw_exec_capture,
    acpx_openclaw_exec_interactive,
)
from openclaw.client import ask
from openclaw.http_fallback import http_ask, openclaw_http_fallback

load_env()

__all__ = [
    "REPO_ROOT",
    "ask",
    "acpx_openclaw_exec",
    "acpx_openclaw_exec_interactive",
    "acpx_openclaw_exec_capture",
    "openclaw_http_fallback",
    "http_ask",
]
