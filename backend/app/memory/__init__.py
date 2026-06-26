"""Persistent customer memory and the learning loop.

This package implements the Memory interface that the rest of the backend
depends on. It stores decision *episodes* per account, records the human
*outcome* of each recommendation (accepted / edited / rejected), and distills
those outcomes into procedural *preferences* that improve future
recommendations.

Public surface (frozen interface):

    class Memory:
        async recall_similar(account_id, situation, k=3) -> list[dict]
        async write_episode(account_id, domain, situation, action_key, recommendation) -> str
        async record_outcome(episode_id, decision, reason, outcome) -> None
        async get_preferences(domain) -> dict

    def get_memory() -> Memory

The default implementation is fully in-memory and seeded with day-zero
episodes (including a few where the system was previously wrong) so that a
measurable before/after improvement is demoable offline, with no database or
network required. When ``DATABASE_URL`` is configured the same in-memory store
is used as a write-through cache; durable persistence can be layered on later
without changing the interface.
"""

from __future__ import annotations

from app.memory.distill import run_distillation
from app.memory.store import Memory, get_memory
from app.memory.types import Episode, Outcome, Preference

__all__ = [
    "Memory",
    "get_memory",
    "Episode",
    "Outcome",
    "Preference",
    "run_distillation",
]
