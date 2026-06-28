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

# The agentic copilot's callable tool surface (app/chat/tools.py). Registered
# here so the governance catalog and the Agents page reflect the FULL tool
# architecture (every API capability is also an agent-callable tool), not just
# the in-graph specialists above.
_COPILOT_TOOLS: List[ToolSpec] = [
    ToolSpec("list_accounts", "python", "List the org's accounts ranked by risk.", False, "low"),
    ToolSpec("get_account", "python", "Fetch one account's 360 (signals, context, history).", False, "low"),
    ToolSpec("list_domains", "python", "List available domain packs.", False, "low"),
    ToolSpec("get_domain", "python", "Inspect a domain pack (process, journey, decision points).", False, "low"),
    ToolSpec("run_nba", "python", "Run the full planner graph and return an explained recommendation.", True, "medium", {"graph": "planner"}),
    ToolSpec("search_knowledge", "python", "Hybrid retrieval over the evidence corpus with citations.", False, "low"),
    ToolSpec("web_search", "http", "Live Google web search via Serper for fresh public context.", False, "low"),
    ToolSpec("evaluate_policy", "python", "Check a candidate action against the org's policy guardrails.", False, "low"),
    ToolSpec("execute_action", "python", "Generate a concrete artifact (email, task, slack) from a recommendation.", True, "medium"),
    ToolSpec("get_last_run", "python", "Return the org's most recent run and recommendation.", False, "low"),
    ToolSpec("get_run", "python", "Return a specific run by id.", False, "low"),
    ToolSpec("send_artifact", "python", "Deliver a run's recommendation by email or Slack to one or more recipients.", True, "high"),
    ToolSpec("send_message", "python", "Send a composed email (custom subject and body) to a saved contact or given address.", True, "high"),
    ToolSpec("tag_run", "python", "Associate a run with an account or note.", True, "low"),
    ToolSpec("ingest_interaction", "python", "Ingest an interaction (note, transcript, email) into retrievable evidence.", True, "medium"),
    ToolSpec("get_learning", "python", "Read the org's learning loop (decisions, acceptance, outcomes).", False, "low"),
    ToolSpec("get_eval", "python", "Read the org's evaluation outcomes.", False, "low"),
]
for _spec in _COPILOT_TOOLS:
    TOOLS.register(_spec)
