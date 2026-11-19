from datetime import timedelta

from conftest import FIX, NOW, fixture_fetcher
from revue.prefilter import normalize_url, prefilter
from revue.sources.google_news import GoogleNewsSource, build_url
from revue.sources.rss import RSSSource, parse_feed


def test_parse_feed_ignore_articles_sans_date():
    arts, sans_date = parse_feed((FIX / "lapresse.xml").read_bytes(), "La Presse")
    assert len(arts) == 5 and sans_date == 1
    assert "<p>" not in arts[0].summary


def test_presse_canadienne_detectee():
    arts, _ = parse_feed((FIX / "tva.xml").read_bytes(), "TVA Nouvelles")
    assert arts[0].media == "TVA Nouvelles (La Presse Canadienne)"


def test_source_rss_echec_isole():
    src = RSSSource([{"media": "La Presse", "url": "https://x/lapresse"},
                     {"media": "Mort", "url": "https://x/inexistant"}],
                    fetcher=fixture_fetcher({"lapresse": "lapresse.xml"}))
    res = src.fetch(NOW - timedelta(days=30), NOW)
    assert len(res.articles) == 5
    assert len(res.echecs) == 1 and "Mort" in res.echecs[0]


def test_google_news_filtre_medias_et_nettoie_titre(cfg):
    gcfg = {**cfg["google_news"], "queries_fr": ["q"], "queries_en": []}
    src = GoogleNewsSource(gcfg, fetcher=fixture_fetcher({"news.google.com": "google_news.xml"}))
    res = src.fetch(NOW - timedelta(days=10), NOW)
    medias = sorted(a.media for a in res.articles)
    assert medias == ["La Presse", "Radio-Canada", "The Canadian Press"]  # blog exclu
    assert all(not a.title.endswith(" - La Presse") for a in res.articles)


def test_build_url_contient_when():
    assert "when%3A7d" in build_url("policier accusé", 7, "fr")


def test_normalize_url():
    assert normalize_url("https://www.lapresse.ca/a/b.php?utm_source=rss#x") == \
        normalize_url("https://lapresse.ca/a/b.php/")


def test_prefilter_fenetre_doublons_mots_cles(cfg):
    lp, _ = parse_feed((FIX / "lapresse.xml").read_bytes(), "La Presse")
    lp_dup, _ = parse_feed((FIX / "lapresse.xml").read_bytes(), "La Presse")
    res = prefilter(lp + lp_dup, NOW - timedelta(days=30), NOW, cfg["prefilter"]["keywords"])
    titres = [a.title for a in res.candidates]
    assert res.stats["dans_fenetre"] == 8      # article de septembre exclu, x2
    assert res.stats["uniques"] == 4          # doublons exacts retirés
    assert not any("Canadien l'emporte" in t for t in titres)  # hockey : pas de mot-clé
    assert len(titres) == 3


def test_prefilter_prefere_lien_direct_rss():
    from revue.models import Article
    rss = Article(id="1", title="Titre X", url="https://lapresse.ca/x", media="La Presse",
                  published=NOW - timedelta(days=1), source="rss")
    gn = rss.model_copy(update={"id": "2", "url": "https://news.google.com/a", "source": "google_news",
                                "published": NOW - timedelta(days=2)})
    res = prefilter([gn, rss], NOW - timedelta(days=5), NOW, [], use_keywords=False)
    assert [a.source for a in res.candidates] == ["rss"]


def test_prefilter_plafond_cout():
    from revue.models import Article
    arts = [Article(id=str(i), title=f"Employé accusé {i}", url=f"https://a/{i}", media="M",
                    published=NOW - timedelta(hours=i)) for i in range(10)]
    res = prefilter(arts, NOW - timedelta(days=5), NOW, ["employé"], max_candidates=4)
    assert res.stats["tronques"] == 6 and len(res.candidates) == 4
