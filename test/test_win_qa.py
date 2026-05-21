"""
通过 acpx 与本地 OpenClaw（ACP）单次问答。

正确用法（与官方 CLI 一致）：
  npx acpx@latest --format quiet --approve-all openclaw exec "你的问题"
  ※ 全局选项（--format / --timeout）必须在 openclaw 之前
  ※ 默认 `acpx exec` 走 codex，必须用 `openclaw exec`
  ※ Windows 下不要用 capture_output=True，会导致 ACP 握手失败

用法：
  python test/test_win_qa.py
  python test/test_win_qa.py 你支持图片分析吗
  set ACPX_INTERACTIVE=1          # 直接打印到终端（最稳，不捕获 stdout）
  set OPENCLAW_HTTP_FALLBACK=1    # acpx 失败时改用 HTTP webhook（见 openclawApi.py）

环境变量（可选）：
  OPENCLAW_AGENT_TIMEOUT   acpx --timeout（秒），默认 300
  OPENCLAW_ACPX_RETRIES    捕获模式重试次数，默认 3
  ACPX_VERBOSE=1
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    load_dotenv()
except ImportError:
    pass


def _resolve_npx() -> str:
    for name in ("npx.cmd", "npx.exe", "npx"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError("未找到 npx，请先安装 Node.js。")


def _build_acpx_argv(
    prompt: str, *, timeout_sec: int, format_mode: str
) -> tuple[list[str], str | None]:
    """
    返回 (argv, prompt_file)。Windows 下通过 -f 传 UTF-8 文件，避免中文参数乱码。
    """
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
                cwd=str(_REPO_ROOT),
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
                cwd=str(_REPO_ROOT),
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


def openclaw_http_fallback(prompt: str) -> str:
    """acpx 不可用时的 HTTP webhook 退路（与 test/openclawApi.py 相同链路）。"""
    import openclawApi as oc

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


def acpx_openclaw_exec(prompt: str, *, interactive: bool | None = None) -> str:
    try:
        timeout = int(os.getenv("OPENCLAW_AGENT_TIMEOUT", "300").strip() or "300")
    except ValueError:
        timeout = 300
    try:
        retries = int(os.getenv("OPENCLAW_ACPX_RETRIES", "3").strip() or "3")
    except ValueError:
        retries = 3

    if interactive is None:
        env_flag = (os.getenv("ACPX_INTERACTIVE") or "").strip().lower()
        if env_flag in ("0", "false", "no", "off"):
            interactive = False
        elif env_flag in ("1", "true", "yes", "on"):
            interactive = True
        else:
            # Windows 上管道捕获 stdout 易触发 ACP 握手错误，默认交互输出
            interactive = sys.platform == "win32"

    if interactive:
        rc = acpx_openclaw_exec_interactive(
            prompt, timeout_sec=timeout, retries=max(1, retries)
        )
        return "" if rc == 0 else f"acpx 退出码: {rc}（可执行 openclaw gateway restart 后重试）"

    result = acpx_openclaw_exec_capture(
        prompt, timeout_sec=timeout, retries=max(1, retries)
    )
    if result.startswith("下发失败") and (
        os.getenv("OPENCLAW_HTTP_FALLBACK") or ""
    ).strip().lower() in ("1", "true", "yes", "on"):
        print("【回退】改用 HTTP webhook …", flush=True)
        return openclaw_http_fallback(prompt)
    return result


if __name__ == "__main__":
    question = "你支持图片分析吗"
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])

    try:
        answer = acpx_openclaw_exec(question)
    except Exception as exc:
        answer = f"配置或启动错误: {exc}"

    if answer:
        print("\n" + "=" * 20 + " OpenClaw / acpx 回复 " + "=" * 20)
        try:
            print(answer)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((answer + "\n").encode("utf-8", errors="replace"))
