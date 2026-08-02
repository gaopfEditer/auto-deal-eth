"""news_mornitor — CryptoPulse 入口。"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from news_mornitor.config import FETCH_INTERVAL_SEC, WEB_HOST, WEB_PORT


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _pids_listening(port: int) -> set[int]:
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return set()
    return {int(x) for x in out.split() if x.strip().isdigit()}


def free_listen_port(port: int, *, wait_sec: float = 1.5) -> None:
    """启动前若端口已被占用，先 SIGTERM / SIGKILL 释放（便于重复 python run.py）。"""
    log = logging.getLogger("CryptoPulse")
    me = os.getpid()
    pids = {p for p in _pids_listening(port) if p != me}
    if not pids:
        return
    log.info("端口 %s 已被占用 %s，先结束旧进程…", port, sorted(pids))
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as e:
            log.warning("无法结束 PID %s: %s", pid, e)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        left = {p for p in _pids_listening(port) if p != me}
        if not left:
            log.info("端口 %s 已释放", port)
            return
        time.sleep(0.15)
    left = {p for p in _pids_listening(port) if p != me}
    for pid in left:
        try:
            log.warning("PID %s 未退出，SIGKILL…", pid)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as e:
            log.warning("SIGKILL PID %s 失败: %s", pid, e)
    time.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoPulse — 交易所广场热讯聚合")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["web", "once", "daemon"],
        default="web",
        help="web=API+前端 | once=单次抓取 | daemon=定时抓取",
    )
    parser.add_argument("--host", default=WEB_HOST)
    parser.add_argument("--port", type=int, default=WEB_PORT)
    parser.add_argument("--interval", type=int, default=FETCH_INTERVAL_SEC)
    parser.add_argument(
        "--no-kill-port",
        action="store_true",
        help="不自动结束占用端口的旧进程",
    )
    args = parser.parse_args()
    _setup_logging()

    if args.mode == "once":
        from news_mornitor.pipeline.ingest import IngestPipeline

        result = asyncio.run(IngestPipeline().run_once())
        print(result)
        return

    if args.mode == "daemon":
        from news_mornitor.scheduler import run_scheduler

        print(f"CryptoPulse daemon interval={args.interval}s")
        # daemon：先抓一轮再按间隔睡
        async def _daemon() -> None:
            from news_mornitor.pipeline.fetch_control import is_fetch_enabled
            from news_mornitor.pipeline.ingest_gate import run_ingest_gated

            if is_fetch_enabled():
                await run_ingest_gated(force=True, interval_sec=args.interval)
            await run_scheduler(interval_sec=args.interval)

        asyncio.run(_daemon())
        return

    if not args.no_kill_port:
        free_listen_port(args.port)

    import threading

    import uvicorn

    # 先起 API/前端（立刻可读历史 JSON）；抓取全部丢后台，不挡访问
    def _bg_fetch() -> None:
        import asyncio

        from news_mornitor.pipeline.fetch_control import is_fetch_enabled
        from news_mornitor.pipeline.ingest_gate import run_ingest_gated
        from news_mornitor.scheduler import run_scheduler
        from news_mornitor.store import FileStore

        log = logging.getLogger("CryptoPulse")
        try:
            store = FileStore()
            n = len(store.load_posts())
            if not is_fetch_enabled():
                log.info(
                    "定时抓取已停止（历史 %s 条可访问）；可在前端点「开始获取」或「立即获取」",
                    n,
                )
            else:
                log.info("后台启动 ingest（历史 %s 条已可访问；间隔 %ss）…", n, args.interval)
                result = asyncio.run(
                    run_ingest_gated(
                        force=True, interval_sec=args.interval, limit_per_source=40
                    )
                )
                log.info(
                    "启动 ingest 完成: skipped=%s fetched=%s",
                    result.get("skipped"),
                    result.get("fetched"),
                )
        except Exception as e:
            log.warning("启动 ingest 失败（前端仍可用历史数据）: %s", e)

        try:
            asyncio.run(run_scheduler(interval_sec=args.interval))
        except Exception as e:
            log.warning("后台调度退出: %s", e)

    t = threading.Thread(target=_bg_fetch, name="cryptopulse-fetcher", daemon=True)
    t.start()
    logging.getLogger("CryptoPulse").info(
        "Web 已就绪 http://%s:%s （历史数据可立即访问；后台每 %ss 抓一轮）",
        args.host,
        args.port,
        args.interval,
    )

    uvicorn.run(
        "news_mornitor.api.server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
