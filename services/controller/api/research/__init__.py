"""ARES-owned research service."""

from .deep_researcher import DeepResearcher
from .handler import ResearchHandler


def health_probe() -> None:
    """Raise when ARES cannot execute the local half of deep research."""
    from api.backend_selector import get_active_backend
    from api.backends.router import get_router
    from api.config import get_config

    config = get_config()
    search = config.get("search") if isinstance(config, dict) else None
    search_url = (
        search.get("searxng_url") or search.get("search_url")
        if isinstance(search, dict)
        else None
    )
    if not str(search_url or "").strip():
        raise RuntimeError("Deep Research requires a configured search service")
    backend_id = get_active_backend(config)
    if get_router().select(backend_id) is None:
        raise RuntimeError(f"Runtime unavailable: {backend_id}")


__all__ = ["DeepResearcher", "ResearchHandler", "health_probe"]
