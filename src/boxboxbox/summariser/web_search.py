"""Web search tool for digest agent — Tavily-powered F1 news retrieval."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from pydantic_ai import RunContext

logger = logging.getLogger(__name__)

_AUTHORITATIVE_DOMAINS = [
    "formula1.com",
    "autosport.com",
    "skysports.com",
]

_MAX_SEARCHES_PER_DIGEST = 3


@dataclass
class DigestDeps:
    """Dependencies injected into the digest agent at run time."""

    tavily_api_key: str
    circuit_name: str  # e.g. "Monza"
    session_name: str  # e.g. "Race" or "Qualifying"
    _search_count: int = field(default=0, repr=False)


async def search_f1_news(ctx: RunContext[DigestDeps], query: str) -> str:
    """Search authoritative F1 news sources (formula1.com, autosport.com, skysports.com) for recent
    articles relevant to this session. Use this to find driver storylines, championship context,
    expert analysis, pre-race predictions, or post-race reactions. Call 1-2 times maximum."""

    deps = ctx.deps

    if deps._search_count >= _MAX_SEARCHES_PER_DIGEST:
        return "Search limit reached for this digest."

    deps._search_count += 1

    augmented_query = f"F1 {deps.circuit_name} {deps.session_name} {query}"
    logger.debug("search_f1_news: query=%r", augmented_query)

    try:
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=deps.tavily_api_key)
        t0 = time.monotonic()
        response = await client.search(
            query=augmented_query,
            include_domains=_AUTHORITATIVE_DOMAINS,
            max_results=3,
            search_depth="basic",
        )
        elapsed = time.monotonic() - t0
        results = response.get("results", [])
        logger.debug("search_f1_news: %d results in %.1fs", len(results), elapsed)

        if not results:
            return "No results found."

        parts: list[str] = []
        for r in results:
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = r.get("content", "")
            parts.append(f"**{title}**\nSource: {url}\n{content}")

        return "\n\n---\n\n".join(parts)

    except Exception:
        logger.warning("search_f1_news: Tavily search failed", exc_info=True)
        return "No results found."
