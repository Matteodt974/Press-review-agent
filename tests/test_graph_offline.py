"""Bout en bout, sans réseau : sources figées + FakeLLM."""
import json
from datetime import timedelta

import docx
import pytest

from conftest import NOW, fixture_fetcher
from revue.fake_llm import FakeLLM
from revue.graph import Deps, run
from revue.sources.google_news import GoogleNewsSource
from revue.sources.rss import RSSSource

MAPPING = {"lapresse": "lapresse.xml", "tva": "tva.xml", "news.google.com": "google_news.xml"}


def sources(cfg, mapping=MAPPING):
    f = fixture_fetcher(mapping)
    feeds = [{"media": "La Presse", "url": "https://x/lapresse"},
             {"media": "TVA Nouvelles", "url": "https://x/tva"}]
    g = {**cfg["google_news"], "queries_fr": ["q"], "queries_en": []}
    return [RSSSource(feeds, fetcher=f), GoogleNewsSource(g, fetcher=f)]


def texte(path):
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def liens(path):
    d = docx.Document(path)
    return [r.target_ref for r in d.part.rels.values() if "hyperlink" in r.reltype]


def test_bout_en_bout_puis_rien_de_nouveau(cfg, tmp_path):
    out = run(Deps(cfg=cfg, llm=FakeLLM(), sources=sources(cfg), base_dir=tmp_path, now=NOW))
    assert out["state_saved"]
    titres = [a.titre for a in out["affaires"]]
    # Affaire de l'assureur (La Presse + TVA) regroupée en UNE affaire avec 2 médias
    assureur = [a for a in out["affaires"] if "assureur" in a.titre.lower()]
    assert len(assureur) == 1 and len(assureur[0].medias) == 2
    # Affaire télécom : doublon RSS / Google News fusionné (lien direct conservé)
    telecom = [a for a in out["affaires"] if "télécommunications" in a.titre]
    assert len(telecom) == 1 and telecom[0].articles[0].url.startswith("https://www.lapresse.ca")
    # Cyberattaque externe exclue, hockey exclu
    assert not any("Cyberattaque" in t or "Canadien" in t for t in titres)

    txt = texte(out["report_path"])
    assert "Période couverte" in txt and "Québec" in txt
    assert "https://www.tvanouvelles.ca/2026/11/14/assureur-ottawa" in liens(out["report_path"])
    assert "Articles écartés" in txt  # annexe de validation
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["last_run"].startswith("2026-11-16")

    # 2e lancement 1 h plus tard : rien de nouveau
    out2 = run(Deps(cfg=cfg, llm=FakeLLM(), sources=sources(cfg), base_dir=tmp_path,
                    now=NOW + timedelta(hours=1)))
    assert not out2.get("affaires")
    assert "Aucun nouvel article trouvé depuis le 16/11/2026" in texte(out2["report_path"])
    assert out2["state_saved"]


def test_echec_llm_ne_sauve_pas_l_etat(cfg, tmp_path):
    with pytest.raises(RuntimeError):
        run(Deps(cfg=cfg, llm=FakeLLM(fail=True), sources=sources(cfg), base_dir=tmp_path, now=NOW))
    assert not (tmp_path / "state.json").exists()


def test_toutes_sources_en_echec_ne_fait_pas_avancer_la_date(cfg, tmp_path):
    out = run(Deps(cfg=cfg, llm=FakeLLM(), sources=sources(cfg, mapping={}), base_dir=tmp_path, now=NOW))
    assert out["report_path"].exists()
    assert not out["state_saved"] and not (tmp_path / "state.json").exists()
    txt = texte(out["report_path"])
    assert "Sources en échec" in txt and "ÉCHEC DE LA COLLECTE" in txt
    assert "Aucun nouvel article" not in txt


def test_since_override_n_ecrit_pas_l_etat(cfg, tmp_path):
    out = run(Deps(cfg=cfg, llm=FakeLLM(), sources=sources(cfg), base_dir=tmp_path, now=NOW,
                   save=False, since_override=NOW - timedelta(days=3)))
    assert not out["state_saved"]
