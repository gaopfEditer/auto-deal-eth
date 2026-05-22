"""
通过 OpenClaw 单次问答（逻辑在 openclaw 包）。

用法：
  python test/test_win_qa.py
  python test/test_win_qa.py 你支持图片分析吗
  python -m openclaw.cli 你的问题

环境变量见 openclaw 包文档（OPENCLAW_AGENT_TIMEOUT、ACPX_INTERACTIVE 等）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from openclaw import ask


def main() -> None:
    question = "你支持图片分析吗"
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])

    try:
        answer = ask(question)
    except Exception as exc:
        answer = f"配置或启动错误: {exc}"

    if answer:
        print("\n" + "=" * 20 + " OpenClaw / acpx 回复 " + "=" * 20)
        try:
            print(answer)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((answer + "\n").encode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
