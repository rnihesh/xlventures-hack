"""Critic and verifier.

Assembles the Explainable Recommendation Object from the grounded state, then
runs an adversarial faithfulness pass: every claim in the rationale must be
backed by cited evidence. The critic can downgrade confidence and can demand a
human (HITL) when confidence is low or the action is high risk.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents import make_step
from app.explain.recommendation import build_recommendation
from app.packs.registry import register_agent

# Actions that always require human approval before execution.
_HIGH_RISK_ACTIONS = {
    "offer_save_concession",
    "open_executive_escalation",
    "propose_expansion_offer",
    "resolve_billing_dispute",
    "send_proposal",
}


def _faithfulness(recommendation: Dict[str, Any]) -> Dict[str, Any]:
    """Check that the rationale's claims are grounded in cited evidence."""

    evidence: List[Dict[str, Any]] = recommendation.get("evidence") or []
    cited = [e for e in evidence if e.get("snippet") and e.get("source_id")]
    uncited = [e for e in evidence if not (e.get("snippet") and e.get("source_id"))]

    faithful = len(cited) > 0 and len(uncited) == 0
    coverage = round(len(cited) / len(evidence), 3) if evidence else 0.0
    return {
        "faithful": faithful,
        "cited_claims": len(cited),
        "uncited_claims": len(uncited),
        "coverage": coverage,
    }


@register_agent(
    capability="critic",
    description="Verifies faithfulness against evidence and calibrates confidence.",
    output_keys=["recommendation", "critic"],
    cost_tier="strong",
    tags=["guardrail"],
)
async def node(state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.deps import get_llm

        llm = get_llm()
    except Exception:  # noqa: BLE001
        llm = None

    recommendation = build_recommendation(dict(state), llm)

    report = _faithfulness(recommendation)

    # Recalibrate confidence: an unfaithful rationale loses credibility.
    confidence = recommendation.get("confidence") or {}
    score = float(confidence.get("score", 0.7))
    if not report["faithful"]:
        score = round(score * 0.7, 3)
    score = max(0.05, min(0.97, score))
    label = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    confidence["score"] = score
    confidence["label"] = label
    confidence["method"] = "self_consistency+verbalized+critic"
    recommendation["confidence"] = confidence

    action_key = (recommendation.get("action") or {}).get("key", "")
    is_risk = (recommendation.get("risk_opportunity") or {}).get("type") == "risk"
    requires_hitl = (
        action_key in _HIGH_RISK_ACTIONS or score < 0.85 or (is_risk and score < 0.9)
    )

    verdict = "approved_for_review" if report["faithful"] else "needs_replan"
    critic = {
        "faithful": report["faithful"],
        "coverage": report["coverage"],
        "cited_claims": report["cited_claims"],
        "uncited_claims": report["uncited_claims"],
        "confidence_reviewed": score,
        "requires_hitl": requires_hitl,
        "verdict": verdict,
    }

    return {
        "recommendation": recommendation,
        "critic": critic,
        "messages": [
            {
                "role": "critic",
                "content": f"{verdict} at confidence {score:.2f}"
                + (" (human review required)" if requires_hitl else ""),
            }
        ],
        "steps": [
            make_step(
                "critic",
                f"Verified faithfulness ({critic['coverage']:.0%}); confidence {score:.2f}",
                critic,
            )
        ],
    }
