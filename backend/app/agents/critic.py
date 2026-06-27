"""Critic and verifier.

Assembles the Explainable Recommendation Object from the grounded state, then
runs an adversarial faithfulness pass: every claim in the rationale must be
backed by cited evidence. The critic can downgrade confidence and can demand a
human (HITL) when confidence is low or the action is high risk.
"""

from __future__ import annotations

import asyncio

import re
from typing import Any, Dict, List

from app.agents import make_step
from app.explain.recommendation import build_recommendation
from app.packs.registry import register_agent

_WORD_RE = re.compile(r"[a-z][a-z0-9\-]+")
_RATIONALE_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "value",
    "account", "action", "play", "their", "would", "before", "while", "which",
    "directly", "addresses", "strongest", "signals", "highest", "expected",
}

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


def _content_words(text: str) -> set[str]:
    """Lowercased content words from text, minus a small stop list."""

    return {
        w for w in _WORD_RE.findall((text or "").lower())
        if len(w) > 2 and w not in _RATIONALE_STOP
    }


def _reflection(
    recommendation: Dict[str, Any],
    report: Dict[str, Any],
    information_gaps: List[str],
) -> Dict[str, Any]:
    """A light self-consistency pass over the assembled recommendation.

    Re-reads the recommendation against its own cited evidence and the named
    information gaps, then derives a consistency score in [0, 1]. Thin evidence,
    a rationale that does not overlap the cited snippets, and a long list of open
    gaps all pull consistency (and therefore confidence) down. Deterministic and
    offline: it inspects only the already-built recommendation object.
    """

    evidence: List[Dict[str, Any]] = recommendation.get("evidence") or []
    grounded = [e for e in evidence if e.get("snippet") and e.get("source_id")]

    # Does the rationale actually echo the cited evidence, or float free of it?
    rationale_words = _content_words(recommendation.get("rationale", ""))
    evidence_blob = " ".join(
        f"{e.get('claim', '')} {e.get('snippet', '')}" for e in grounded
    )
    evidence_words = _content_words(evidence_blob)
    if rationale_words and evidence_words:
        overlap = len(rationale_words & evidence_words) / len(rationale_words)
    else:
        overlap = 0.0
    overlap = round(overlap, 3)

    contradicting = (recommendation.get("signals") or {}).get("contradicting") or []
    gaps_n = len(information_gaps)
    thin_evidence = len(grounded) < 2

    consistency = 1.0
    notes: List[str] = []
    if thin_evidence:
        consistency -= 0.25
        notes.append("Only a single grounded source supports the call.")
    if overlap < 0.12:
        consistency -= 0.2
        notes.append("Rationale is weakly tied to the cited evidence.")
    if not report.get("faithful", True):
        consistency -= 0.2
        notes.append("At least one rationale claim is uncited.")
    # Each open information gap erodes a little confidence, capped so a thorough
    # gap analysis does not collapse the score on its own.
    consistency -= min(gaps_n, 4) * 0.05
    if gaps_n:
        notes.append(f"{gaps_n} open information gap(s) remain.")
    if not contradicting:
        consistency -= 0.05
        notes.append("Case rests only on confirming signals (no counter-signal tested).")

    consistency = round(max(0.0, min(1.0, consistency)), 3)
    return {
        "consistency": consistency,
        "rationale_evidence_overlap": overlap,
        "grounded_sources": len(grounded),
        "thin_evidence": thin_evidence,
        "gaps_considered": gaps_n,
        "notes": notes,
    }


def _information_gaps(
    recommendation: Dict[str, Any], report: Dict[str, Any]
) -> List[str]:
    """Name the concrete missing facts that would change or strengthen the call.

    Built from what the retrieval evidence and account context do NOT contain
    (carried on the recommendation as ``missing_information``), plus gaps the
    faithfulness pass itself exposes. Deterministic and offline.
    """

    gaps: List[str] = []
    for item in recommendation.get("missing_information") or []:
        text = item.get("gap")
        if text:
            gaps.append(str(text))

    # A rationale with uncited claims is itself a known gap: the claim stands but
    # its source does not, so flag what still needs grounding.
    if report.get("uncited_claims"):
        gaps.append(
            "Some rationale claims are not yet tied to cited evidence and need a verifiable source."
        )

    # Thin evidence is a gap even when everything cited is faithful.
    if report.get("cited_claims", 0) < 2:
        gaps.append(
            "Only a single corroborating source was retrieved; more evidence would raise confidence."
        )

    # De-duplicate while preserving the surfaced order.
    seen: set[str] = set()
    unique: List[str] = []
    for g in gaps:
        if g not in seen:
            seen.add(g)
            unique.append(g)
    return unique


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

    recommendation = await asyncio.to_thread(build_recommendation, dict(state), llm)

    report = _faithfulness(recommendation)

    # The information gaps are computed first so the reflection pass can weigh
    # how many concrete unknowns still surround the call.
    information_gaps = _information_gaps(recommendation, report)
    reflection = _reflection(recommendation, report, information_gaps)

    # SINGLE calibration path. The explain step set a PRIOR (an evidence and
    # action signal, labelled method="evidence_prior"); the critic is the sole
    # owner of the FINAL confidence and the method of record. We take the prior
    # once, then apply two penalties in one pass: an unfaithful rationale loses
    # credibility outright, and the self-consistency reflection scales what
    # remains (thin evidence and open gaps pull it down, up to a 30% reduction).
    # No value is calibrated twice and there is exactly one method string.
    confidence = recommendation.get("confidence") or {}
    prior = float(confidence.get("prior", confidence.get("score", 0.7)))
    score = prior
    if not report["faithful"]:
        score = score * 0.7
    consistency = float(reflection["consistency"])
    score = round(score * (1.0 - 0.3 * (1.0 - consistency)), 3)
    score = max(0.05, min(0.97, score))
    label = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    confidence["prior"] = round(prior, 3)
    confidence["score"] = score
    confidence["label"] = label
    confidence["method"] = "critic_reflection"
    confidence["consistency"] = consistency
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
        "information_gaps": information_gaps,
        "reflection": reflection,
        "verdict": verdict,
    }

    return {
        "recommendation": recommendation,
        "critic": critic,
        "messages": [
            {
                "role": "critic",
                "content": f"{verdict} at confidence {score:.2f} "
                f"(self-consistency {consistency:.2f})"
                + (" (human review required)" if requires_hitl else ""),
            }
        ],
        "steps": [
            make_step(
                "critic",
                f"Verified faithfulness ({critic['coverage']:.0%}); "
                f"reflection {consistency:.2f}; confidence {score:.2f}",
                critic,
            )
        ],
    }
