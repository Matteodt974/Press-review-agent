"""Préfiltre sans LLM : fenêtre temporelle, dédoublonnage exact, mots-clés."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import Article


def strip_accents(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(c))


def norm_text(txt: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", strip_accents(txt.lower())).strip()


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "cid"))]
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", urlencode(query), ""))


def compile_keywords(keywords: list[str]) -> re.Pattern | None:
    kws = [norm_text(k) for k in keywords if k.strip()]
    if not kws:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")")


@dataclass
class PrefilterResult:
    candidates: list[Article]
    stats: dict = field(default_factory=dict)


def prefilter(articles: list[Article], since: datetime, now: datetime, keywords: list[str],
              use_keywords: bool = True, max_candidates: int = 400) -> PrefilterResult:
    stats = {"recus": len(articles)}

    # 1) Fenêtre : publié après le dernier lancement (tolérance d'1 jour dans le futur
    #    pour les fuseaux horaires mal déclarés dans certains flux)
    in_window = [a for a in articles if since <= a.published <= now + timedelta(days=1)]
    stats["dans_fenetre"] = len(in_window)

    # 2) Dédoublonnage exact (même URL, ou même titre chez le même média).
    #    On préfère le lien direct du média (RSS) au lien Google News.
    in_window.sort(key=lambda a: (a.source != "rss", a.published))
    seen_url: set[str] = set()
    seen_title: set[tuple[str, str]] = set()
    uniques: list[Article] = []
    for a in in_window:
        ku = normalize_url(a.url)
        kt = (a.media.split(" (")[0], norm_text(a.title))
        if ku in seen_url or kt in seen_title:
            continue
        seen_url.add(ku)
        seen_title.add(kt)
        uniques.append(a)
    stats["uniques"] = len(uniques)

    # 3) Mots-clés (large, pour réduire le coût LLM sans perdre de rappel)
    pattern = compile_keywords(keywords) if use_keywords else None
    if pattern is not None:
        cands = [a for a in uniques if pattern.search(norm_text(f"{a.title} {a.summary}"))]
    else:
        cands = uniques
    stats["apres_mots_cles"] = len(cands)

    # 4) Plafond (protection du coût) : on garde les plus récents
    cands.sort(key=lambda a: a.published, reverse=True)
    stats["tronques"] = max(0, len(cands) - max_candidates)
    cands = cands[:max_candidates]
    stats["candidats"] = len(cands)
    return PrefilterResult(cands, stats)
