"""Construction des sources à partir de la configuration."""
from __future__ import annotations

from .base import Source
from .google_news import GoogleNewsSource
from .rss import RSSSource


def build_sources(cfg: dict) -> list[Source]:
    sc = cfg["sources"]
    timeout = sc.get("timeout_seconds", 20)
    sources: list[Source] = []
    if sc.get("rss", True) and cfg.get("feeds"):
        sources.append(RSSSource(cfg["feeds"], timeout=timeout))
    if sc.get("google_news", True):
        sources.append(GoogleNewsSource(cfg["google_news"], timeout=timeout))
    # Plus tard : sources.append(MonApiPayanteSource(...))
    return sources
