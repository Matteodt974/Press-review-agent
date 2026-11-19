"""Évaluation de l'agent sur un jeu d'articles étiquetés.

Usage :
  python -m evaluation.run_eval                 # vrai LLM (clé dans config.yaml)
  python -m evaluation.run_eval --fake          # base de comparaison par mots-clés (gratuit)
  python -m evaluation.run_eval --min-rappel 0.9   # code de sortie 1 si le rappel est sous 90 %

Mesures :
- Classification (le plus important) : rappel, précision, F1, exactitude.
  Le RAPPEL compte le plus : une affaire ratée est pire qu'une fausse alerte.
- Portée Québec/Canada : exactitude sur les vrais positifs.
- Regroupement (dédoublonnage) : précision et rappel par paires.
Résultats écrits dans evaluation/resultats/ (Markdown + JSON).

Pour améliorer le jeu : ajoute des lignes dans dataset.jsonl à partir de
VRAIS articles (surtout ceux que l'agent a ratés ou mal classés).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from revue.classifier import classify  # noqa: E402
from revue.clustering import cluster  # noqa: E402
from revue.config import load_config, resolve_api_key  # noqa: E402
from revue.models import Article  # noqa: E402

HERE = Path(__file__).resolve().parent


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def to_article(row: dict, now: datetime) -> Article:
    return Article(id=row["id"], title=row["title"], summary=row.get("summary", ""),
                   url=f"https://exemple.invalid/{row['id']}", media=row.get("media", "?"),
                   published=now, source="test")


def ratio(a: int, b: int) -> float:
    return a / b if b else 0.0


def eval_classification(rows: list[dict], llm, cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    arts = [to_article(r, now) for r in rows]
    verdicts, non_classes = classify(arts, llm, cfg["llm"]["batch_size"], cfg["llm"]["parallel_calls"])
    tp = fp = fn = tn = 0
    portee_ok = portee_n = 0
    erreurs = []
    par_origine: dict[str, list[int]] = {}
    for r in rows:
        v = verdicts[r["id"]]
        attendu, predit = r["attendu_pertinent"], v.pertinent
        tp += attendu and predit
        fp += (not attendu) and predit
        fn += attendu and not predit
        tn += (not attendu) and not predit
        ok = attendu == predit
        par_origine.setdefault(r["origine"], [0, 0])
        par_origine[r["origine"]][0] += ok
        par_origine[r["origine"]][1] += 1
        if attendu and predit:
            portee_n += 1
            portee_ok += v.portee == r["attendu_portee"]
            if v.portee != r["attendu_portee"]:
                erreurs.append({"id": r["id"], "type": "portée", "title": r["title"],
                                "attendu": r["attendu_portee"], "obtenu": v.portee,
                                "justification": v.justification})
        if not ok:
            erreurs.append({"id": r["id"], "type": "faux négatif (RATÉ)" if attendu else "faux positif",
                            "title": r["title"], "attendu": f"critère {r['attendu_critere']}",
                            "obtenu": f"critère {v.critere}", "justification": v.justification,
                            "origine": r["origine"]})
    p, rc = ratio(tp, tp + fp), ratio(tp, tp + fn)
    return {
        "n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": p, "rappel": rc, "f1": ratio(2 * p * rc, p + rc),
        "exactitude": ratio(tp + tn, len(rows)),
        "exactitude_portee": ratio(portee_ok, portee_n),
        "non_classes": non_classes,
        "par_origine": {k: f"{a}/{b}" for k, (a, b) in par_origine.items()},
        "erreurs": erreurs,
    }


def eval_clustering(cases: list[dict], llm) -> dict:
    now = datetime.now(timezone.utc)
    tp = fp = fn = 0
    details = []
    for case in cases:
        arts = [to_article(a, now) for a in case["articles"]]
        attendu = {a["id"]: a["groupe"] for a in case["articles"]}
        groupes = cluster(arts, llm)
        obtenu = {a.id: gi for gi, g in enumerate(groupes) for a in g}
        ctp = cfp = cfn = 0
        for x, y in itertools.combinations(attendu, 2):
            same_exp = attendu[x] == attendu[y]
            same_got = obtenu[x] == obtenu[y]
            ctp += same_exp and same_got
            cfp += (not same_exp) and same_got
            cfn += same_exp and not same_got
        tp, fp, fn = tp + ctp, fp + cfp, fn + cfn
        details.append({"cas": case["cas"], "groupes_obtenus": [[a.id for a in g] for g in groupes],
                        "paires_fusionnees_a_tort": cfp, "paires_separees_a_tort": cfn})
    return {"precision_paires": ratio(tp, tp + fp), "rappel_paires": ratio(tp, tp + fn), "details": details}


def to_markdown(res: dict, mode: str) -> str:
    c, k = res["classification"], res["regroupement"]
    lines = [
        f"# Évaluation — {res['date']} — mode : {mode}", "",
        "## Classification (pertinent / non pertinent)", "",
        "| Mesure | Valeur |", "|---|---|",
        f"| **Rappel** (affaires trouvées / affaires réelles) | **{c['rappel']:.0%}** |",
        f"| Précision (vraies alertes / alertes) | {c['precision']:.0%} |",
        f"| F1 | {c['f1']:.2f} |",
        f"| Exactitude globale | {c['exactitude']:.0%} ({c['n']} cas) |",
        f"| Exactitude Québec/Canada | {c['exactitude_portee']:.0%} |",
        f"| Non classés | {c['non_classes']} |", "",
        f"Matrice : VP={c['tp']}  FP={c['fp']}  FN={c['fn']}  VN={c['tn']}", "",
        f"Par origine des cas : {c['par_origine']}", "",
        "## Erreurs à examiner", "",
    ]
    if not c["erreurs"]:
        lines.append("Aucune.")
    for e in c["erreurs"]:
        lines.append(f"- **{e['type']}** [{e['id']}] {e['title']} — attendu {e['attendu']}, "
                     f"obtenu {e['obtenu']}. _{e['justification']}_")
    lines += ["", "## Regroupement des doublons", "",
              f"Précision par paires : {k['precision_paires']:.0%} — rappel par paires : {k['rappel_paires']:.0%}", ""]
    for d in k["details"]:
        lines.append(f"- {d['cas']} : {d['groupes_obtenus']} (fusions à tort : "
                     f"{d['paires_fusionnees_a_tort']}, séparations à tort : {d['paires_separees_a_tort']})")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="base de comparaison par mots-clés, sans LLM")
    ap.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    ap.add_argument("--dataset", type=Path, default=HERE / "dataset.jsonl")
    ap.add_argument("--clustering", type=Path, default=HERE / "clustering_cases.jsonl")
    ap.add_argument("--min-rappel", type=float, default=None)
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.fake:
        from revue.fake_llm import FakeLLM
        llm, mode = FakeLLM(), "FakeLLM (mots-clés)"
    else:
        key = resolve_api_key(cfg)
        if not key:
            print("Aucune clé API dans config.yaml (ou utilise --fake).")
            return 2
        from revue.llm import LangChainLLM
        llm = LangChainLLM(cfg["llm"], key)
        mode = f"{cfg['llm']['provider']} : {cfg['llm']['model_classify']} / {cfg['llm']['model_write']}"

    res = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mode": mode,
        "classification": eval_classification(load_jsonl(args.dataset), llm, cfg),
        "regroupement": eval_clustering(load_jsonl(args.clustering), llm),
    }
    out_dir = HERE / "resultats"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + ("_fake" if args.fake else "")
    md = to_markdown(res, mode)
    (out_dir / f"eval_{stamp}.md").write_text(md, encoding="utf-8")
    (out_dir / f"eval_{stamp}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    print(f"Résultats : {out_dir / f'eval_{stamp}.md'}")
    if args.min_rappel is not None and res["classification"]["rappel"] < args.min_rappel:
        print(f"ÉCHEC : rappel {res['classification']['rappel']:.0%} < seuil {args.min_rappel:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
