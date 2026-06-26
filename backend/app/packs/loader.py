"""Domain Pack loader.

``load_pack`` reads ``domain_packs/<domain>.yaml`` and validates it into a
:class:`~app.packs.schema.DomainPack`. ``list_packs`` scans the pack folder and
returns a compact summary for each pack (used by the /domains endpoint).

The pack directory is resolved robustly so the backend works whether it is run
from the repo root, from ``backend/``, or inside a container. An override is
available through the ``DOMAIN_PACKS_DIR`` environment variable.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.packs.schema import DomainPack


def _candidate_dirs() -> List[Path]:
    """Ordered candidate locations for the ``domain_packs`` directory."""

    candidates: List[Path] = []

    env_dir = os.environ.get("DOMAIN_PACKS_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    # This file lives at <repo>/backend/app/packs/loader.py
    here = Path(__file__).resolve()
    # parents[3] -> <repo>/backend ; parents[4] -> <repo>
    backend_dir = here.parents[2]  # <repo>/backend/app -> .. -> backend
    repo_dir = here.parents[3]

    candidates.append(repo_dir / "domain_packs")
    candidates.append(backend_dir / "domain_packs")
    candidates.append(Path.cwd() / "domain_packs")
    candidates.append(Path.cwd().parent / "domain_packs")

    return candidates


def packs_dir() -> Path:
    """Return the first existing ``domain_packs`` directory.

    Falls back to the repo-root candidate (which may not exist yet) so callers
    get a deterministic path for error messages.
    """

    for candidate in _candidate_dirs():
        if candidate.is_dir():
            return candidate
    return _candidate_dirs()[-3]


def _minimal_pack(domain: str) -> DomainPack:
    """A safe, generic pack so the engine still runs if a YAML is missing."""

    return DomainPack(
        domain=domain,
        display_name=domain.replace("_", " ").title(),
        decision_points={
            "general_review": {
                "label": "General review",
                "description": "A generic decision point used when no pack is found.",
                "trigger_signals": [],
                "primary_kpi": "outcome_score",
                "default_persona": "operator",
            }
        },
        actions=[
            {
                "key": "monitor_no_action",
                "title": "Monitor and hold",
                "description": "Keep the entity on a watch list with re-evaluation thresholds.",
                "eligibility": "Use when signals are weak or contradicting.",
            }
        ],
        kpis=[
            {
                "key": "outcome_score",
                "label": "Outcome Score",
                "description": "Generic composite outcome metric.",
                "unit": "index_0_100",
                "target": ">= 70",
            }
        ],
        planner_prompt=(
            "You are a generic decision planner. Turn signals into a single, "
            "explainable next best action grounded in retrieved evidence."
        ),
    )


@lru_cache(maxsize=32)
def load_pack(domain: str) -> DomainPack:
    """Load and validate a domain pack by key.

    Returns a minimal generic pack if the YAML file cannot be found, so the
    walking skeleton never crashes on a missing pack.
    """

    path = packs_dir() / f"{domain}.yaml"
    if not path.is_file():
        # Try a .yml extension before giving up.
        alt = packs_dir() / f"{domain}.yml"
        path = alt if alt.is_file() else path

    if not path.is_file():
        return _minimal_pack(domain)

    with path.open("r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    raw.setdefault("domain", domain)
    return DomainPack.model_validate(raw)


def list_packs() -> List[Dict[str, Any]]:
    """Scan the pack folder and return a compact summary per pack."""

    directory = packs_dir()
    summaries: List[Dict[str, Any]] = []
    if not directory.is_dir():
        return summaries

    seen: set[str] = set()
    for path in sorted(directory.glob("*.y*ml")):
        domain = path.stem
        if domain in seen:
            continue
        seen.add(domain)
        try:
            pack = load_pack(domain)
            summaries.append(pack.summary())
        except Exception:  # noqa: BLE001 - never let one bad pack break the list
            summaries.append(
                {
                    "key": domain,
                    "display_name": domain.replace("_", " ").title(),
                    "actions_count": 0,
                    "decision_points_count": 0,
                }
            )
    return summaries
