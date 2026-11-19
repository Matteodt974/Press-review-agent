"""Étape 2 du LLM : regrouper les articles d'une même affaire (dédoublonnage)."""
from __future__ import annotations

import logging

from .llm import LLMClient
from .models import Article, Clustering
from .prompts import SYSTEM_CLUSTER, format_article_line

log = logging.getLogger(__name__)


def sanitize_groups(raw: list[list[str]], all_ids: list[str]) -> list[list[str]]:
    """Garantit que chaque identifiant apparaît exactement une fois."""
    valid = set(all_ids)
    vus: set[str] = set()
    groups: list[list[str]] = []
    for g in raw:
        clean = [i for i in g if i in valid and i not in vus]
        vus.update(clean)
        if clean:
            groups.append(clean)
    oublies = [i for i in all_ids if i not in vus]
    if oublies:
        log.warning("%d article(s) non regroupé(s) par le LLM : traités comme affaires uniques.", len(oublies))
    groups.extend([i] for i in oublies)
    return groups


def cluster(articles: list[Article], llm: LLMClient) -> list[list[Article]]:
    if len(articles) <= 1:
        return [articles] if articles else []
    indexed = {f"a{i}": a for i, a in enumerate(articles)}
    user = "Articles à regrouper :\n" + "\n".join(
        format_article_line(sid, a.media, f"{a.published:%Y-%m-%d} {a.title}", a.summary, 300)
        for sid, a in indexed.items()
    )
    out = llm.structured("write", Clustering, SYSTEM_CLUSTER, user)
    groups = sanitize_groups([g.ids for g in out.groupes], list(indexed))
    return [[indexed[i] for i in g] for g in groups]
