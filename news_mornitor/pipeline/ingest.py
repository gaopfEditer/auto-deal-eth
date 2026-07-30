"""抓取 → 打分 → AI 增强 → 落盘 流水线。"""
from __future__ import annotations

import logging

from news_mornitor.fetchers.manager import FetcherManager
from news_mornitor.models import Post
from news_mornitor.pipeline.ai_enrich import enrich_posts
from news_mornitor.pipeline.scoring import apply_score
from news_mornitor.store import FileStore

logger = logging.getLogger("CryptoPulse.Pipeline")


class IngestPipeline:
    def __init__(
        self,
        store: FileStore | None = None,
        fetchers: FetcherManager | None = None,
    ) -> None:
        self.store = store or FileStore()
        self.fetchers = fetchers or FetcherManager()

    async def run_once(self, *, limit_per_source: int = 40) -> dict:
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
        for p in all_posts.values():
            apply_score(p)
        self.store.save_posts(all_posts)
        trending = self.store.rebuild_tickers_24h(all_posts)

        from news_mornitor.fetchers.macro_calendar import fetch_jinshi_calendar

        macro = await fetch_jinshi_calendar()
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
            "by_platform": {
                "BINANCE": sum(1 for p in candidates if p.platform.value == "BINANCE"),
                "BITGET": sum(1 for p in candidates if p.platform.value == "BITGET"),
                "OKX": sum(1 for p in candidates if p.platform.value == "OKX"),
            },
        }
        logger.info("流水线完成: %s", result)
        return result
