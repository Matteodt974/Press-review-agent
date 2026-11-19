import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def fixture_fetcher(mapping: dict[str, str]):
    """Fetcher qui renvoie un fichier de fixture selon un fragment d'URL."""
    def fetch(url: str, timeout: float) -> bytes:
        for frag, fname in mapping.items():
            if frag in url:
                return (FIX / fname).read_bytes()
        raise ConnectionError(f"URL inconnue en test : {url}")
    return fetch


@pytest.fixture
def cfg():
    from revue.config import load_config
    return load_config(ROOT / "config.yaml")
