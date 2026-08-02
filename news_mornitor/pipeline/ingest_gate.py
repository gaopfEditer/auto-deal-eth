"""全进程抓取限流：默认间隔内只允许一轮（含 boot / 调度 / API）。"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from news_mornitor.config import DATA_DIR, FETCH_INTERVAL_SEC

logger = logging.getLogger("CryptoPulse.IngestGate")

_LOCK = threading.Lock()
_STATE_FILE = DATA_DIR / "last_ingest.json"
_running = False


def _read_last() -> float:
    try:
        if not _STATE_FILE.exists():
            return 0.0
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return float(data.get("ts") or 0)
    except Exception:
        return 0.0


def _write_last(ts: float) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps({"ts": ts, "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))}, ensure_ascii=False),
        encoding="utf-8",
    )


def seconds_until_next(*, interval_sec: int | None = None) -> float:
    interval = int(interval_sec if interval_sec is not None else FETCH_INTERVAL_SEC)
    last = _read_last()
    if last <= 0:
        return 0.0
    remain = interval - (time.time() - last)
    return max(0.0, remain)


def mark_ingest_done() -> None:
    with _LOCK:
        _write_last(time.time())


async def run_ingest_gated(
    *,
    force: bool = False,
    interval_sec: int | None = None,
    limit_per_source: int = 40,
) -> dict[str, Any]:
    """
    带间隔限流的 ingest。
    force=True 时忽略间隔（启动首轮 / 用户点「立即获取」）。
    """
    global _running
    from news_mornitor.pipeline.ingest import IngestPipeline

    interval = int(interval_sec if interval_sec is not None else FETCH_INTERVAL_SEC)
    with _LOCK:
        if _running:
            return {"ok": False, "skipped": True, "reason": "already_running"}
        if not force:
            remain = seconds_until_next(interval_sec=interval)
            if remain > 1:
                logger.info(
                    "距上次抓取不足 %ss，跳过（还需 %.0fs）",
                    interval,
                    remain,
                )
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "rate_limited",
                    "interval_sec": interval,
                    "retry_after_sec": int(remain),
                }
        _running = True

    try:
        result = await IngestPipeline().run_once(limit_per_source=limit_per_source)
        mark_ingest_done()
        return {"ok": True, "skipped": False, **result}
    finally:
        with _LOCK:
            _running = False
