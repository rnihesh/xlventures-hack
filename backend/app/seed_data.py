"""Seed corpus loader shared by retrieval and memory slices.

Resolves the ``backend/seeds/<domain>/`` JSON files via a package-relative path
(``app/seed_data.py`` -> ``../seeds``) with an importlib.resources-style
fallback, so it works whether the backend is run from source or installed.
Results are cached in-process.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DEFAULT_DOMAIN = "customer_success"


def _seeds_root() -> Path:
    """Locate the seeds directory robustly across run layouts."""
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "seeds",  # backend/seeds (source layout)
        here.parent / "seeds",  # app/seeds (if bundled into the package)
        Path.cwd() / "backend" / "seeds",  # repo root cwd
        Path.cwd() / "seeds",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    # Default to the source layout even if missing; loaders handle absence.
    return candidates[0]


def _read_json(domain: str, name: str) -> list[dict]:
    path = _seeds_root() / domain / name
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        # Allow {"accounts": [...]} or {"documents": [...]} wrappers.
        for value in data.values():
            if isinstance(value, list):
                return value
        return []
    return data if isinstance(data, list) else []


@lru_cache(maxsize=8)
def load_accounts(domain: str = _DEFAULT_DOMAIN) -> list[dict]:
    """Return the seeded account records for ``domain``."""
    return _read_json(domain, "accounts.json")


@lru_cache(maxsize=8)
def load_documents(domain: str = _DEFAULT_DOMAIN) -> list[dict]:
    """Return the seeded source documents for ``domain``."""
    return _read_json(domain, "documents.json")


def get_account(account_id: str, domain: str = _DEFAULT_DOMAIN) -> dict | None:
    """Convenience lookup of a single account by id."""
    for acc in load_accounts(domain):
        if acc.get("account_id") == account_id:
            return acc
    return None
