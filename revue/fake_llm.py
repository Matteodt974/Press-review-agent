"""LLM factice, sans réseau, à base de mots-clés.

Sert à :
- faire tourner les tests et une démo hors ligne (python main.py --fake-llm) ;
- donner une BASE DE COMPARAISON dans l'évaluation (« le vrai LLM fait-il mieux
  qu'une simple règle de mots-clés ? »).
Ce n'est PAS un classificateur de qualité production.
"""
from __future__ import annotations

import re

from .models import Clustering, FicheAffaire, Groupe, Redaction, Verdict, VerdictBatch
from .prefilter import norm_text

LINE_RE = re.compile(r"^\[(\w+)\] (.*?) \| (.*?) \| (.*)$", re.M)
AFF_RE = re.compile(r"^### Affaire (\d+)", re.M)

# (critère, motifs « acteur en poste de confiance », motifs « problème »)
REGLES = [
    (1, r"employe|ex employe|ancien employe|employee|worker", r"consult|donnees|dossiers|records|personal information|vend|accessed"),
    (2, r"policier|policiere|police officer|officer|agent de la paix", r"accuse|charged|crime organise|organized crime|hells|motard|abus de confiance|breach of trust"),
    (3, r"candidat|elu|conseiller|maire|candidate|councillor", r"casier|hells|motard|criminal record|antecedents|liens"),
    (4, r"aeroport|airport|douane|cbsa|port de", r"drogue|cocaine|importation|smuggling|drug"),
    (5, r"fonctionnaire|public servant|ingenieur|employe", r"ingerence|espion|interference|espionage"),
    (6, r"ecole|cpe|garderie|school|daycare", r"intrus|intrusion|intruder|entre sans"),
    (8, r"enseignant|entraineur|teacher|coach|admis|accepte", r"antecedents|verification|background|meurtr|condamne|casier"),
    (11, r"verificateur general|auditor general|ombudsman|rapport", r"verification|antecedents|background|filtrage|habilitation"),
    (12, r"loi|reglement|regulation|bill|projet de loi", r"habilitation|security clearance|verification des antecedents|cote de securite"),
    (13, r"faux medecin|fausse infirmiere|fake nurse|fake doctor|impostor|se faisait passer", r"."),
    (14, r"libere par erreur|released in error|mistakenly released", r"."),
    (15, r"employe|employee", r"congedie|fired|fraude|fraud"),
]
QUEBEC_RE = re.compile(
    r"quebec|montreal|laval|longueuil|gatineau|sherbrooke|estrie|saguenay|trois rivieres|"
    r"saaq|revenu quebec|desjardins|hydro quebec|cisss|ciusss|dge"
)
HORS_CANADA_RE = re.compile(r"france|paris|etats unis|united states|london|londres")


def classer(title: str, summary: str) -> tuple[bool, int]:
    t = norm_text(f"{title} {summary}")
    for crit, acteur, probleme in REGLES:
        if re.search(acteur, t) and re.search(probleme, t):
            return True, crit
    return False, 0


def portee(title: str, summary: str) -> str:
    t = norm_text(f"{title} {summary}") + " "
    if HORS_CANADA_RE.search(t):
        return "Hors Canada"
    return "Québec" if QUEBEC_RE.search(t) else "Canada"


def _tokens(title: str) -> set[str]:
    return {w for w in norm_text(title).split() if len(w) > 3}


class FakeLLM:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def structured(self, role, schema, system, user):
        self.calls += 1
        if self.fail:
            raise RuntimeError("FakeLLM : échec simulé")
        items = LINE_RE.findall(user)
        if schema is VerdictBatch:
            verdicts = []
            for sid, media, title, summary in items:
                ok, crit = classer(title, summary)
                por = portee(title, summary)
                if por == "Hors Canada":
                    ok, crit = False, 19
                verdicts.append(Verdict(
                    id=sid, pertinent=ok, critere=crit, portee=por,
                    stade="accusation" if re.search(r"accus|charged", norm_text(title + summary)) else "allégation",
                    importance=4 if por == "Québec" else 3,
                    justification="Règle par mots-clés (FakeLLM).",
                ))
            return VerdictBatch(verdicts=verdicts)
        if schema is Clustering:
            groupes: list[tuple[set[str], list[str]]] = []
            for sid, _m, title, _s in items:
                tok = _tokens(title)
                for gtok, ids in groupes:
                    if tok and len(tok & gtok) / len(tok | gtok) >= 0.4:
                        ids.append(sid)
                        gtok |= tok
                        break
                else:
                    groupes.append((tok, [sid]))
            return Clustering(groupes=[Groupe(ids=ids) for _t, ids in groupes])
        if schema is Redaction:
            n = len(AFF_RE.findall(user))
            fiches = []
            for i in range(1, n + 1):
                bloc = user.split(f"### Affaire {i}\n", 1)[1].split("### Affaire", 1)[0]
                first = LINE_RE.search(bloc)
                titre = first.group(3) if first else f"Affaire {i}"
                resume = (first.group(4) if first else "") or titre
                fiches.append(FicheAffaire(index=i, titre=titre[:120], resume=f"[Résumé hors ligne] {resume[:300]}"))
            return Redaction(resume_global=f"[Mode hors ligne / FakeLLM] {n} affaire(s) détectée(s) par règles de mots-clés.",
                             fiches=fiches)
        raise TypeError(f"Schéma non géré par FakeLLM : {schema}")
