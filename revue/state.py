"""Mémoire du dernier lancement (state.json) et calcul de la fenêtre temporelle."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)
STATE_FILE = "state.json"


def app_dir() -> Path:
    """Dossier de l'exécutable (PyInstaller) ou du projet (python main.py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def load_last_run(base_dir: Path) -> datetime | None:
    path = base_dir / STATE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        dt = datetime.fromisoformat(data["last_run"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as exc:  # fichier corrompu -> on repart comme un 1er lancement
        log.warning("state.json illisible (%s) : traité comme un premier lancement.", exc)
        return None


@dataclass
class Fenetre:
    since: datetime
    now: datetime
    last_run: datetime | None
    premier_lancement: bool
    plafonnee: bool  # True si la fenêtre a été coupée au plafond de N jours


def compute_window(last_run: datetime | None, now: datetime, max_days: int) -> Fenetre:
    plancher = now - timedelta(days=max_days)
    if last_run is None:
        return Fenetre(plancher, now, None, True, True)
    if last_run < plancher:
        return Fenetre(plancher, now, last_run, False, True)
    return Fenetre(last_run, now, last_run, False, False)


def save_state(base_dir: Path, run_started: datetime, report_path: Path) -> None:
    """Écriture atomique : on n'écrase jamais un état valide par un fichier à moitié écrit."""
    path = base_dir / STATE_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"last_run": run_started.astimezone(timezone.utc).isoformat(),
             "last_report": report_path.name},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)
