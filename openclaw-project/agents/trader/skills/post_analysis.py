#!/usr/bin/env python3
"""
将分析结果通过 POST 发送到指定 Webhook（如 3123 端口或 TradingView 接收端）

用法:
  python post_analysis.py '{"direction":"long","confidence":0.8,...}'
  python post_analysis.py --file output/analysis.json
  echo '{"direction":"long"}' | python post_analysis.py --stdin

环境变量:
  WEBHOOK_URL  默认 http://127.0.0.1:3123/api/tradingview/receive
  WEBHOOK_TOKEN 可选，Bearer token
"""

import argparse
import json
import os
import sys


def load_config():
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "config.json"
    )
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg.get("webhook", {})
    return {}


def post_analysis(payload: dict, url: str | None = None, token: str | None = None) -> bool:
    import urllib.request

    cfg = load_config()
    url = url or os.environ.get("WEBHOOK_URL") or cfg.get("url") or "http://127.0.0.1:3123/api/tradingview/receive"
    token = token or os.environ.get("WEBHOOK_TOKEN") or cfg.get("token")

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OpenClaw-Trader/1.0",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            if 200 <= code < 300:
                print(f"[OK] POST {url} -> {code}", file=sys.stderr)
                return True
            print(f"[WARN] POST {url} -> {code} {body}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(description="POST analysis JSON to webhook")
    ap.add_argument("payload", nargs="?", help="JSON string")
    ap.add_argument("--file", "-f", help="Read payload from file")
    ap.add_argument("--stdin", action="store_true", help="Read payload from stdin")
    ap.add_argument("--url", help="Override webhook URL")
    ap.add_argument("--token", help="Override Bearer token")
    args = ap.parse_args()

    if args.stdin:
        raw = sys.stdin.read()
    elif args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw = f.read()
    elif args.payload:
        raw = args.payload
    else:
        print("Usage: post_analysis.py <json> | --file <path> | --stdin", file=sys.stderr)
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    ok = post_analysis(payload, url=args.url, token=args.token)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
