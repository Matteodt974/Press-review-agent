"""Modèles de données (Pydantic)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Portee = Literal["Québec", "Canada", "Hors Canada"]
Stade = Literal[
    "allégation", "enquête", "congédiement", "accusation",
    "procès", "condamnation", "rapport/réforme", "autre",
]

# Ordre de « gravité » des stades (pour choisir le stade le plus avancé d'une affaire)
STADE_ORDRE = {
    "autre": 0, "rapport/réforme": 1, "allégation": 2, "enquête": 3,
    "congédiement": 4, "accusation": 5, "procès": 6, "condamnation": 7,
}


class Article(BaseModel):
    id: str
    title: str
    summary: str = ""
    url: str
    media: str
    published: datetime
    source: str = "rss"  # "rss" | "google_news" | "test"


# ---------- Sorties structurées du LLM ----------

class Verdict(BaseModel):
    id: str = Field(description="Identifiant de l'article, recopié exactement (ex. a12)")
    pertinent: bool = Field(description="true si l'article est un brief de sécurité selon les critères")
    critere: int = Field(description="Numéro du critère INCLURE ou EXCLURE appliqué ; 0 si aucun")
    portee: Portee = Field(description="Québec, Canada (hors Québec ou fédéral) ou Hors Canada")
    stade: Stade = Field(description="Stade de l'affaire")
    importance: int = Field(description="Importance de 1 (mineure) à 5 (majeure)")
    justification: str = Field(description="Une phrase courte en français")


class VerdictBatch(BaseModel):
    verdicts: list[Verdict]


class Groupe(BaseModel):
    ids: list[str] = Field(description="Identifiants des articles qui décrivent la même affaire")


class Clustering(BaseModel):
    groupes: list[Groupe]


class FicheAffaire(BaseModel):
    index: int = Field(description="Numéro de l'affaire, recopié exactement")
    titre: str = Field(description="Titre factuel en français, 15 mots maximum")
    resume: str = Field(description="Résumé en français, 2 à 3 phrases")


class Redaction(BaseModel):
    resume_global: str = Field(description="Synthèse de la période en 3 à 5 phrases, en français")
    fiches: list[FicheAffaire]


# ---------- Résultat final ----------

class Affaire(BaseModel):
    titre: str
    resume: str
    portee: Portee
    stade: Stade
    importance: int
    criteres: list[int]
    articles: list[Article]

    @property
    def medias(self) -> list[str]:
        vus: list[str] = []
        for a in self.articles:
            if a.media not in vus:
                vus.append(a.media)
        return vus

    @property
    def derniere_date(self) -> datetime:
        return max(a.published for a in self.articles)
