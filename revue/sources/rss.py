"""Source : flux RSS des médias."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import feedparser

from ..models import Article
from .base import FetchResult, Fetcher, Source, article_id, clean_text, entry_datetime, http_fetch

log = logging.getLogger(__name__)

_CP_MARKERS = ("presse canadienne", "canadian press")


def parse_feed(content: bytes, media: str) -> tuple[list[Article], int]:
    """Transforme un flux RSS/Atom en articles. Retourne (articles, nb_sans_date)."""
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"flux illisible ({parsed.get('bozo_exception')})")
    articles: list[Article] = []
    sans_date = 0
    for e in parsed.entries:
        url = e.get("link")
        title = clean_text(e.get("title", ""), 300)
        if not url or not title:
            continue
        published = entry_datetime(e)
        if published is None:
            sans_date += 1  # sans date, impossible de savoir s'il est « nouveau »
            continue
        nom = media
        auteur = (e.get("author") or "").lower()
        if any(m in auteur for m in _CP_MARKERS):
            nom = f"{media} (La Presse Canadienne)"
        articles.append(Article(
            id=article_id(url), title=title,
            summary=clean_text(e.get("summary", "") or e.get("description", "")),
            url=url, media=nom, published=published, source="rss",
        ))
    return articles, sans_date


class RSSSource(Source):
    name = "Flux RSS des médias"

    def __init__(self, feeds: list[dict], timeout: float = 20, fetcher: Fetcher = http_fetch,
                 workers: int = 8):
        self.feeds = feeds
        self.timeout = timeout
        self.fetcher = fetcher
        self.workers = workers

    def _one(self, feed: dict):
        content = self.fetcher(feed["url"], self.timeout)
        return parse_feed(content, feed["media"])

    def fetch(self, since: datetime, now: datetime) -> FetchResult:
        res = FetchResult()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._one, f): f for f in self.feeds}
            for fut, feed in futures.items():
                try:
                    arts, sans_date = fut.result()
                    res.articles.extend(arts)
                    res.sans_date += sans_date
                    log.info("  %-22s %3d articles  (%s)", feed["media"], len(arts), feed["url"])
                except Exception as exc:
                    msg = f"{feed['media']} — {feed['url']} : {type(exc).__name__}: {exc}"
                    log.warning("  ÉCHEC %s", msg)
                    res.echecs.append(msg)
        return res
