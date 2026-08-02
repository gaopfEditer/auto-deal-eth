"""抓取 → 打分 → AI 增强 → 落盘 流水线。"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from news_mornitor.config import USE_MOCK_FETCHER
from news_mornitor.fetchers.manager import FetcherManager
from news_mornitor.models import Platform, Post
from news_mornitor.pipeline.ai_enrich import enrich_posts
from news_mornitor.pipeline.scoring import apply_score
from news_mornitor.store import FileStore

logger = logging.getLogger("CryptoPulse.Pipeline")

_MOCK_EID = re.compile(r"^[a-z]{3,4}-p\d+", re.I)


def _looks_like_demo_post(post: Post) -> bool:
    """旧 mock / 无真实外链条目，真爬模式下应从库中剔除。"""
    eid = (post.external_id or "").strip()
    if _MOCK_EID.match(eid):
        return True
    url = (post.source_url or "").strip()
    if not url.startswith("http"):
        return True
    return False


def _is_stale_viral_reddit(post: Post) -> bool:
    """PullPush 陈年高赞（>30 天）不应占榜。"""
    plat = post.platform.value if hasattr(post.platform, "value") else str(post.platform)
    if plat != Platform.REDDIT.value:
        return False
    try:
        ts = datetime.fromisoformat((post.published_at or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    return age_days > 30


class IngestPipeline:
    def __init__(
        self,
        store: FileStore | None = None,
        fetchers: FetcherManager | None = None,
    ) -> None:
        self.store = store or FileStore()
        self.fetchers = fetchers or FetcherManager()

    async def run_once(self, *, limit_per_source: int = 40) -> dict:
        if not USE_MOCK_FETCHER:
            existing = self.store.load_posts()
            kept = {
                pid: p
                for pid, p in existing.items()
                if not _looks_like_demo_post(p) and not _is_stale_viral_reddit(p)
            }
            dropped = len(existing) - len(kept)
            if dropped:
                logger.info("真爬模式：清除 %s 条演示/陈年 Reddit 残留", dropped)
                self.store.save_posts(kept)

        raw_items = await self.fetchers.fetch_all(limit_per_source=limit_per_source)
        seen = self.store.load_seen_ids()
        existing = self.store.load_posts()

        candidates: list[Post] = []
        for item in raw_items:
            post = Post.from_raw(
                platform=item.platform,
                external_id=item.external_id,
                author=item.author,
                author_avatar=item.author_avatar,
                title=item.title,
                content=item.content,
                like_count=item.like_count,
                comment_count=item.comment_count,
                share_count=item.share_count,
                published_at=item.published_at,
                source_url=item.source_url,
                image_urls=item.image_urls,
            )
            if not USE_MOCK_FETCHER and _looks_like_demo_post(post):
                continue
            if post.id in existing:
                old = existing[post.id]
                post.summary = old.summary
                post.mentioned_tickers = old.mentioned_tickers
                post.is_spam = old.is_spam
            apply_score(post)
            candidates.append(post)

        need_ai = [p for p in candidates if not p.summary or p.id not in seen]
        if need_ai:
            enriched_map = {p.id: p for p in await enrich_posts(need_ai)}
            for i, p in enumerate(candidates):
                if p.id in enriched_map:
                    candidates[i] = apply_score(enriched_map[p.id])

        inserted, updated = self.store.upsert_posts(candidates)
        self.store.add_seen_ids([p.id for p in candidates])

        all_posts = self.store.load_posts()
        if not USE_MOCK_FETCHER:
            all_posts = {
                pid: p
                for pid, p in all_posts.items()
                if not _looks_like_demo_post(p) and not _is_stale_viral_reddit(p)
            }
        for p in all_posts.values():
            apply_score(p)
        self.store.save_posts(all_posts)
        trending = self.store.rebuild_tickers_24h(all_posts)

        from news_mornitor.fetchers.macro_calendar import fetch_jinshi_calendar

        macro = await fetch_jinshi_calendar()
        # 真爬且本轮无宏观数据时，清掉旧 mock 宏观
        if not USE_MOCK_FETCHER and not macro:
            self.store.save_macro_events([])
        else:
            self.store.save_macro_events(macro)
        cleared = self.store.cache_clear()

        result = {
            "fetched": len(raw_items),
            "upserted": len(candidates),
            "inserted": inserted,
            "updated": updated,
            "tickers_top": [t.symbol for t in trending[:10]],
            "macro_events": len(macro),
            "cache_cleared": cleared,
            "use_mock": USE_MOCK_FETCHER,
            "by_platform": {},
        }
        for p in candidates:
            key = p.platform.value if hasattr(p.platform, "value") else str(p.platform)
            result["by_platform"][key] = result["by_platform"].get(key, 0) + 1
        logger.info("流水线完成: %s", result)
        return result
