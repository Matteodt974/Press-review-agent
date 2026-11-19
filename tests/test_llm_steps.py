from datetime import timedelta

from conftest import NOW
from revue.classifier import classify
from revue.clustering import sanitize_groups
from revue.models import Article, Verdict, VerdictBatch
from revue.summarizer import build_affaires


def art(i, title, media="La Presse", days=1):
    return Article(id=f"id{i}", title=title, url=f"https://ex/{i}", media=media,
                   published=NOW - timedelta(days=days))


class LLMOubliCertains:
    """Simule un LLM qui « oublie » un article et invente un identifiant."""
    def __init__(self):
        self.calls = 0

    def structured(self, role, schema, system, user):
        self.calls += 1
        assert schema is VerdictBatch
        ids = [l.split("]")[0][1:] for l in user.splitlines() if l.startswith("[")]
        if len(ids) > 1:
            ids = ids[1:]  # oublie le premier au 1er passage
        vs = [Verdict(id=i, pertinent=True, critere=1, portee="Québec", stade="allégation",
                      importance=9, justification="x") for i in ids]
        vs.append(Verdict(id="zzz", pertinent=True, critere=1, portee="Québec", stade="autre",
                          importance=3, justification="inventé"))
        return VerdictBatch(verdicts=vs)


def test_classify_reessaie_les_oublies_et_borne_importance():
    arts = [art(i, f"Employé accusé {i}") for i in range(3)]
    verdicts, non_classes = classify(arts, LLMOubliCertains(), batch_size=10, parallel=1)
    assert set(verdicts) == {a.id for a in arts}
    assert non_classes == 0
    assert all(v.importance == 5 for v in verdicts.values())


def test_sanitize_groups_chaque_id_une_seule_fois():
    groups = sanitize_groups([["a0", "a1"], ["a1", "a9"], []], ["a0", "a1", "a2"])
    assert groups == [["a0", "a1"], ["a2"]]


def test_tri_importance_puis_quebec():
    from revue.fake_llm import FakeLLM
    a1, a2, a3 = art(1, "Affaire Canada imp 5"), art(2, "Affaire Québec imp 4"), art(3, "Affaire Canada imp 4")
    v = {
        a1.id: Verdict(id="", pertinent=True, critere=1, portee="Canada", stade="accusation", importance=5, justification=""),
        a2.id: Verdict(id="", pertinent=True, critere=1, portee="Québec", stade="allégation", importance=4, justification=""),
        a3.id: Verdict(id="", pertinent=True, critere=1, portee="Canada", stade="allégation", importance=4, justification=""),
    }
    affaires, _ = build_affaires([[a3], [a2], [a1]], v, FakeLLM())
    assert [a.portee for a in affaires] == ["Canada", "Québec", "Canada"]
    assert affaires[0].importance == 5


def test_fusion_stade_le_plus_avance_et_portee_quebec():
    from revue.fake_llm import FakeLLM
    a1, a2 = art(1, "X congédié", media="CBC"), art(2, "X accusé", media="La Presse")
    v = {
        a1.id: Verdict(id="", pertinent=True, critere=15, portee="Canada", stade="congédiement", importance=3, justification=""),
        a2.id: Verdict(id="", pertinent=True, critere=1, portee="Québec", stade="accusation", importance=4, justification=""),
    }
    (aff,), _ = build_affaires([[a1, a2]], v, FakeLLM())
    assert aff.stade == "accusation" and aff.portee == "Québec"
    assert aff.medias == ["CBC", "La Presse"] and aff.criteres == [1, 15]
