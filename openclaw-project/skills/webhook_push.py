#!/usr/bin/env python3
"""
通用 Webhook 推送技能

将任意 JSON 或文本 POST 到指定 URL。可供 trader、operator、auditor 等复用。

用法:
  python webhook_push.py --url https://example.com/webhook --body '{"msg":"hello"}'
  python webhook_push.py --url https://example.com/webhook --file data.json
"""

import argparse
import json
import os
import sys


def push(url: str, body: str | dict, token: str | None = None) -> bool:
    import urllib.request

    if isinstance(body, dict):
        body = json.dumps(body, ensure_ascii=False)
    data = body.encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OpenClaw-Webhook/1.0",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            if 200 <= code < 300:
                print(f"[OK] POST {url} -> {code}", file=sys.stderr)
                return True
            print(f"[WARN] POST {url} -> {code}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(description="POST to webhook")
    ap.add_argument("--url", "-u", required=True, help="Webhook URL")
    ap.add_argument("--body", "-b", help="JSON body string")
    ap.add_argument("--file", "-f", help="Read body from file")
    ap.add_argument("--token", "-t", default=os.environ.get("WEBHOOK_TOKEN"), help="Bearer token")
    args = ap.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            body = f.read()
    elif args.body:
        body = args.body
    else:
        print("Usage: webhook_push.py --url <url> (--body <json> | --file <path>)", file=sys.stderr)
        sys.exit(1)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = body

    ok = push(args.url, payload, token=args.token)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
