"""Chargement de la configuration (config.yaml)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_KEYS = {"", "COLLE_TA_CLE_ICI", "sk-..."}

DEFAULTS: dict[str, Any] = {
    "llm": {
        "provider": "anthropic",
        "api_key": "",
        "model_classify": "claude-haiku-5-5",
        "model_write": "claude-opus-5-5",
        "effort_classify": "low",
        "effort_write": "medium",
        "batch_size": 15,
        "parallel_calls": 4,
    },
    "window": {"max_days": 30},
    "prefilter": {"use_keywords": True, "max_candidates": 400, "keywords": []},
    "sources": {"rss": True, "google_news": True, "timeout_seconds": 20},
    "feeds": [],
    "google_news": {"domains": {}, "source_names": [], "queries_fr": [], "queries_en": []},
    "report": {"annexe_exclus": True, "annexe_exclus_max": 60, "timezone": "America/Toronto"},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _merge(DEFAULTS, data)


def resolve_api_key(cfg: dict) -> str | None:
    """Clé du config.yaml, sinon variable d'environnement du fournisseur."""
    key = (cfg["llm"].get("api_key") or "").strip()
    if key and key not in PLACEHOLDER_KEYS:
        return key
    env = "OPENAI_API_KEY" if cfg["llm"]["provider"] == "openai" else "ANTHROPIC_API_KEY"
    return os.environ.get(env) or None
