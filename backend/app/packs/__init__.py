"""Domain Pack subsystem: schema, loader, and registries.

Public surface used by the rest of the backend:

    from app.packs.loader import load_pack, list_packs
    from app.packs.schema import DomainPack
    from app.packs.registry import AGENTS, register_agent, TOOLS
"""

from __future__ import annotations

from app.packs.loader import list_packs, load_pack
from app.packs.registry import AGENTS, TOOLS, AgentCard, register_agent
from app.packs.schema import DomainPack

__all__ = [
    "load_pack",
    "list_packs",
    "DomainPack",
    "AGENTS",
    "TOOLS",
    "AgentCard",
    "register_agent",
]
