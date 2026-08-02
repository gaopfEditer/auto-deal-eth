"""AI 洗稿 / 摘要 / 代币提取；无 Key 时走规则回退。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from news_mornitor.config import AI_ENABLED, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from news_mornitor.models import Post

logger = logging.getLogger("CryptoPulse.AI")

SPAM_PATTERNS = [
    re.compile(r"邀请码", re.I),
    re.compile(r"invite\s*code", re.I),
    re.compile(r"免费领取", re.I),
    re.compile(r"躺赚", re.I),
    re.compile(r"无风险", re.I),
    re.compile(r"加微信|加\s*vx|加\s*v", re.I),
    re.compile(r"空投.*(链接|点击)", re.I),
]

TICKER_RE = re.compile(r"\$([A-Z]{2,10})\b")
KNOWN_TICKERS = {
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "LINK",
    "DOT",
    "MATIC",
    "ARB",
    "OP",
    "SUI",
    "APT",
    "NEAR",
    "FET",
    "TAO",
    "PEPE",
    "WIF",
    "ORDI",
    "TIA",
}


def rule_is_spam(text: str) -> bool:
    return any(p.search(text or "") for p in SPAM_PATTERNS)


def rule_extract_tickers(text: str) -> list[str]:
    found = {m.upper() for m in TICKER_RE.findall(text or "")}
    upper = (text or "").upper()
    for t in KNOWN_TICKERS:
        if re.search(rf"\b{t}\b", upper):
            found.add(t)
    return sorted(found)


def rule_summary(title: str, content: str) -> str:
    body = (content or "").strip().replace("\n", " ")
    head = (title or "").strip()
    if head and body.startswith(head):
        body = body[len(head) :].strip(" ：:—-")
    # 截两句
    parts = re.split(r"[。！？.!?]", body)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts and head:
        return head[:80]
    if len(parts) == 1:
        return parts[0][:120]
    return f"{parts[0][:80]}。{parts[1][:80]}。"


def enrich_post_rules(post: Post) -> Post:
    from news_mornitor.pipeline.content_quality import is_generic_wire

    text = f"{post.title}\n{post.content}"
    post.is_spam = rule_is_spam(text) or is_generic_wire(
        post.title, post.content, post.author
    )
    if not post.mentioned_tickers:
        post.mentioned_tickers = rule_extract_tickers(text)
    if not post.summary:
        post.summary = rule_summary(post.title, post.content)
    return post


_AI_PROMPT = """你是加密社区审稿。根据帖子原文：
1) spam: 以下任一则为 true——邀请码/纯喊单推广；媒体简报腔（「再创新高」「溢价回升」「风险资产共振」这类研报标题，无个人经历）；否则 false
2) tickers: 提取代币符号数组，如 ["BTC","ETH"]，无则 []
3) summary: 用恰好 2 句中文摘要，保留口语与个人立场，不要写成新闻稿

只输出 JSON：{{"spam":bool,"tickers":[...],"summary":"..."}}

标题：{title}
正文：{content}
"""


async def enrich_post_llm(post: Post) -> Post:
    if not AI_ENABLED or not LLM_API_KEY:
        return enrich_post_rules(post)

    import aiohttp

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": _AI_PROMPT.format(
                    title=post.title[:200],
                    content=(post.content or "")[:2000],
                ),
            }
        ],
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    try:
        timeout = aiohttp.ClientTimeout(total=40)
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("LLM HTTP %s: %s", resp.status, text[:200])
                    return enrich_post_rules(post)
                data = await resp.json()
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
        # 剥 markdown code fence
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        parsed: dict[str, Any] = json.loads(content)
        post.is_spam = bool(parsed.get("spam"))
        ticks = parsed.get("tickers") or []
        if isinstance(ticks, list):
            post.mentioned_tickers = [str(t).upper().lstrip("$") for t in ticks if t]
        summary = parsed.get("summary")
        if isinstance(summary, str) and summary.strip():
            post.summary = summary.strip()
        return post
    except Exception as e:
        logger.warning("LLM  enrichment 失败，回退规则: %s", e)
        return enrich_post_rules(post)


async def enrich_posts(posts: list[Post]) -> list[Post]:
    out: list[Post] = []
    for p in posts:
        # 已有摘要且非首次：跳过 LLM，仅规则补全
        if p.summary and p.mentioned_tickers is not None and AI_ENABLED:
            out.append(p)
            continue
        out.append(await enrich_post_llm(p))
    return out
