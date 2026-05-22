"""python -m openclaw.cli [问题...]"""
from __future__ import annotations

import sys

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
        print("\n" + "=" * 20 + " OpenClaw 回复 " + "=" * 20)
        try:
            print(answer)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((answer + "\n").encode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
