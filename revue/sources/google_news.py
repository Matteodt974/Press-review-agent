"""Source : recherche Google News via ses flux RSS publics.

Les flux des médias ne gardent que quelques jours d'articles ; la recherche
Google News permet de remonter plus loin (paramètre when:Nj). Les liens
renvoyés sont des redirections Google News vers l'article original.
Seuls les résultats provenant des médias autorisés (config) sont gardés.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote, urlparse

import feedparser

from ..models import Article
from .base import FetchResult, Fetcher, Source, article_id, clean_text, entry_datetime, http_fetch

log = logging.getLogger(__name__)

LOCALES = {
    "fr": "hl=fr-CA&gl=CA&ceid=CA:fr",
    "en": "hl=en-CA&gl=CA&ceid=CA:en",
}


def build_url(query: str, days: int, lang: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(f'{query} when:{days}d')}&{LOCALES[lang]}"


def _domain(href: str) -> str:
    host = (urlparse(href).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def resolve_media(href: str, source_title: str, domains: dict[str, str],
                  source_names: list[str]) -> str | None:
    host = _domain(href)
    for dom, media in domains.items():
        if host == dom or host.endswith("." + dom):
            return media
    for name in source_names:
        if source_title.strip().lower() == name.lower():
            return name
    return None


def parse_results(content: bytes, domains: dict[str, str], source_names: list[str]) -> list[Article]:
    parsed = feedparser.parse(content)
    out: list[Article] = []
    for e in parsed.entries:
        src = e.get("source") or {}
        media = resolve_media(src.get("href", ""), src.get("title", ""), domains, source_names)
        if not media:
            continue  # média hors liste -> ignoré
        published = entry_datetime(e)
        url = e.get("link")
        if not published or not url:
            continue
        title = clean_text(e.get("title", ""), 300)
        # Google News ajoute toujours « - Nom du média » à la fin du titre
        if " - " in title and len(title.rsplit(" - ", 1)[1]) <= 40:
            title = title.rsplit(" - ", 1)[0]
        summary = clean_text(e.get("summary", ""))
        if summary.startswith(title):  # le résumé Google répète souvent le titre
            summary = ""
        out.append(Article(id=article_id(url), title=title, summary=summary, url=url,
                           media=media, published=published, source="google_news"))
    return out


class GoogleNewsSource(Source):
    name = "Recherche Google News"

    def __init__(self, cfg: dict, timeout: float = 20, fetcher: Fetcher = http_fetch):
        self.cfg = cfg
        self.timeout = timeout
        self.fetcher = fetcher

    def fetch(self, since: datetime, now: datetime) -> FetchResult:
        days = max(1, math.ceil((now - since).total_seconds() / 86400))
        jobs = [(q, "fr") for q in self.cfg.get("queries_fr", [])]
        jobs += [(q, "en") for q in self.cfg.get("queries_en", [])]
        res = FetchResult()

        def one(job):
            q, lang = job
            content = self.fetcher(build_url(q, days, lang), self.timeout)
            return parse_results(content, self.cfg.get("domains", {}), self.cfg.get("source_names", []))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(one, j): j for j in jobs}
            for fut, (q, lang) in futures.items():
                try:
                    arts = fut.result()
                    res.articles.extend(arts)
                    log.info("  Google News [%s] %3d résultats : %s", lang, len(arts), q[:60])
                except Exception as exc:
                    msg = f"Google News [{lang}] « {q} » : {type(exc).__name__}: {exc}"
                    log.warning("  ÉCHEC %s", msg)
                    res.echecs.append(msg)
        return res
