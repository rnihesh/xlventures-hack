"""The Memory store: in-memory episode + outcome storage with similarity recall.

The default ``Memory`` is fully in-memory and seeded at construction with
day-zero episodes (see ``seed_episodes``). It runs distillation once on
startup so preferences exist immediately. It requires no database and no
network: recall uses a lightweight lexical similarity (token Jaccard blended
with a sequence ratio) so the demo boots offline.

When ``DATABASE_URL`` is set the same in-memory store is used; a Postgres
write-through layer can be added later behind this identical interface without
touching callers.
"""

from __future__ import annotations

import difflib
import re
import uuid
from typing import Any, Dict, List, Optional

from app.memory.distill import run_distillation
from app.memory.seed_episodes import load_seed_episodes
from app.memory.types import Episode, Outcome, normalize_decision

_WORD_RE = re.compile(r"[a-z0-9]+")

# Light stopword list so similarity keys on meaningful tokens.
_STOP = {
    "the", "a", "an", "and", "or", "is", "are", "to", "of", "in", "on", "at",
    "for", "with", "has", "have", "had", "this", "that", "was", "were", "it",
    "as", "by", "from", "but", "not", "no", "two", "over", "out", "up", "down",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall((text or "").lower()) if t not in _STOP}


def _similarity(a: str, b: str) -> float:
    """Blend token Jaccard with a character sequence ratio. Range [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    jaccard = inter / union if union else 0.0
    ratio = difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
    return round(0.65 * jaccard + 0.35 * ratio, 4)


class Memory:
    """In-memory implementation of the frozen Memory interface."""

    def __init__(self, *, seed: bool = True) -> None:
        self._episodes: Dict[str, Episode] = {}
        # domain -> distilled preference bundle (see distill.run_distillation).
        self._preferences: Dict[str, Dict[str, Any]] = {}
        self._pref_version: int = 0
        self._distilled: bool = False

        if seed:
            for ep in load_seed_episodes():
                self._episodes[ep.id] = ep
            # Distill once so preferences are available on first request.
            run_distillation(self)

    # -- internal helpers ----------------------------------------------------

    def all_episodes(self) -> List[Episode]:
        """All stored episodes (insertion order)."""
        return list(self._episodes.values())

    def _ensure_distilled(self) -> None:
        if not self._distilled:
            run_distillation(self)

    # -- frozen interface ----------------------------------------------------

    async def recall_similar(
        self, account_id: str, situation: str, k: int = 3
    ) -> List[Dict[str, Any]]:
        """Return up to ``k`` past episodes most similar to ``situation``.

        Same-account episodes get a relevance boost so the "what changed since
        last time" story surfaces first, but cross-account precedents are still
        eligible. Each result includes a ``what_changed`` note when it is a
        prior decision on the same account.
        """

        scored: List[tuple[float, Episode]] = []
        for ep in self._episodes.values():
            sim = _similarity(situation, ep.situation)
            if ep.account_id == account_id:
                sim = min(1.0, sim + 0.15)  # same-account boost
            if sim <= 0.0:
                continue
            scored.append((sim, ep))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: List[Dict[str, Any]] = []
        for sim, ep in scored[: max(0, k)]:
            decision = ep.outcome.decision if ep.outcome else "pending"
            what_changed: Optional[str] = None
            if ep.account_id == account_id and ep.outcome is not None:
                if ep.outcome.accepted_like:
                    what_changed = (
                        f"Last time we recommended '{ep.action_key}' here and it was "
                        f"{ep.outcome.decision}; weight that action up."
                    )
                elif ep.preferred_action_key:
                    what_changed = (
                        f"Last time '{ep.action_key}' was rejected here; the team "
                        f"preferred '{ep.preferred_action_key}'."
                    )
                else:
                    what_changed = (
                        f"Last time '{ep.action_key}' was {ep.outcome.decision} here."
                    )
            results.append(
                {
                    "episode_id": ep.id,
                    "account_id": ep.account_id,
                    "domain": ep.domain,
                    "situation": ep.situation,
                    "action_key": ep.action_key,
                    "preferred_action_key": ep.preferred_action_key,
                    "decision": decision,
                    "similarity": sim,
                    "phase": ep.phase,
                    "what_changed": what_changed,
                    "recommendation": ep.recommendation,
                }
            )
        return results

    async def write_episode(
        self,
        account_id: str,
        domain: str,
        situation: str,
        action_key: str,
        recommendation: Dict[str, Any],
    ) -> str:
        """Persist a new episode and return its id."""

        episode_id = f"ep-{uuid.uuid4().hex[:12]}"
        self._episodes[episode_id] = Episode(
            id=episode_id,
            account_id=account_id,
            domain=domain,
            situation=situation,
            action_key=action_key,
            recommendation=recommendation or {},
            phase="live",
            outcome=Outcome(decision="pending"),
        )
        return episode_id

    async def record_outcome(
        self,
        episode_id: str,
        decision: str,
        reason: Optional[str] = None,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Attach a human decision (and optional measured metrics) to an episode
        and re-distill so the next recommendation reflects the new signal."""

        episode = self._episodes.get(episode_id)
        if episode is None:
            return

        episode.outcome = Outcome(
            decision=normalize_decision(decision),
            reason=reason,
            metrics=dict(outcome or {}),
        )
        # Learning is incremental: every outcome updates preferences.
        run_distillation(self)

    async def get_preferences(self, domain: str) -> Dict[str, Any]:
        """Return the distilled preference bundle for ``domain``.

        The bundle feeds the recommender as improving few-shot examples plus
        procedural rules and per-action weights. Empty-but-valid shape is
        returned for unknown domains so callers never need to special-case.
        """

        self._ensure_distilled()
        bundle = self._preferences.get(domain)
        if bundle is None:
            return {
                "domain": domain,
                "version": self._pref_version,
                "decided_episodes": 0,
                "accepted_rate": 0.0,
                "action_weights": {},
                "preferences": {},
                "few_shot": [],
                "rules": [],
                "avoid": {},
            }
        return {**bundle, "version": self._pref_version}


# ---------------------------------------------------------------------------
# Factory (singleton)
# ---------------------------------------------------------------------------

_memory: Optional[Memory] = None


def get_memory() -> Memory:
    """Return the process-wide Memory singleton (seeded + distilled)."""
    global _memory
    if _memory is None:
        _memory = Memory(seed=True)
    return _memory
