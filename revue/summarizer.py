"""Étape 3 du LLM : titre + résumé français par affaire, synthèse globale, tri."""
from __future__ import annotations

import logging

from .llm import LLMClient
from .models import STADE_ORDRE, Affaire, Article, Redaction, Verdict
from .prompts import SYSTEM_WRITE, format_article_line

log = logging.getLogger(__name__)


def _fusion(group: list[Article], verdicts: dict[str, Verdict]) -> dict:
    vs = [verdicts[a.id] for a in group]
    return {
        "portee": "Québec" if any(v.portee == "Québec" for v in vs) else "Canada",
        "stade": max((v.stade for v in vs), key=lambda s: STADE_ORDRE.get(s, 0)),
        "importance": max(v.importance for v in vs),
        "criteres": sorted({v.critere for v in vs if v.critere}),
    }


def sort_key(a: Affaire):
    # Importance d'abord ; à importance égale le Québec passe devant,
    # puis l'affaire la plus reprise par les médias, puis la plus récente.
    return (-a.importance, a.portee != "Québec", -len(a.medias), -a.derniere_date.timestamp())


def build_affaires(groups: list[list[Article]], verdicts: dict[str, Verdict],
                   llm: LLMClient) -> tuple[list[Affaire], str]:
    if not groups:
        return [], ""
    meta = [_fusion(g, verdicts) for g in groups]
    blocs = []
    for i, (g, m) in enumerate(zip(groups, meta), start=1):
        lignes = "\n".join(format_article_line(f"a{j}", a.media, a.title, a.summary, 500)
                           for j, a in enumerate(g))
        blocs.append(f"### Affaire {i}\nPortée : {m['portee']} — Stade : {m['stade']}\n{lignes}\n")
    out = llm.structured("write", Redaction, SYSTEM_WRITE, "\n".join(blocs))
    fiches = {f.index: f for f in out.fiches}

    affaires = []
    for i, (g, m) in enumerate(zip(groups, meta), start=1):
        f = fiches.get(i)
        if f is None:
            log.warning("Pas de résumé pour l'affaire %d : titre d'origine utilisé.", i)
        affaires.append(Affaire(
            titre=f.titre if f else g[0].title,
            resume=f.resume if f else (g[0].summary or g[0].title),
            articles=sorted(g, key=lambda a: a.published),
            **m,
        ))
    affaires.sort(key=sort_key)
    return affaires, out.resume_global
