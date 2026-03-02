#!/usr/bin/env python3
"""Operator 技能：数值加一。用于测试角色功能。完成时通知 webhook，next=auditor。"""
import argparse
import json
import sys
import urllib.request


WEBHOOK_URL = "http://localhost:3123/api/openclaw/webhook"


def _notify_webhook(payload: dict):
    try:
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as _:
            pass
    except Exception as e:
        print(f"[WARN] webhook 通知失败: {e}", file=sys.stderr)


def add_one(x: float) -> float:
    return x + 1


def main():
    ap = argparse.ArgumentParser(description="数值加一")
    ap.add_argument("n", type=float, nargs="?", help="输入数值")
    ap.add_argument("--json", action="store_true", help="JSON 输入/输出")
    args = ap.parse_args()

    if args.json:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        n = float(data.get("n", data.get("value", 0)))
    else:
        n = args.n
        if n is None:
            n = float(input("输入数值: ").strip() or 0)

    result = add_one(n)
    out = {"input": n, "result": result, "agent": "operator"}
    _notify_webhook({"type": "openclaw", "next": "role:auditor", **out})
    if args.json:
        print(json.dumps(out))
    else:
        print(f"{n} + 1 = {result}")


if __name__ == "__main__":
    main()
