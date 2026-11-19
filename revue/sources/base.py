"""Interface commune des sources.

Pour ajouter plus tard une API de recherche payante : créer une classe qui
hérite de Source, implémenter fetch(), et l'ajouter dans build_sources().
"""
from __future__ import annotations

import hashlib
import html
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import requests

from ..models import Article

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RevueSecurite/1.0 (lecteur RSS)"

Fetcher = Callable[[str, float], bytes]


def http_fetch(url: str, timeout: float) -> bytes:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.content


@dataclass
class FetchResult:
    articles: list[Article] = field(default_factory=list)
    echecs: list[str] = field(default_factory=list)  # "Média — url : erreur"
    sans_date: int = 0


class Source(ABC):
    name: str = "source"

    @abstractmethod
    def fetch(self, since: datetime, now: datetime) -> FetchResult: ...


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str, max_len: int = 600) -> str:
    txt = html.unescape(_TAG_RE.sub(" ", raw or ""))
    txt = _WS_RE.sub(" ", txt).strip()
    return txt[:max_len]


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime(*st[:6], tzinfo=timezone.utc)
    return None
