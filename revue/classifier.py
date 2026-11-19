"""Étape 1 du LLM : pertinence de chaque article (brief de sécurité ou non)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .llm import LLMClient
from .models import Article, Verdict, VerdictBatch
from .prompts import SYSTEM_CLASSIFY, format_article_line

log = logging.getLogger(__name__)


def _non_classe(sid: str) -> Verdict:
    return Verdict(id=sid, pertinent=False, critere=0, portee="Canada", stade="autre",
                   importance=1, justification="NON CLASSÉ : réponse du LLM incomplète.")


def _classify_batch(llm: LLMClient, batch: list[tuple[str, Article]]) -> dict[str, Verdict]:
    user = "Articles à classer :\n" + "\n".join(
        format_article_line(sid, a.media, a.title, a.summary) for sid, a in batch
    )
    out = llm.structured("classify", VerdictBatch, SYSTEM_CLASSIFY, user)
    attendus = {sid for sid, _ in batch}
    res: dict[str, Verdict] = {}
    for v in out.verdicts:
        if v.id in attendus and v.id not in res:
            v.importance = min(5, max(1, v.importance))
            if v.portee == "Hors Canada":
                v.pertinent = False
            res[v.id] = v
    return res


def classify(articles: list[Article], llm: LLMClient, batch_size: int = 15,
             parallel: int = 4) -> tuple[dict[str, Verdict], int]:
    """Retourne ({article.id: Verdict}, nb_non_classés)."""
    indexed = [(f"a{i}", a) for i, a in enumerate(articles)]
    by_sid = dict(indexed)
    batches = [indexed[i:i + batch_size] for i in range(0, len(indexed), batch_size)]
    verdicts: dict[str, Verdict] = {}
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for res in pool.map(lambda b: _classify_batch(llm, b), batches):
            verdicts.update(res)

    # Articles oubliés par le LLM : une seconde chance, un par un
    manquants = [(sid, by_sid[sid]) for sid in by_sid if sid not in verdicts]
    if manquants:
        log.warning("%d article(s) sans verdict, nouvel essai...", len(manquants))
        for item in manquants:
            try:
                verdicts.update(_classify_batch(llm, [item]))
            except Exception as exc:
                log.warning("Échec de reclassification de %s : %s", item[0], exc)
    non_classes = 0
    final: dict[str, Verdict] = {}
    for sid, art in indexed:
        v = verdicts.get(sid)
        if v is None:
            v = _non_classe(sid)
            non_classes += 1
        final[art.id] = v
    return final, non_classes
