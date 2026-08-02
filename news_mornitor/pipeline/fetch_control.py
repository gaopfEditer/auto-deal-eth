"""抓取开关：停止 / 开始定时；立即获取单独触发。"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from news_mornitor.config import DATA_DIR, FETCH_INTERVAL_SEC
from news_mornitor.pipeline.ingest_gate import (
    run_ingest_gated,
    seconds_until_next,
)

logger = logging.getLogger("CryptoPulse.FetchControl")

_LOCK = threading.Lock()
_STATE_FILE = DATA_DIR / "fetch_control.json"
_DEFAULT = {"enabled": True, "updated_at": 0.0}


def _load() -> dict[str, Any]:
    try:
        if not _STATE_FILE.exists():
            return dict(_DEFAULT)
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULT)
        return {
            "enabled": bool(data.get("enabled", True)),
            "updated_at": float(data.get("updated_at") or 0),
        }
    except Exception:
        return dict(_DEFAULT)


def _save(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_fetch_enabled() -> bool:
    with _LOCK:
        return bool(_load().get("enabled", True))


def set_fetch_enabled(enabled: bool) -> dict[str, Any]:
    with _LOCK:
        state = {"enabled": bool(enabled), "updated_at": time.time()}
        _save(state)
    logger.info("定时抓取已%s", "开启" if enabled else "停止")
    return get_fetch_status()


def get_fetch_status() -> dict[str, Any]:
    from news_mornitor.pipeline import ingest_gate

    with _LOCK:
        state = _load()
    remain = seconds_until_next()
    return {
        "ok": True,
        "enabled": bool(state.get("enabled", True)),
        "running": bool(getattr(ingest_gate, "_running", False)),
        "interval_sec": int(FETCH_INTERVAL_SEC),
        "retry_after_sec": int(remain),
        "updated_at": state.get("updated_at") or 0,
    }


async def fetch_now(*, limit_per_source: int = 40) -> dict[str, Any]:
    """立即抓取一轮（忽略定时开关与间隔；进行中则返回 already_running）。"""
    result = await run_ingest_gated(force=True, limit_per_source=limit_per_source)
    status = get_fetch_status()
    return {**result, "status": status}
