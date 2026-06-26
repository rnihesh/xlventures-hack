"""Day-zero seed episodes for the learning loop.

The learning loop starts EMPTY: there is no fabricated before/after history and
no pre-baked "climbed from X%" narrative. Episodes accrue only from real runs
(``write_episode``) and real human decisions (``record_outcome``), so every
acceptance rate and every distilled preference reflects actual usage.

``load_seed_episodes`` therefore returns an empty list. The function and the
``SEED_EPISODES_JSON`` export are kept so existing imports in the memory store
and the seed CLI continue to work unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.memory.types import Episode


def load_seed_episodes() -> List[Episode]:
    """Return the day-zero episodes. Empty by design: learn from real runs only."""
    return []


# A json-shaped export, handy for inspection / fixtures. Empty by design.
SEED_EPISODES_JSON: List[Dict[str, Any]] = [e.model_dump() for e in load_seed_episodes()]
