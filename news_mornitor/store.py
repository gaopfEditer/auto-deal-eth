"""JSON 文件读写缓存（替代 PostgreSQL + Redis）。"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from news_mornitor.config import (
    API_CACHE_TTL_SEC,
    CACHE_DIR,
    DATA_DIR,
    MACRO_FILE,
    POSTS_FILE,
    POSTS_MAX_KEEP,
    SEEN_IDS_FILE,
    TICKERS_FILE,
)
from news_mornitor.models import MacroEvent, Post, Ticker, utc_now_iso

logger = logging.getLogger("CryptoPulse.Store")

_lock = threading.RLock()


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else dict(default)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取 %s 失败: %s，使用默认值", path, e)
        return dict(default)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


class FileStore:
    """帖子 / 代币 / 去重 / API 响应缓存。"""

    def __init__(self) -> None:
        _ensure_dirs()

    # ── posts ──────────────────────────────────────────────

    def load_posts(self) -> dict[str, Post]:
        with _lock:
            raw = _read_json(POSTS_FILE, {"posts": {}, "updated_at": ""})
            out: dict[str, Post] = {}
            for pid, item in (raw.get("posts") or {}).items():
                try:
                    out[pid] = Post.model_validate(item)
                except Exception as e:
                    logger.debug("跳过损坏帖子 %s: %s", pid, e)
            return out

    def save_posts(self, posts: dict[str, Post]) -> None:
        with _lock:
            # 按 score 保留 Top N，其余按时间淘汰
            items = sorted(
                posts.values(),
                key=lambda p: (p.score, p.published_at),
                reverse=True,
            )[:POSTS_MAX_KEEP]
            payload = {
                "posts": {p.id: p.model_dump(mode="json") for p in items},
                "updated_at": utc_now_iso(),
            }
            _write_json(POSTS_FILE, payload)

    def upsert_posts(self, new_posts: list[Post]) -> tuple[int, int]:
        """返回 (inserted, updated)。"""
        with _lock:
            posts = self.load_posts()
            inserted = updated = 0
            for p in new_posts:
                if p.id in posts:
                    old = posts[p.id]
                    # 保留已有 summary / tickers / is_spam，更新互动与分数
                    p.summary = p.summary or old.summary
                    p.mentioned_tickers = p.mentioned_tickers or old.mentioned_tickers
                    p.is_spam = old.is_spam if p.summary else p.is_spam
                    updated += 1
                else:
                    inserted += 1
                posts[p.id] = p
            self.save_posts(posts)
            return inserted, updated

    # ── seen ids ───────────────────────────────────────────

    def load_seen_ids(self) -> set[str]:
        with _lock:
            raw = _read_json(SEEN_IDS_FILE, {"ids": []})
            return set(raw.get("ids") or [])

    def add_seen_ids(self, ids: list[str]) -> None:
        with _lock:
            seen = self.load_seen_ids()
            seen.update(ids)
            # 截断，避免无限膨胀
            trimmed = sorted(seen)[-max(POSTS_MAX_KEEP * 2, 5000) :]
            _write_json(SEEN_IDS_FILE, {"ids": trimmed, "updated_at": utc_now_iso()})

    # ── tickers ────────────────────────────────────────────

    def load_tickers(self) -> dict[str, Ticker]:
        with _lock:
            raw = _read_json(TICKERS_FILE, {"tickers": {}, "updated_at": ""})
            out: dict[str, Ticker] = {}
            for sym, item in (raw.get("tickers") or {}).items():
                try:
                    out[sym] = Ticker.model_validate(item)
                except Exception:
                    continue
            return out

    def save_tickers(self, tickers: dict[str, Ticker]) -> None:
        with _lock:
            _write_json(
                TICKERS_FILE,
                {
                    "tickers": {k: v.model_dump(mode="json") for k, v in tickers.items()},
                    "updated_at": utc_now_iso(),
                },
            )

    def rebuild_tickers_24h(self, posts: dict[str, Post] | None = None) -> list[Ticker]:
        """根据近 24h 非垃圾帖重建热门代币榜。"""
        from datetime import datetime, timedelta, timezone

        posts = posts or self.load_posts()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        buckets: dict[str, Ticker] = {}

        for p in posts.values():
            if p.is_spam:
                continue
            try:
                ts = datetime.fromisoformat(p.published_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            for sym in p.mentioned_tickers:
                s = sym.strip().upper().lstrip("$")
                if not s:
                    continue
                t = buckets.get(s) or Ticker(symbol=s, updated_at=utc_now_iso())
                if p.id not in t.post_ids:
                    t.post_ids.append(p.id)
                    t.mention_count_24h = len(t.post_ids)
                t.updated_at = utc_now_iso()
                buckets[s] = t

        self.save_tickers(buckets)
        return sorted(buckets.values(), key=lambda x: x.mention_count_24h, reverse=True)

    # ── macro timeline ─────────────────────────────────────

    def load_macro_events(self) -> list[MacroEvent]:
        with _lock:
            raw = _read_json(MACRO_FILE, {"events": [], "updated_at": ""})
            out: list[MacroEvent] = []
            for item in raw.get("events") or []:
                try:
                    out.append(MacroEvent.model_validate(item))
                except Exception:
                    continue
            return out

    def save_macro_events(self, events: list[MacroEvent]) -> None:
        with _lock:
            _write_json(
                MACRO_FILE,
                {
                    "events": [e.model_dump(mode="json") for e in events],
                    "updated_at": utc_now_iso(),
                },
            )

    # ── API response cache ─────────────────────────────────

    def cache_get(self, key: str) -> Any | None:
        path = CACHE_DIR / f"{key}.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                blob = json.load(f)
            if time.time() - float(blob.get("_ts", 0)) > API_CACHE_TTL_SEC:
                return None
            return blob.get("data")
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def cache_set(self, key: str, data: Any) -> None:
        _ensure_dirs()
        path = CACHE_DIR / f"{key}.json"
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump({"_ts": time.time(), "data": data}, f, ensure_ascii=False)
        except OSError as e:
            logger.warning("写缓存失败 %s: %s", key, e)

    def cache_clear(self) -> int:
        """清空 API 响应缓存（ingest 后调用）。"""
        _ensure_dirs()
        n = 0
        for p in CACHE_DIR.glob("*.json"):
            try:
                p.unlink()
                n += 1
            except OSError:
                continue
        return n
