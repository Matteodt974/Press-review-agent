from datetime import timedelta

from conftest import NOW
from revue.state import compute_window, load_last_run, save_state


def test_premier_lancement_plafonne_a_30_jours():
    f = compute_window(None, NOW, 30)
    assert f.premier_lancement and f.plafonnee
    assert f.since == NOW - timedelta(days=30)


def test_dernier_lancement_recent():
    last = NOW - timedelta(days=3)
    f = compute_window(last, NOW, 30)
    assert f.since == last and not f.plafonnee and not f.premier_lancement


def test_dernier_lancement_trop_ancien_est_plafonne():
    f = compute_window(NOW - timedelta(days=90), NOW, 30)
    assert f.since == NOW - timedelta(days=30) and f.plafonnee


def test_aller_retour_state(tmp_path):
    save_state(tmp_path, NOW, tmp_path / "rapport.docx")
    assert load_last_run(tmp_path) == NOW


def test_state_corrompu_traite_comme_premier_lancement(tmp_path):
    (tmp_path / "state.json").write_text("{pas du json", encoding="utf-8")
    assert load_last_run(tmp_path) is None
