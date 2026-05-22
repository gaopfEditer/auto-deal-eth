"""OpenClaw 统一问答入口（acpx 优先，可选 HTTP 回退）。"""
from __future__ import annotations

import os

from openclaw.acpx import acpx_openclaw_exec
from openclaw.http_fallback import openclaw_http_fallback

__all__ = ["ask"]


def ask(prompt: str, *, interactive: bool | None = None, http_fallback: bool | None = None) -> str:
    """
    向本地 OpenClaw 提问。

    :param interactive: None 时按 ACPX_INTERACTIVE / 平台默认
    :param http_fallback: None 时读 OPENCLAW_HTTP_FALLBACK；acpx 失败且为 True 时走 HTTP
    """
    result = acpx_openclaw_exec(prompt, interactive=interactive)

    use_http = http_fallback
    if use_http is None:
        use_http = (os.getenv("OPENCLAW_HTTP_FALLBACK") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    if use_http and (
        result.startswith("下发失败") or result.startswith("acpx 退出码")
    ):
        print("【回退】改用 HTTP webhook …", flush=True)
        return openclaw_http_fallback(prompt)
    return result
