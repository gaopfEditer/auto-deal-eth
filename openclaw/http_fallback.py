"""acpx 不可用时的 HTTP webhook 退路（复用 test/openclawApi.py）。"""
from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType, SimpleNamespace

from openclaw._env import REPO_ROOT

__all__ = ["http_ask", "openclaw_http_fallback"]

_MODULE_NAME = "_openclaw_api_client"


def _load_openclaw_api() -> ModuleType:
    cached = sys.modules.get(_MODULE_NAME)
    if cached is not None:
        return cached
    path = REPO_ROOT / "test" / "openclawApi.py"
    if not path.is_file():
        raise ImportError(f"未找到 {path}")
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def openclaw_http_fallback(prompt: str) -> str:
    oc = _load_openclaw_api()
    ns = SimpleNamespace(
        webhook_url=None,
        webhook_token=None,
        webhook_path="webhook",
        session_key=(os.getenv("OPENCLAW_SESSION_HISTORY_KEY") or "").strip() or None,
        timeout=120.0,
        poll_interval=float(os.getenv("OPENCLAW_HISTORY_POLL_INTERVAL", "3") or "3"),
        no_poll=False,
    )
    os.environ.setdefault("OPENCLAW_QUIET", "1")
    out = oc._execute_single_task(prompt, ns)
    text = (out.get("assistant_text") or "").strip()
    if text:
        return text
    if out.get("wait_error"):
        return f"HTTP 等待超时: {out['wait_error']}"
    return f"HTTP 未拿到回复: {out}"


def http_ask(prompt: str) -> str:
    return openclaw_http_fallback(prompt)
