"""Point d'entrée — Agent revue de presse « briefs de sécurité ».

Double-clic sur RevueSecurite.exe (ou : python main.py)

Options utiles :
  --verifier-flux   teste chaque flux RSS et quitte
  --fake-llm        démo hors ligne sans clé API (classement par mots-clés)
  --depuis AAAA-MM-JJ  force la date de début (n'écrit PAS state.json)
  --sans-pause      ne pas attendre « Entrée » à la fin
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


def _setup_logging(base_dir: Path) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # accents dans la console Windows
    except Exception:
        pass
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(base_dir / "revue_securite.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    for noisy in ("httpx", "httpcore", "urllib3", "anthropic", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def verifier_flux(cfg: dict) -> int:
    from revue.sources.base import http_fetch
    from revue.sources.google_news import build_url
    from revue.sources.rss import parse_feed

    ok = 0
    feeds = list(cfg.get("feeds", []))
    q = (cfg["google_news"].get("queries_fr") or ["police"])[0]
    feeds.append({"media": "Google News (test)", "url": build_url(q, 7, "fr")})
    for f in feeds:
        try:
            arts, sans_date = parse_feed(http_fetch(f["url"], 20), f["media"])
            dates = sorted(a.published for a in arts)
            span = f"{dates[0]:%d/%m} -> {dates[-1]:%d/%m}" if dates else "-"
            print(f"  OK     {f['media']:<22} {len(arts):3d} articles ({span})  {f['url']}")
            ok += 1
        except Exception as exc:
            print(f"  ÉCHEC  {f['media']:<22} {type(exc).__name__}: {str(exc)[:80]}  {f['url']}")
    print(f"\n{ok}/{len(feeds)} flux fonctionnels. Corrige ou retire les flux en échec dans config.yaml.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    from revue.state import app_dir

    parser = argparse.ArgumentParser(description="Revue de presse des briefs de sécurité")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--verifier-flux", action="store_true")
    parser.add_argument("--fake-llm", action="store_true")
    parser.add_argument("--depuis", type=str, default=None)
    parser.add_argument("--sans-pause", action="store_true")
    args = parser.parse_args(argv)

    base_dir = app_dir()
    _setup_logging(base_dir)
    log = logging.getLogger("main")
    code = 0
    try:
        from revue.config import load_config, resolve_api_key

        cfg = load_config(args.config or base_dir / "config.yaml")
        if args.verifier_flux:
            return verifier_flux(cfg)

        if args.fake_llm:
            from revue.fake_llm import FakeLLM
            llm = FakeLLM()
        else:
            key = resolve_api_key(cfg)
            if not key:
                log.error("Aucune clé API. Ouvre config.yaml et colle ta clé dans llm.api_key.")
                return 2
            from revue.llm import LangChainLLM
            llm = LangChainLLM(cfg["llm"], key)

        from revue.graph import Deps, run
        from revue.sources.factory import build_sources

        since = None
        if args.depuis:
            since = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        deps = Deps(cfg=cfg, llm=llm, sources=build_sources(cfg), base_dir=base_dir,
                    save=since is None and not args.fake_llm, since_override=since,
                    mode_hors_ligne=args.fake_llm)
        result = run(deps)

        n = len(result.get("affaires", []))
        print()
        if not result.get("articles") and result.get("echecs"):
            print(f"==> ÉCHEC DE LA COLLECTE : aucune source n'a répondu. Vérifie internet. "
                  f"Rapport : {result['report_path']}")
        elif n:
            print(f"==> {n} affaire(s) trouvée(s). Rapport : {result['report_path']}")
        else:
            print(f"==> Aucun nouvel article trouvé depuis le {result['fenetre'].since:%d/%m/%Y}. "
                  f"Rapport : {result['report_path']}")
        if not result.get("state_saved"):
            print("    (date du dernier lancement non mise à jour)")
    except Exception:
        log.exception("Erreur fatale — aucun état sauvegardé, le prochain lancement reprendra la même période.")
        code = 1
    finally:
        if not args.sans_pause and sys.stdin and sys.stdin.isatty():
            try:
                input("\nAppuie sur Entrée pour fermer...")
            except EOFError:
                pass
    return code


if __name__ == "__main__":
    sys.exit(main())
