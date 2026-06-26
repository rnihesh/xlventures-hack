"""Agent and tool registries.

Two lightweight registries decouple "what capabilities exist" from "how the
graph runs". A specialist registers an async ``node(state) -> dict`` under a
capability name; the planner looks specialists up by capability at runtime and
never imports specialist code directly. Adding a capability is a registration,
not a graph edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

# A specialist node takes the shared run state and returns a partial update.
NodeFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class AgentCard:
    """Everything the planner needs to know about a specialist, minus its code."""

    capability: str
    description: str
    node: NodeFn
    output_keys: List[str] = field(default_factory=list)
    cost_tier: str = "standard"  # cheap | standard | strong
    tags: List[str] = field(default_factory=list)

    def public(self) -> Dict[str, Any]:
        """Serializable view (no callable) for prompts or introspection."""

        return {
            "capability": self.capability,
            "description": self.description,
            "output_keys": list(self.output_keys),
            "cost_tier": self.cost_tier,
            "tags": list(self.tags),
        }


class AgentRegistry:
    """A capability -> AgentCard map."""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        self._agents[card.capability] = card

    def get(self, capability: str) -> AgentCard:
        return self._agents[capability]

    def find(self, capability: str) -> Optional[AgentCard]:
        return self._agents.get(capability)

    def has(self, capability: str) -> bool:
        return capability in self._agents

    def names(self) -> List[str]:
        return list(self._agents.keys())

    def cards(self) -> List[AgentCard]:
        return list(self._agents.values())

    def public_cards(self) -> List[Dict[str, Any]]:
        return [card.public() for card in self._agents.values()]


# Process-wide singleton registry.
AGENTS = AgentRegistry()


def register_agent(
    capability: str,
    description: str,
    output_keys: Optional[List[str]] = None,
    cost_tier: str = "standard",
    tags: Optional[List[str]] = None,
) -> Callable[[NodeFn], NodeFn]:
    """Decorator that registers an async node under a capability name."""

    def decorator(fn: NodeFn) -> NodeFn:
        AGENTS.register(
            AgentCard(
                capability=capability,
                description=description,
                node=fn,
                output_keys=output_keys or [],
                cost_tier=cost_tier,
                tags=tags or [],
            )
        )
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Tool registry (minimal): describes callable tools by name and governance.
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    """Describes a tool the engine can call, with governance metadata."""

    name: str
    kind: str  # python | http | mcp
    description: str = ""
    side_effecting: bool = False
    risk_tier: str = "low"  # low | medium | high
    binding: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """A name -> ToolSpec map for governance-aware tool lookup."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def specs(self) -> List[ToolSpec]:
        return list(self._tools.values())


TOOLS = ToolRegistry()

# A few representative tool specs so the governance story is visible.
TOOLS.register(
    ToolSpec(
        name="hybrid_search",
        kind="python",
        description="Hybrid lexical plus dense retrieval over the evidence corpus.",
        side_effecting=False,
        risk_tier="low",
        binding={"import": "app.retrieval.store:get_retriever"},
    )
)
TOOLS.register(
    ToolSpec(
        name="draft_email",
        kind="python",
        description="Draft a personalized outreach email for a recommended play.",
        side_effecting=True,
        risk_tier="high",
        binding={"node": "drafter"},
    )
)
TOOLS.register(
    ToolSpec(
        name="kpi_simulate",
        kind="python",
        description="Project KPI movement for a candidate action.",
        side_effecting=False,
        risk_tier="low",
        binding={"node": "outcome_simulator"},
    )
)
