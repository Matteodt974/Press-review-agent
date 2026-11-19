"""Orchestration LangGraph.

load_state -> fetch -> prefilter -> [candidats ?] -> classify -> [pertinents ?]
           -> cluster -> summarize -> write_report -> save_state
(si rien à analyser ou rien de pertinent : saut direct vers write_report)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .classifier import classify
from .clustering import cluster
from .llm import LLMClient
from .models import Affaire, Article, Verdict
from .prefilter import prefilter
from .report import ReportData, write_report
from .sources.base import Source
from .state import Fenetre, compute_window, load_last_run, save_state
from .summarizer import build_affaires

log = logging.getLogger(__name__)


class RunState(TypedDict, total=False):
    fenetre: Fenetre
    articles: list[Article]
    echecs: list[str]
    stats: dict[str, Any]
    candidats: list[Article]
    verdicts: dict[str, Verdict]
    pertinents: list[Article]
    groupes: list[list[Article]]
    affaires: list[Affaire]
    resume_global: str
    report_path: Path
    state_saved: bool


@dataclass
class Deps:
    cfg: dict
    llm: LLMClient
    sources: list[Source]
    base_dir: Path
    now: datetime | None = None
    save: bool = True            # False = ne pas mettre à jour state.json (tests, --since)
    since_override: datetime | None = None
    mode_hors_ligne: bool = False


def _collecte_echouee(state: RunState) -> bool:
    return not state.get("articles") and bool(state.get("echecs"))


def build_graph(deps: Deps):
    cfg = deps.cfg

    def n_load_state(state: RunState) -> RunState:
        now = deps.now or datetime.now(timezone.utc)
        if deps.since_override:
            f = Fenetre(deps.since_override, now, None, False, False)
        else:
            f = compute_window(load_last_run(deps.base_dir), now, cfg["window"]["max_days"])
        log.info("Fenêtre de recherche : %s -> %s%s", f.since.isoformat(timespec="minutes"),
                 f.now.isoformat(timespec="minutes"), " (plafonnée)" if f.plafonnee else "")
        return {"fenetre": f}

    def n_fetch(state: RunState) -> RunState:
        f = state["fenetre"]
        articles: list[Article] = []
        echecs: list[str] = []
        sans_date = 0
        for src in deps.sources:
            log.info("Collecte : %s", src.name)
            try:
                res = src.fetch(f.since, f.now)
                articles += res.articles
                echecs += res.echecs
                sans_date += res.sans_date
            except Exception as exc:
                log.exception("Source %s en échec", src.name)
                echecs.append(f"{src.name} : {type(exc).__name__}: {exc}")
        log.info("%d article(s) récupéré(s), %d source(s) en échec.", len(articles), len(echecs))
        return {"articles": articles, "echecs": echecs, "stats": {"sans_date": sans_date}}

    def n_prefilter(state: RunState) -> RunState:
        f = state["fenetre"]
        pc = cfg["prefilter"]
        res = prefilter(state["articles"], f.since, f.now, pc.get("keywords", []),
                        pc.get("use_keywords", True), pc.get("max_candidates", 400))
        log.info("Préfiltre : %s", res.stats)
        return {"candidats": res.candidates, "stats": {**state["stats"], **res.stats}}

    def n_classify(state: RunState) -> RunState:
        lc = cfg["llm"]
        log.info("Classification de %d article(s) par l'IA...", len(state["candidats"]))
        verdicts, non_classes = classify(state["candidats"], deps.llm,
                                         lc.get("batch_size", 15), lc.get("parallel_calls", 4))
        pertinents = [a for a in state["candidats"] if verdicts[a.id].pertinent]
        log.info("%d article(s) pertinent(s).", len(pertinents))
        return {"verdicts": verdicts, "pertinents": pertinents,
                "stats": {**state["stats"], "pertinents": len(pertinents), "non_classes": non_classes}}

    def n_cluster(state: RunState) -> RunState:
        groupes = cluster(state["pertinents"], deps.llm)
        log.info("%d affaire(s) distincte(s) après regroupement.", len(groupes))
        return {"groupes": groupes}

    def n_summarize(state: RunState) -> RunState:
        affaires, resume = build_affaires(state["groupes"], state["verdicts"], deps.llm)
        return {"affaires": affaires, "resume_global": resume}

    def n_write_report(state: RunState) -> RunState:
        f = state["fenetre"]
        verdicts = state.get("verdicts", {})
        exclus = []
        if cfg["report"].get("annexe_exclus", True):
            exclus = [(a, verdicts[a.id]) for a in state.get("candidats", [])
                      if a.id in verdicts and not verdicts[a.id].pertinent]
        data = ReportData(
            since=f.since, now=f.now, last_run=f.last_run, premier_lancement=f.premier_lancement,
            plafonnee=f.plafonnee, max_days=cfg["window"]["max_days"],
            affaires=state.get("affaires", []), resume_global=state.get("resume_global", ""),
            stats={**state.get("stats", {}), "pertinents": state.get("stats", {}).get("pertinents", 0)},
            echecs=state.get("echecs", []), exclus=exclus, mode_hors_ligne=deps.mode_hors_ligne,
            collecte_echouee=_collecte_echouee(state),
        )
        path = write_report(data, deps.base_dir, cfg["report"].get("timezone", "America/Toronto"),
                            cfg["report"].get("annexe_exclus_max", 60))
        log.info("Rapport écrit : %s", path)
        return {"report_path": path}

    def n_save_state(state: RunState) -> RunState:
        path = state.get("report_path")
        if not deps.save or not path or not Path(path).exists():
            return {"state_saved": False}
        # Si TOUTES les sources ont échoué, on ne fait pas avancer la date :
        # sinon on « perdrait » la période au prochain lancement.
        if _collecte_echouee(state):
            log.warning("Aucune source n'a répondu : date du dernier lancement NON mise à jour.")
            return {"state_saved": False}
        save_state(deps.base_dir, state["fenetre"].now, Path(path))
        return {"state_saved": True}

    g = StateGraph(RunState)
    for name, fn in [("load_state", n_load_state), ("fetch", n_fetch), ("prefilter", n_prefilter),
                     ("classify", n_classify), ("cluster", n_cluster), ("summarize", n_summarize),
                     ("write_report", n_write_report), ("save_state", n_save_state)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_state")
    g.add_edge("load_state", "fetch")
    g.add_edge("fetch", "prefilter")
    g.add_conditional_edges("prefilter", lambda s: "classify" if s["candidats"] else "write_report",
                            ["classify", "write_report"])
    g.add_conditional_edges("classify", lambda s: "cluster" if s["pertinents"] else "write_report",
                            ["cluster", "write_report"])
    g.add_edge("cluster", "summarize")
    g.add_edge("summarize", "write_report")
    g.add_edge("write_report", "save_state")
    g.add_edge("save_state", END)
    return g.compile()


def run(deps: Deps) -> RunState:
    return build_graph(deps).invoke({})
