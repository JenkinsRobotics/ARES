"""ARES Research Search Bridge — connects DeepResearcher to ARES search backends.

Provides async web_search and web_extract callables that the researcher uses.
Falls back to SearXNG (if configured) or direct web scraping.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)
_MAX_PAGE_BYTES = 2 * 1024 * 1024


def _public_http_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Research sources must use an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Research source URLs cannot contain credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for info in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(info[4][0])
        candidate = getattr(address, "ipv4_mapped", None) or address
        if (
            candidate.is_loopback
            or candidate.is_private
            or candidate.is_link_local
            or candidate.is_multicast
            or candidate.is_reserved
            or candidate.is_unspecified
        ):
            raise ValueError("Research sources cannot target private or local addresses")
    return parsed.geturl()


async def _fetch_public_text(url: str) -> str:
    import httpx

    current = url
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        for _redirect in range(6):
            current = _public_http_url(current)
            async with client.stream(
                "GET",
                current,
                headers={"User-Agent": "ARES-Research/1.0 (Mozilla/5.0 compatible)"},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return ""
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    return ""
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_PAGE_BYTES:
                        raise ValueError("Research source exceeds the 2 MB extraction limit")
                return content.decode(response.encoding or "utf-8", errors="replace")
    raise ValueError("Research source redirected too many times")


async def web_search(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Search the web and return results as [{title, url, snippet}].

    Uses ARES's configured search backend (SearXNG, Brave, etc.)
    or falls back to a direct approach.
    """
    results: List[Dict[str, str]] = []

    # A configured SearXNG service is the current supported search owner.
    try:
        from api.config import get_config
        cfg = get_config()
        search_cfg = cfg.get("search", {}) if isinstance(cfg, dict) else {}

        # Check for SearXNG configuration
        searxng_url = search_cfg.get("searxng_url") or search_cfg.get("search_url")
        if searxng_url:
            results = await _searxng_search(searxng_url, query, limit)
            if results:
                return results
    except Exception as e:
        logger.debug(f"ARES config search not available: {e}")

    return results


async def _searxng_search(
    searxng_url: str, query: str, limit: int = 5
) -> List[Dict[str, str]]:
    """Search using SearXNG instance."""
    import httpx

    results = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{searxng_url.rstrip('/')}/search",
                params={"q": query, "format": "json", "categories": "general"},
                headers={"User-Agent": "ARES-Research/1.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", [])[:limit]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                    })
    except Exception as e:
        logger.error(f"SearXNG search failed: {e}")
    return results


async def web_extract(url: str, goal: str) -> Optional[Dict[str, str]]:
    """Extract relevant content from a URL for a research goal.

    Returns {rational, evidence, summary} from goal-based extraction,
    or None if extraction fails.
    """
    try:
        content = await _fetch_public_text(url)
        content = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", content)
        content = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", content)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()

        if len(content) < 100:
            return None

        content = content[:15000]
        return {
            "rational": f"Content extracted from {url} for research goal: {goal}",
            "evidence": content[:5000],
            "summary": content[:2000],
        }
    except Exception as e:
        logger.debug(f"Content extraction failed for {url}: {e}")
        return None
