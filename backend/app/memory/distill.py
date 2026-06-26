"""Distillation: turn outcomes into procedural preferences.

``run_distillation`` scans every episode that has a recorded outcome and, per
domain, computes:

  * per-action accept / reject counts and a signed ``weight``;
  * ``few_shot`` exemplars from accepted episodes (situation -> action);
  * ``rules`` derived from rejected episodes that named a preferred action,
    e.g. "When the situation resembles '<...>', prefer <preferred> over
    <rejected>";
  * an ``avoid`` map of actions the system has learned to deprioritize.

The result is written back onto the memory instance (``memory._preferences``)
and the preferences version is bumped so callers can detect that learning
happened. This is the step that makes the loop demoable: run it, then watch the
same accounts get the human-preferred action.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from app.memory.types import Preference, now_iso


def _short(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _label_for_weight(weight: float) -> str:
    if weight >= 0.34:
        return "prefer"
    if weight <= -0.34:
        return "avoid"
    return "neutral"


def _distill_domain(domain: str, episodes: List[Any]) -> Dict[str, Any]:
    """Build the preference bundle for a single domain."""

    prefs: Dict[str, Preference] = {}
    rules: List[str] = []
    avoid: Dict[str, Dict[str, Any]] = {}
    few_shot: List[Dict[str, Any]] = []

    accepted_total = 0
    decided_total = 0

    for ep in episodes:
        if ep.outcome is None or ep.outcome.decision == "pending":
            continue
        decided_total += 1

        pref = prefs.get(ep.action_key)
        if pref is None:
            pref = Preference(domain=domain, action_key=ep.action_key)
            prefs[ep.action_key] = pref

        if ep.outcome.accepted_like:
            accepted_total += 1
            pref.accept_count += 1
            # Accepted episodes become positive in-context exemplars.
            few_shot.append(
                {
                    "situation": ep.situation,
                    "action_key": ep.action_key,
                    "action_title": (ep.recommendation or {})
                    .get("action", {})
                    .get("title", ep.action_key),
                    "decision": ep.outcome.decision,
                    "account_id": ep.account_id,
                }
            )
        else:
            pref.reject_count += 1
            # Rejected episodes that named a better action become procedural
            # rules and feed the avoid map.
            preferred = ep.preferred_action_key
            if preferred:
                # Credit the preferred action as a positive signal too.
                pp = prefs.get(preferred)
                if pp is None:
                    pp = Preference(domain=domain, action_key=preferred)
                    prefs[preferred] = pp
                pp.accept_count += 1

                rule = (
                    f"When the situation resembles \"{_short(ep.situation)}\", "
                    f"prefer '{preferred}' over '{ep.action_key}'."
                )
                if rule not in rules:
                    rules.append(rule)

                entry = avoid.setdefault(
                    ep.action_key,
                    {"action_key": ep.action_key, "count": 0, "prefer_instead": []},
                )
                entry["count"] += 1
                if preferred not in entry["prefer_instead"]:
                    entry["prefer_instead"].append(preferred)

    # Compute signed weights and attach rules per action.
    action_weights: Dict[str, float] = {}
    for key, pref in prefs.items():
        total = pref.accept_count + pref.reject_count
        pref.weight = round((pref.accept_count - pref.reject_count) / total, 3) if total else 0.0
        action_weights[key] = pref.weight
        pref.rules = [r for r in rules if f"'{key}'" in r]

    accepted_rate = round(accepted_total / decided_total, 3) if decided_total else 0.0

    return {
        "domain": domain,
        "updated_at": now_iso(),
        "decided_episodes": decided_total,
        "accepted_rate": accepted_rate,
        "action_weights": action_weights,
        "preferences": {k: v.model_dump() for k, v in prefs.items()},
        # Keep the most recent, highest-signal exemplars first.
        "few_shot": few_shot[-8:],
        "rules": rules,
        "avoid": avoid,
    }


def run_distillation(memory: Any) -> Dict[str, Any]:
    """Distill all episodes in ``memory`` into per-domain preferences.

    Mutates ``memory._preferences`` and bumps ``memory._pref_version``.
    Returns a summary suitable for logging or returning from an API.
    """

    by_domain: Dict[str, List[Any]] = defaultdict(list)
    for ep in memory.all_episodes():
        by_domain[ep.domain].append(ep)

    summary_domains: Dict[str, Any] = {}
    for domain, eps in by_domain.items():
        bundle = _distill_domain(domain, eps)
        memory._preferences[domain] = bundle
        summary_domains[domain] = {
            "rules": len(bundle["rules"]),
            "accepted_rate": bundle["accepted_rate"],
            "actions_learned": len(bundle["action_weights"]),
        }

    memory._pref_version += 1
    memory._distilled = True

    return {
        "version": memory._pref_version,
        "domains": summary_domains,
        "updated_at": now_iso(),
    }
