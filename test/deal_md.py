#!/usr/bin/env python3
"""
将 API 返回的问答字符串（含字面 \\n）转为正常换行、有段落的 Markdown。

用法:
  python test/deal_md.py                    # 从 stdin 读，输出到 stdout
  python test/deal_md.py input.txt         # 从文件读，输出到 stdout
  python test/deal_md.py input.txt -o out.md
  python test/deal_md.py -o output.md      # stdin -> output.md
"""
import argparse
import codecs
import sys


def unescape_api_text(raw: str) -> str:
    """把 API 返回里的字面 \\n、\\t 等转成真实换行、制表符。"""
    if not raw:
        return raw
    # 先处理字面反斜杠+n/t，避免 decode('unicode_escape') 误伤其他反斜杠（如 Markdown 的 \*）
    out = raw.replace("\\n", "\n").replace("\\t", "\t")
    # 若仍有其他常见转义，可再替换
    out = out.replace("\\r", "\r")
    return out


def main():
    ap = argparse.ArgumentParser(description="API 返回字符串转成正常段落 Markdown")
    ap.add_argument("input", nargs="?", help="输入文件，不传则从 stdin 读")
    ap.add_argument("-o", "--output", help="输出文件，不传则 stdout")
    args = ap.parse_args()

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    formatted = unescape_api_text(raw)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(formatted)
        print(f"[OK] 已写入 {args.output}", file=sys.stderr)
    else:
        print(formatted, end="")


if __name__ == "__main__":
    main()
