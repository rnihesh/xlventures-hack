"""The Memory store: episode + outcome storage with similarity recall.

The default ``Memory`` is seeded at construction with day-zero episodes (see
``seed_episodes``) and runs distillation once so preferences exist immediately.
It requires no database and no network: recall uses a lightweight lexical
similarity (token Jaccard blended with a sequence ratio) so the demo boots
offline.

When ``DATABASE_URL`` is set the in-memory store becomes a write-through cache
over Postgres: persisted episodes (and their outcomes) are lazily loaded on the
first async access and every ``write_episode`` / ``record_outcome`` is mirrored
to the ``episodes`` table via the episodes repository, so learning survives
restarts. With no database the same code path is a graceful no-op and behavior
is identical to the pure in-memory store. The frozen Memory interface
(recall_similar, write_episode, record_outcome, get_preferences) is unchanged.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from app.memory.distill import run_distillation
from app.memory.seed_episodes import load_seed_episodes
from app.memory.types import Episode, Outcome, normalize_decision

logger = logging.getLogger("app.memory.store")

# Tenant that owns unscoped (seeded day-zero) episodes. Kept in sync with
# app.api._org.DEMO_ORG; defined locally to avoid importing the API layer into
# the memory store (and the import cycle that would create).
_DEMO_ORG = "org_demo"

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

        # Postgres write-through (lazy). ``_repo`` stays None offline; the load
        # guard makes the one-time DB hydration idempotent and concurrency-safe.
        self._repo: Any | None = None
        self._db_loaded: bool = False
        self._db_lock = asyncio.Lock()

        if seed:
            for ep in load_seed_episodes():
                self._episodes[ep.id] = ep
            # Distill once so preferences are available on first request.
            run_distillation(self)

    # -- internal helpers ----------------------------------------------------

    def all_episodes(self) -> List[Episode]:
        """All stored episodes (insertion order)."""
        return list(self._episodes.values())

    def get_episode(self, episode_id: str) -> Optional[Episode]:
        """Return a single stored episode by id, or ``None`` if absent.

        Callers that accept an opaque, caller-supplied ``episode_id`` must use
        this to resolve the episode and verify org ownership BEFORE mutating it,
        so one tenant cannot write outcomes onto another tenant's episode.
        """
        return self._episodes.get(episode_id)

    def _ensure_distilled(self) -> None:
        if not self._distilled:
            run_distillation(self)

    # -- persistence (Postgres write-through, no-op offline) -----------------

    async def _ensure_db(self) -> None:
        """Lazily bind the episodes repository and hydrate persisted episodes.

        Runs at most once. When no pool is available (offline) this leaves the
        store as a pure in-memory + seeded instance. Any failure degrades to
        in-memory only so the app keeps serving.
        """

        if self._db_loaded:
            return
        async with self._db_lock:
            if self._db_loaded:
                return
            try:
                from app.deps import get_pool
                from app.repositories.episodes import EpisodesRepository

                pool = await get_pool()
                repo = EpisodesRepository(pool)
                if repo.enabled:
                    self._repo = repo
                    await self._load_persisted(repo)
            except Exception as exc:  # noqa: BLE001 - persistence is best-effort
                logger.warning("Memory persistence unavailable: %s", exc)
                self._repo = None
            finally:
                self._db_loaded = True

    async def _embed_situation(self, text: str) -> Optional[List[float]]:
        """Embed an episode situation for pgvector recall (best-effort).

        Uses OpenAI embeddings when configured, else the deterministic offline
        hash embedding, so persisted episode vectors are consistent between
        write and recall. Returns ``None`` if embedding is unavailable.
        """
        try:
            from app.retrieval.embeddings import embed_for_index

            matrix, _ = await embed_for_index([text or ""])
            if matrix is not None and len(matrix):
                return matrix[0].tolist()
        except Exception:  # noqa: BLE001 - embeddings are best-effort
            pass
        return None

    async def _load_persisted(self, repo: Any) -> None:
        """Merge DB-persisted episodes over the seeds, or seed an empty DB."""

        rows = await repo.list_all()
        if not rows:
            # First boot against an empty database: persist the seeded day-zero
            # episodes (with embeddings) so the before/after learning story and
            # vector recall both survive restarts.
            for ep in list(self._episodes.values()):
                try:
                    await self._persist_episode(ep.id)
                except Exception:  # noqa: BLE001
                    pass
            return

        changed = False
        for payload in rows:
            try:
                ep = Episode(**payload)
            except Exception:  # noqa: BLE001 - skip any malformed row
                continue
            self._episodes[ep.id] = ep
            changed = True
        if changed:
            # Re-distill so preferences reflect the persisted outcomes.
            run_distillation(self)

    async def _persist_episode(self, episode_id: str) -> None:
        """Mirror a single episode (and its embedding) to Postgres when enabled."""

        if self._repo is None:
            return
        episode = self._episodes.get(episode_id)
        if episode is None:
            return
        try:
            embedding = await self._embed_situation(episode.situation)
            await self._repo.save(episode.model_dump(), embedding=embedding)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist episode %s: %s", episode_id, exc)

    # -- frozen interface ----------------------------------------------------

    def _owns(self, ep: Episode, org_id: Optional[str]) -> bool:
        """True when ``ep`` is visible to ``org_id`` (tenant isolation).

        An unscoped (seeded day-zero) episode belongs to the Demo org, mirroring
        the learning / timeline surfaces. ``org_id is None`` means "no tenant
        filter" (legacy callers): every episode is visible, preserving the old
        behavior. A concrete ``org_id`` only ever sees its own episodes, so recall
        can never surface another tenant's situation or recommendation even when
        two orgs share an account id (e.g. both ran import-demo).
        """
        if org_id is None:
            return True
        return (getattr(ep, "org_id", None) or _DEMO_ORG) == org_id

    async def recall_similar(
        self, account_id: str, situation: str, k: int = 3, org_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return up to ``k`` past episodes most similar to ``situation``.

        Same-account episodes get a relevance boost so the "what changed since
        last time" story surfaces first, but cross-account precedents are still
        eligible. Each result includes a ``what_changed`` note when it is a
        prior decision on the same account.

        ``org_id`` scopes recall to the caller's tenant: only that org's episodes
        (plus the seeded Demo history when the caller IS the Demo org) are
        eligible, so one tenant never reads another's episodes through this path.
        ``None`` keeps the unscoped, all-tenants behavior for legacy callers.
        """

        # Hydrate persisted episodes (no-op offline) so recall spans history.
        await self._ensure_db()

        # Prefer a pgvector similarity search when persistence is enabled; fall
        # back to the in-memory lexical similarity otherwise (or on any error).
        vector_results = await self._recall_via_pgvector(account_id, situation, k, org_id)
        if vector_results is not None:
            return vector_results

        scored: List[tuple[float, Episode]] = []
        for ep in self._episodes.values():
            if not self._owns(ep, org_id):
                continue
            sim = _similarity(situation, ep.situation)
            if ep.account_id == account_id:
                sim = min(1.0, sim + 0.15)  # same-account boost
            if sim <= 0.0:
                continue
            scored.append((sim, ep))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            self._format_recall(ep, account_id, sim)
            for sim, ep in scored[: max(0, k)]
        ]

    async def _recall_via_pgvector(
        self, account_id: str, situation: str, k: int, org_id: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Vector-search recall over persisted episode embeddings.

        Returns formatted results when pgvector is available and usable, or
        ``None`` to signal the caller to use the in-memory fallback. Honors the
        same ``org_id`` tenant filter as the in-memory path so vector recall can
        never surface another tenant's episodes.
        """
        if self._repo is None or k <= 0:
            return None
        vec = await self._embed_situation(situation)
        if vec is None:
            return None
        try:
            rows = await self._repo.search_similar(vec, k=max(k * 4, k))
        except Exception as exc:  # noqa: BLE001 - degrade to in-memory recall
            logger.warning("Vector recall failed: %s", exc)
            return None
        if not rows:
            return None

        scored: List[tuple[float, Episode]] = []
        for payload in rows:
            sim = float(payload.get("similarity", 0.0))
            try:
                ep = Episode(**{p: v for p, v in payload.items() if p != "similarity"})
            except Exception:  # noqa: BLE001 - skip malformed rows
                continue
            if not self._owns(ep, org_id):
                continue
            if ep.account_id == account_id:
                sim = min(1.0, sim + 0.15)  # same-account boost
            scored.append((sim, ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            self._format_recall(ep, account_id, sim)
            for sim, ep in scored[: max(0, k)]
        ]

    def _format_recall(
        self, ep: Episode, account_id: str, sim: float
    ) -> Dict[str, Any]:
        """Shape one recalled episode into the public recall dict."""
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
        return {
            "episode_id": ep.id,
            "account_id": ep.account_id,
            "domain": ep.domain,
            "situation": ep.situation,
            "action_key": ep.action_key,
            "preferred_action_key": ep.preferred_action_key,
            "decision": decision,
            "similarity": round(float(sim), 4),
            "phase": ep.phase,
            "what_changed": what_changed,
            "recommendation": ep.recommendation,
        }

    async def write_episode(
        self,
        account_id: str,
        domain: str,
        situation: str,
        action_key: str,
        recommendation: Dict[str, Any],
        org_id: Optional[str] = None,
    ) -> str:
        """Persist a new episode and return its id.

        ``org_id`` scopes the episode to its owning tenant for the learning loop
        (``None`` keeps it with the Demo org that owns the seeded history).
        """

        await self._ensure_db()

        episode_id = f"ep-{uuid.uuid4().hex[:12]}"
        self._episodes[episode_id] = Episode(
            id=episode_id,
            account_id=account_id,
            domain=domain,
            org_id=org_id,
            situation=situation,
            action_key=action_key,
            recommendation=recommendation or {},
            phase="live",
            outcome=Outcome(decision="pending"),
        )
        # Mirror to Postgres when enabled (no-op offline).
        await self._persist_episode(episode_id)
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

        await self._ensure_db()

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

        # Mirror the updated outcome to Postgres (no-op offline) and append an
        # audit row so the learning history is durable.
        if self._repo is not None:
            try:
                await self._repo.record_outcome(
                    episode.model_dump(), episode.outcome.model_dump()
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to persist outcome for %s: %s", episode_id, exc
                )

    async def get_preferences(self, domain: str) -> Dict[str, Any]:
        """Return the distilled preference bundle for ``domain``.

        The bundle feeds the recommender as improving few-shot examples plus
        procedural rules and per-action weights. Empty-but-valid shape is
        returned for unknown domains so callers never need to special-case.
        """

        await self._ensure_db()
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
