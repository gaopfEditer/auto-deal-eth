#!/usr/bin/env python3
"""
调用本机 8000 内容服务 POST /api/publish/signal 的独立 Demo。

不依赖项目其它模块，拷贝本文件到任意机器即可测试（需能访问 8000 服务）。

用法:
  python publish_signal_8000_demo.py
  python publish_signal_8000_demo.py --public          # publish=true，发布到广场
  python publish_signal_8000_demo.py --url http://127.0.0.1:8000/api/publish/signal
  python publish_signal_8000_demo.py --signal-file ./my_signal.txt
  python publish_signal_8000_demo.py --strategy strategy_left_ambush --style style_tianya_classic

环境变量（可选）:
  SIGNAL_PUBLISH_URL
  SIGNAL_PUBLISH_STRATEGY_ID
  SIGNAL_PUBLISH_STYLE_IDS   逗号分隔
  SIGNAL_PUBLISH_COMPOSE_MODE
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# 与 tv_ws 链路一致的示例 signal 纯文本
SAMPLE_SIGNAL = """📊 BTCUSD 倒锤子

触发信号

💰 交易对: BTCUSD
📈 类型: 倒锤子
⏰ 周期: 1h
⏰ 时间: 2026-05-18 23:00:00
💵 价格: 76348.01
📈 最高: 76425.95
📉 最低: 75992.0

👤 来源: TradingView"""


def build_payload(
    signal: str,
    *,
    publish: bool,
    strategy_id: str,
    style_ids: list[str],
    compose_mode: str,
) -> dict[str, Any]:
    return {
        "signal": signal.strip(),
        "style_ids": style_ids,
        "strategy_id": strategy_id,
        "compose_mode": compose_mode,
        "publish": publish,
    }


def post_publish_signal(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_sec: int = 60,
) -> tuple[int, str, dict[str, Any] | None]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
        text = e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接 {url}: {e}") from e

    parsed: dict[str, Any] | None = None
    try:
        j = json.loads(text)
        if isinstance(j, dict):
            parsed = j
    except json.JSONDecodeError:
        pass
    return status, text, parsed


def format_polished_preview(body: dict[str, Any]) -> str:
    """简易打印润色结果（与 promat_publish 终端展示类似）。"""
    if not body.get("ok"):
        return json.dumps(body, ensure_ascii=False, indent=2)
    lines = [f"ok={body.get('ok')}"]
    if body.get("model"):
        lines.append(f"model={body.get('model')}")
    polished = body.get("polished")
    if isinstance(polished, dict):
        star = polished.get("star")
        if star is not None:
            lines.append(f"⭐ 信号强度: {star}/5  |  isSign={polished.get('isSign')}")
            lines.append("")
        content = polished.get("content")
        if content:
            s = str(content).strip()
            if "\\n" in s and "\n" not in s:
                s = s.replace("\\n", "\n")
            lines.append(s)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo: POST /api/publish/signal")
    parser.add_argument(
        "--url",
        default=os.getenv(
            "SIGNAL_PUBLISH_URL", "http://127.0.0.1:8000/api/publish/signal"
        ),
        help="派发接口地址",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="publish=true 发布到广场；默认 publish=false 仅润色",
    )
    parser.add_argument(
        "--signal-file",
        metavar="PATH",
        help="从文件读取 signal 正文；默认使用内置 BTCUSD 样本",
    )
    parser.add_argument(
        "--strategy",
        default=os.getenv("SIGNAL_PUBLISH_STRATEGY_ID", "strategy_left_ambush"),
    )
    parser.add_argument(
        "--style",
        default=os.getenv("SIGNAL_PUBLISH_STYLE_IDS", "style_tianya_classic"),
        help="单个 style id，或用逗号传多个",
    )
    parser.add_argument(
        "--compose-mode",
        default=os.getenv("SIGNAL_PUBLISH_COMPOSE_MODE", "manual"),
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要发送的 JSON，不真正 POST",
    )
    args = parser.parse_args()

    if args.signal_file:
        signal = open(args.signal_file, encoding="utf-8").read()
    else:
        signal = SAMPLE_SIGNAL

    style_ids = [s.strip() for s in args.style.split(",") if s.strip()]
    payload = build_payload(
        signal,
        publish=args.public,
        strategy_id=args.strategy.strip(),
        style_ids=style_ids,
        compose_mode=args.compose_mode.strip() or "manual",
    )

    url = args.url.strip()
    print(f"URL: {url}")
    print(f"publish={payload['publish']}  strategy={payload['strategy_id']!r}")
    print(f"styles={payload['style_ids']}  signal_len={len(payload['signal'])}")
    print("-" * 56)
    print(payload["signal"][:800] + ("…" if len(payload["signal"]) > 800 else ""))
    print("-" * 56)

    if args.dry_run:
        print("\n[dry-run] 请求体:\n")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("\nPOST …")
    try:
        status, raw, body = post_publish_signal(url, payload, timeout_sec=args.timeout)
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    print(f"HTTP {status}")
    if body is not None:
        print("\n--- 响应（润色预览）---\n")
        print(format_polished_preview(body))
    else:
        print(raw[:3000])

    if status < 200 or status >= 300:
        return 1
    if isinstance(body, dict) and body.get("ok") is False:
        return 1
    print("\n[OK] 请求成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
