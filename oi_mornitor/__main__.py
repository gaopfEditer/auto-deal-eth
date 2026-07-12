"""OI Monitor 入口。"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 支持在 oi_mornitor 目录内执行 python -m oi_mornitor（未 editable 安装时）
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from oi_mornitor.config import SCAN_INTERVAL_SEC, WEB_HOST, WEB_PORT


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="币安永续 OI 动态热钱雷达")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["daemon", "once", "web"],
        default="web",
        help="daemon=终端守护 | once=单次扫描 | web=前端+后端(默认)",
    )
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL_SEC, help="扫描间隔秒")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="开发模式：Vite 热更新(5173) + 后端 API(8765)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="跳过前端自动构建（内部/开发子进程使用）",
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="仅启动后端 API，不打印一键启动横幅（内部使用）",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="强制重新构建前端",
    )
    args = parser.parse_args()
    _setup_logging()

    if args.mode == "web":
        from oi_mornitor.launcher import (
            ensure_frontend_built,
            kill_processes_on_ports,
            run_dev_stack,
            run_production_web,
        )

        if args.dev:
            run_dev_stack()
            return

        if not args.skip_build:
            ensure_frontend_built(force=args.rebuild)

        if args.backend_only:
            kill_processes_on_ports(WEB_PORT)
            from oi_mornitor.server import main as web_main

            web_main()
            return

        run_production_web()
        return

    if args.mode == "once":
        from oi_mornitor.radar import get_hot_tickers

        hot = asyncio.run(get_hot_tickers())
        print(f"单次扫描完成，异动 {len(hot)} 个")
        return

    from oi_mornitor.radar import run_daemon

    print(f"🛰️  OI 雷达守护进程启动，间隔 {args.interval}s")
    asyncio.run(run_daemon(args.interval))


if __name__ == "__main__":
    main()
