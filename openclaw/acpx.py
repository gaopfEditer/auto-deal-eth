"""通过 acpx CLI 连接本地 OpenClaw（ACP）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from openclaw._env import REPO_ROOT

__all__ = [
    "acpx_openclaw_exec",
    "acpx_openclaw_exec_interactive",
    "acpx_openclaw_exec_capture",
]


def _resolve_npx() -> str:
    for name in ("npx.cmd", "npx.exe", "npx"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError("未找到 npx，请先安装 Node.js。")


def _build_acpx_argv(
    prompt: str, *, timeout_sec: int, format_mode: str
) -> tuple[list[str], str | None]:
    """返回 (argv, prompt_file)。Windows 下通过 -f 传 UTF-8 文件，避免中文参数乱码。"""
    text = prompt.strip()
    argv: list[str] = [
        _resolve_npx(),
        "acpx@latest",
        "--format",
        format_mode,
        "--approve-all",
        "--timeout",
        str(max(30, timeout_sec)),
        "openclaw",
        "exec",
    ]
    if (os.getenv("ACPX_VERBOSE") or "").strip().lower() in ("1", "true", "yes", "on"):
        argv.insert(2, "--verbose")

    prompt_file: str | None = None
    if sys.platform == "win32" or not text.isascii():
        prompt_file = tempfile.mktemp(prefix="acpx_prompt_", suffix=".txt")
        Path(prompt_file).write_text(text, encoding="utf-8")
        argv.extend(["-f", prompt_file])
    else:
        argv.append(text)
    return argv, prompt_file


def _acpx_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OPENCLAW_HIDE_BANNER", "1")
    env.setdefault("OPENCLAW_SUPPRESS_NOTES", "1")
    return env


def _read_text_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _stderr_indicates_handshake(err: str) -> bool:
    s = err.lower()
    return "invalid handshake" in s or "first request must be connect" in s


def acpx_openclaw_exec_interactive(
    prompt: str, *, timeout_sec: int = 300, retries: int = 3
) -> int:
    """子进程继承 stdout/stderr；网关在正常时这是最稳的方式。"""
    print("【acpx】openclaw exec（交互输出）")
    print(f"  prompt: {prompt[:80]}{'…' if len(prompt) > 80 else ''}")
    print("-" * 50)

    last_rc = 1
    for attempt in range(1, max(1, retries) + 1):
        argv, prompt_file = _build_acpx_argv(
            prompt, timeout_sec=timeout_sec, format_mode="quiet"
        )
        try:
            last_rc = subprocess.run(
                argv,
                cwd=str(REPO_ROOT),
                env=_acpx_env(),
                shell=False,
            ).returncode
            if last_rc == 0:
                return 0
            if attempt < retries:
                time.sleep(2.0 * attempt)
        finally:
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass
    return last_rc


def acpx_openclaw_exec_capture(
    prompt: str,
    *,
    timeout_sec: int = 300,
    format_mode: str = "quiet",
    retries: int = 3,
) -> str:
    """
    通过 cmd 重定向捕获 stdout（避免 capture_output=True）。
    网关繁忙时可能握手失败，会自动重试。
    """
    last_err = ""

    for attempt in range(1, max(1, retries) + 1):
        argv, prompt_file = _build_acpx_argv(
            prompt, timeout_sec=timeout_sec, format_mode=format_mode
        )
        cmdline = subprocess.list2cmdline(argv)
        out_path = tempfile.mktemp(prefix="acpx_out_", suffix=".txt")
        err_path = tempfile.mktemp(prefix="acpx_err_", suffix=".txt")
        try:
            completed = subprocess.run(
                cmdline + f' 1>"{out_path}" 2>"{err_path}"',
                shell=True,
                cwd=str(REPO_ROOT),
                env=_acpx_env(),
            )
            stdout = _read_text_file(out_path).strip()
            stderr = _read_text_file(err_path).strip()
            if completed.returncode == 0:
                return stdout or "(无文本回复)"

            last_err = stderr or stdout or f"exit {completed.returncode}"
            if attempt < retries and _stderr_indicates_handshake(stderr):
                time.sleep(2.0 * attempt)
                continue
            break
        finally:
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass
            for p in (out_path, err_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    detail = [f"acpx 退出码非 0（已重试 {retries} 次）"]
    if last_err:
        detail.append(f"【stderr/日志】\n{last_err}")
    detail.append(
        "若持续出现 invalid handshake：先 `openclaw gateway restart`，"
        "并结束残留的 `openclaw acp`；或设置 ACPX_INTERACTIVE=1 再试。"
    )
    return "下发失败！\n" + "\n\n".join(detail)


def _parse_timeout() -> int:
    try:
        return int(os.getenv("OPENCLAW_AGENT_TIMEOUT", "300").strip() or "300")
    except ValueError:
        return 300


def _parse_retries() -> int:
    try:
        return int(os.getenv("OPENCLAW_ACPX_RETRIES", "3").strip() or "3")
    except ValueError:
        return 3


def _resolve_interactive(interactive: bool | None) -> bool:
    if interactive is not None:
        return interactive
    env_flag = (os.getenv("ACPX_INTERACTIVE") or "").strip().lower()
    if env_flag in ("0", "false", "no", "off"):
        return False
    if env_flag in ("1", "true", "yes", "on"):
        return True
    return sys.platform == "win32"


def acpx_openclaw_exec(prompt: str, *, interactive: bool | None = None) -> str:
    """单次向 OpenClaw 提问：默认 Windows 交互输出，其它平台默认捕获 stdout。"""
    timeout = _parse_timeout()
    retries = _parse_retries()

    if _resolve_interactive(interactive):
        rc = acpx_openclaw_exec_interactive(
            prompt, timeout_sec=timeout, retries=max(1, retries)
        )
        return "" if rc == 0 else f"acpx 退出码: {rc}（可执行 openclaw gateway restart 后重试）"

    return acpx_openclaw_exec_capture(
        prompt, timeout_sec=timeout, retries=max(1, retries)
    )
