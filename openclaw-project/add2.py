#!/usr/bin/env python3
"""Auditor 技能：数值加一百。完成时通知 OpenClaw webhook（next=stop），URL 从 config 读取。"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def _get_webhook_url() -> str:
    """从 openclaw-project/config.json 的 openclaw.webhook_url 读取。"""
    root = Path(__file__).resolve().parents[3]  # skills -> auditor -> agents -> openclaw-project
    cfg = root / "config.json"
    if cfg.exists():
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                url = json.load(f).get("openclaw", {}).get("webhook_url")
                if url:
                    return url
        except Exception:
            pass
    return os.environ.get("OPENCLAW_WEBHOOK_URL", "http://localhost:3123/api/openclaw/webhook")


def _notify_webhook(payload: dict):
    try:
        req = urllib.request.Request(
            _get_webhook_url(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as _:
            pass
    except Exception as e:
        print(f"[WARN] webhook 通知失败: {e}", file=sys.stderr)


def add_hundred(x: float) -> float:
    return x + 100


def main():
    ap = argparse.ArgumentParser(description="数值加一百")
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

    result = add_hundred(n)
    out = {"input": n, "result": result, "agent": "auditor"}
    _notify_webhook({"type": "openclaw", "next": "stop", **out})
    if args.json:
        print(json.dumps(out))
    else:
        print(f"{n} + 100 = {result}")


if __name__ == "__main__":
    main()
