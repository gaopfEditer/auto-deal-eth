"""news_mornitor — CryptoPulse 入口。"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
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
        asyncio.run(run_scheduler(interval_sec=args.interval))
        return

    # web: 先跑一轮 ingest（mock），再起 API
    async def _boot() -> None:
        from news_mornitor.pipeline.ingest import IngestPipeline
        from news_mornitor.store import FileStore

        store = FileStore()
        if not store.load_posts():
            logging.getLogger("CryptoPulse").info("空库，执行首次 ingest…")
            await IngestPipeline(store=store).run_once()

    try:
        asyncio.run(_boot())
    except Exception as e:
        logging.getLogger("CryptoPulse").warning("首次 ingest 跳过: %s", e)

    import uvicorn

    uvicorn.run(
        "news_mornitor.api.server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
