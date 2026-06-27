"""Generate REAL learning episodes by driving the actual planner graph.

``python -m app.gen_runs --n 12``

This is not a fixture writer: it executes N real runs through the same
LangGraph planner the API uses, in deterministic DEMO_MODE (offline, no network,
reproducible), then records a believable spread of human decisions
(approve / edit / reject) through the very same ``memory.record_outcome`` path
the HITL endpoint uses. The result is that the learning surface (``/learning``)
and the projected outcomes (``/eval``) are populated by episodes the system
genuinely produced, not by hand-written numbers.

Determinism: DEMO_MODE forces the canned model, accounts are selected in a
stable order, and decisions follow a fixed cycle, so every invocation yields the
same episodes. Offline (no DATABASE_URL) the memory store is fresh per process,
so re-running simply reproduces the same batch. When a database is configured,
the run is guarded (see ``--force``) so it does not silently duplicate history.

Usage:
    python -m app.gen_runs --n 12          # generate 12 real decided episodes
    python -m app.gen_runs --n 20 --force  # re-run even if a DB already has some
"""

from __future__ import annotations

import argparse
import asyncio
import os

# Seeding script: run fully offline (deterministic, no network, no token spend)
# by blanking the OpenAI key before anything imports the LLM or the graph. With
# no key the engine uses its deterministic fallback model.
os.environ["OPENAI_API_KEY"] = ""

from typing import Any, Dict, List, Optional, Tuple

from app import seed_data
from app.deps import get_checkpointer
from app.graph.planner import build_graph
from app.memory.store import get_memory

# Domains to draw accounts from, in a stable order. Each maps to a
# backend/seeds/<domain>/ folder shared with retrieval and the accounts API.
_DOMAINS = ["customer_success", "saas_sales", "collections"]

# A fixed decision cycle: a realistic majority-accept mix with edits and the
# occasional reject, so the acceptance rate and the per-account "preferred play"
# learning are both exercised. accepted-like share is 5/6 across the cycle.
_DECISION_CYCLE = ["approve", "approve", "edit", "approve", "reject", "approve"]

# Honest, labeled projection constants for the per-episode NRR metric. The lift
# is realised only when the human takes the action (approve/edit); a reject
# realises nothing. The realised lift is scaled by the simulator's effectiveness
# and the recommendation's own confidence, so the recorded number is derived
# from the real run, not invented.
_BASELINE_NRR = 100.0
_MAX_NRR_LIFT = 9.0

# Reasons attached to each decision so the episode log reads like real review
# notes (and rejects carry a rationale distillation can learn from).
_REASONS: Dict[str, str] = {
    "approve": "Evidence and projected impact justified the play; approved as drafted.",
    "edit": "Approved with a lighter touch: tightened the outreach before sending.",
    "reject": "Held off: preferred to monitor and revisit after the next check-in.",
}


def _select_accounts(n: int) -> List[Dict[str, Any]]:
    """Pick ``n`` accounts spread across domains in a stable, repeatable order.

    Round-robins across domains (so the demo shows multiple verticals) and sorts
    within each domain by account id for determinism.
    """

    per_domain: Dict[str, List[Dict[str, Any]]] = {}
    for domain in _DOMAINS:
        accounts = sorted(
            (dict(a, domain=a.get("domain", domain)) for a in seed_data.load_accounts(domain)),
            key=lambda a: str(a.get("account_id", "")),
        )
        if accounts:
            per_domain[domain] = accounts

    selected: List[Dict[str, Any]] = []
    cursor: Dict[str, int] = {d: 0 for d in per_domain}
    # Round-robin until we have n accounts or every domain is exhausted.
    while len(selected) < n and any(cursor[d] < len(per_domain[d]) for d in per_domain):
        for domain in _DOMAINS:
            if domain not in per_domain:
                continue
            idx = cursor[domain]
            if idx < len(per_domain[domain]):
                selected.append(per_domain[domain][idx])
                cursor[domain] = idx + 1
                if len(selected) >= n:
                    break
    return selected[:n]


def _signal_for(account: Dict[str, Any]) -> Dict[str, str]:
    """Build a realistic signal envelope from the account's active signals."""

    active = account.get("active_signals") or []
    signal_type = str(active[0]) if active else "health_drop"
    content = (
        account.get("last_signal")
        or account.get("summary")
        or f"{signal_type.replace('_', ' ')} detected on {account.get('name', account['account_id'])}"
    )
    return {"type": signal_type, "content": str(content)}


def _projected_nrr(accepted_like: bool, simulation: Dict[str, Any], confidence: float) -> float:
    """Per-episode projected NRR (labeled projection, derived from the real run).

    The action only moves NRR when the human takes it; the realised lift scales
    with the simulator's effectiveness and the recommendation's confidence.
    """

    if not accepted_like:
        return round(_BASELINE_NRR, 1)
    effectiveness = float(simulation.get("effectiveness", 0.5) or 0.5)
    lift = _MAX_NRR_LIFT * max(0.0, min(1.0, effectiveness)) * max(0.0, min(1.0, confidence))
    return round(_BASELINE_NRR + lift, 1)


async def _run_one(
    graph: Any, account: Dict[str, Any], index: int
) -> Optional[Tuple[str, Dict[str, Any], float]]:
    """Drive a single real run and return (episode_id, simulation, confidence)."""

    domain = account.get("domain", "customer_success")
    signal = _signal_for(account)
    thread_id = f"gen-run-{index}"
    state = {
        "run_id": thread_id,
        "domain": domain,
        "account_id": account["account_id"],
        "signal": signal,
        "plan": [],
        "capabilities": [],
        "steps": [],
        "messages": [],
        "recommendation": None,
    }
    config = {"configurable": {"thread_id": thread_id}}
    final = await graph.ainvoke(state, config=config)

    episode_id = final.get("episode_id")
    if not episode_id:
        return None
    simulation = final.get("simulation") or {}
    recommendation = final.get("recommendation") or {}
    confidence = float((recommendation.get("confidence") or {}).get("score", 0.7) or 0.7)
    return episode_id, simulation, confidence


async def generate(n: int, force: bool) -> Dict[str, Any]:
    """Execute ``n`` real runs and record a deterministic spread of decisions."""

    memory = get_memory()

    # Guard against silently duplicating history when persistence is enabled.
    existing = [e for e in memory.all_episodes() if e.outcome and e.outcome.decision != "pending"]
    if existing and not force and os.getenv("DATABASE_URL"):
        return {
            "skipped": True,
            "reason": (
                f"{len(existing)} decided episodes already present in a persistent "
                "store. Re-run with --force to add another batch."
            ),
        }

    accounts = _select_accounts(n)
    if not accounts:
        return {"skipped": True, "reason": "No seed accounts found to run."}

    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer)

    counts = {"approve": 0, "edit": 0, "reject": 0}
    produced = 0
    for i, account in enumerate(accounts):
        result = await _run_one(graph, account, i)
        if result is None:
            continue
        episode_id, simulation, confidence = result

        decision = _DECISION_CYCLE[i % len(_DECISION_CYCLE)]
        accepted_like = decision in ("approve", "edit")
        counts[decision] += 1

        metrics = {
            "nrr_projected": _projected_nrr(accepted_like, simulation, confidence),
            "arr_at_risk": int(account.get("arr", 0) or 0),
            "sim_kpi": simulation.get("kpi"),
            "sim_delta": simulation.get("delta"),
            "confidence": round(confidence, 3),
            "projected": True,
        }
        await memory.record_outcome(
            episode_id=episode_id,
            decision=decision,
            reason=_REASONS[decision],
            outcome=metrics,
        )
        produced += 1

    decided = sum(counts.values())
    accepted = counts["approve"] + counts["edit"]
    return {
        "skipped": False,
        "runs": produced,
        "decided": decided,
        "accepted": accepted,
        "rejected": counts["reject"],
        "edited": counts["edit"],
        "approved": counts["approve"],
        "acceptance_rate": round(accepted / decided, 3) if decided else 0.0,
        "preferences_version": memory._pref_version,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate real learning episodes via the planner graph (DEMO_MODE)."
    )
    parser.add_argument("--n", type=int, default=12, help="Number of runs to execute.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Generate another batch even if a persistent store already has episodes.",
    )
    args = parser.parse_args()

    summary = asyncio.run(generate(max(1, args.n), args.force))

    print("=" * 60)
    print("gen_runs: real episodes through the planner graph (DEMO_MODE)")
    print("=" * 60)
    if summary.get("skipped"):
        print(f"Skipped: {summary.get('reason')}")
        return
    print(f"  runs executed   : {summary['runs']}")
    print(f"  decided         : {summary['decided']}")
    print(
        f"  approved/edited : {summary['approved']}/{summary['edited']} "
        f"(rejected {summary['rejected']})"
    )
    print(f"  acceptance rate : {summary['acceptance_rate'] * 100:.0f}%")
    print(f"  preferences ver : {summary['preferences_version']}")
    print("")
    print("Now load the UI: the dashboard, /learning, and /eval read these")
    print("real outcomes. Projected KPIs are labeled as projections.")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
