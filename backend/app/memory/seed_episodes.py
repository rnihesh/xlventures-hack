"""Day-zero seed episodes for the learning loop.

The seed is deliberately designed to tell a measurable before/after story on
the *same accounts*:

  * ``baseline`` phase: the system makes several day-zero recommendations.
    On three of five accounts it picks the wrong action and the human rejects
    it (recording the action they actually wanted). Baseline acceptance is
    therefore low (2 of 5 = 40%) and projected NRR is weak.

  * ``learned`` phase: after distillation turns those rejections into
    procedural preferences, the system re-decides the same accounts and now
    picks the human-preferred action every time. Acceptance climbs to 100% and
    projected NRR rises materially.

This data is plain Python dicts (json-shaped) so the store can run fully
offline. ``load_seed_episodes`` returns validated ``Episode`` objects.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.memory.types import Episode, Outcome

# ---------------------------------------------------------------------------
# Helpers to keep the seed compact and consistent.
# ---------------------------------------------------------------------------


def _rec(account_id: str, domain: str, action_key: str, title: str, description: str) -> Dict[str, Any]:
    """A minimal recommendation stub embedded in an episode (shape-compatible
    with the full recommendation object's ``action`` block)."""
    return {
        "account_id": account_id,
        "domain": domain,
        "action": {"key": action_key, "title": title, "description": description},
    }


def _ep(
    ep_id: str,
    account_id: str,
    situation: str,
    action_key: str,
    title: str,
    description: str,
    phase: str,
    decision: str,
    nrr: float,
    *,
    domain: str = "customer_success",
    preferred_action_key: str | None = None,
    reason: str | None = None,
    arr: float = 0.0,
    created_at: str = "",
) -> Episode:
    return Episode(
        id=ep_id,
        account_id=account_id,
        domain=domain,
        situation=situation,
        action_key=action_key,
        recommendation=_rec(account_id, domain, action_key, title, description),
        phase=phase,
        preferred_action_key=preferred_action_key,
        created_at=created_at or "2026-05-01T09:00:00+00:00",
        outcome=Outcome(
            decision=decision,
            reason=reason,
            metrics={"nrr_projected": nrr, "arr": arr},
        ),
    )


# ---------------------------------------------------------------------------
# Situations reused verbatim across phases so recall similarity is high and the
# before/after comparison is clearly about the *same* account context.
# ---------------------------------------------------------------------------

SIT_ACME = (
    "Healthy account, weekly active seats at 92% of license cap and climbing, "
    "champion asked about adding two new teams next quarter."
)
SIT_GLOBEX = (
    "Product usage down 38% quarter over quarter, executive sponsor has skipped "
    "two business reviews, renewal is 90 days out."
)
SIT_INITECH = (
    "New account, onboarding activation milestone is overdue at day 60 and "
    "daily logins are declining week over week."
)
SIT_UMBRELLA = (
    "Champion departed, support ticket volume spiked, sentiment in the latest "
    "call notes is sharply negative."
)
SIT_SOYLENT = (
    "Renewal is open but blocked by a disputed invoice and a late payment on "
    "the prior term."
)


def load_seed_episodes() -> List[Episode]:
    """Return the validated list of day-zero + learned episodes."""

    episodes: List[Episode] = []

    # --- BASELINE: pre-learning. Three wrong calls, two right. ---------------

    # acme-corp: WRONG. System tried to retain a clearly expanding account with
    # a discount. Human rejected and wanted an expansion offer instead.
    episodes.append(
        _ep(
            "seed-acme-baseline",
            "acme-corp",
            SIT_ACME,
            "offer_save_concession",
            "Offer a retention concession",
            "Present a scoped discount to retain the account.",
            phase="baseline",
            decision="reject",
            nrr=98.0,
            arr=180000,
            preferred_action_key="propose_expansion_offer",
            reason="Account is healthy and expanding. Discounting leaves money on the table; should propose expansion.",
        )
    )

    # globex: WRONG. System picked a light-touch adoption campaign for a serious
    # renewal risk. Human wanted a senior save motion.
    episodes.append(
        _ep(
            "seed-globex-baseline",
            "globex",
            SIT_GLOBEX,
            "launch_adoption_campaign",
            "Launch a targeted adoption campaign",
            "Deliver in-app guidance on underused features.",
            phase="baseline",
            decision="reject",
            nrr=95.5,
            arr=240000,
            preferred_action_key="schedule_executive_business_review",
            reason="Sponsor is disengaged with renewal near. A campaign is too light; needs an executive business review.",
        )
    )

    # initech: WRONG. System chose to passively monitor a stalling onboarding.
    # Human wanted to intervene with a taskforce.
    episodes.append(
        _ep(
            "seed-initech-baseline",
            "initech",
            SIT_INITECH,
            "monitor_no_action",
            "Monitor and hold",
            "Keep the account on a watch list.",
            phase="baseline",
            decision="reject",
            nrr=94.0,
            arr=120000,
            preferred_action_key="assign_onboarding_taskforce",
            reason="Onboarding is past due in the first 90 days. Monitoring wastes the activation window; assign a taskforce.",
        )
    )

    # umbrella-co: RIGHT. Escalation for a departed champion + support spike.
    episodes.append(
        _ep(
            "seed-umbrella-baseline",
            "umbrella-co",
            SIT_UMBRELLA,
            "open_executive_escalation",
            "Open an executive escalation",
            "Engage CS leadership and product to triage a remediation plan.",
            phase="baseline",
            decision="approve",
            nrr=101.0,
            arr=300000,
            reason="Correct: sponsor loss plus support spike warrants an executive escalation.",
        )
    )

    # soylent: RIGHT. Resolve the billing dispute blocking renewal.
    episodes.append(
        _ep(
            "seed-soylent-baseline",
            "soylent",
            SIT_SOYLENT,
            "resolve_billing_dispute",
            "Resolve the billing dispute",
            "Coordinate finance and CS to clear the dispute and confirm terms.",
            phase="baseline",
            decision="approve",
            nrr=100.5,
            arr=150000,
            reason="Correct: the dispute is the primary blocker to renewal.",
        )
    )

    # --- LEARNED: post-distillation re-decision of the SAME accounts. --------
    # The previously-wrong accounts now get the human-preferred action and are
    # accepted; projected NRR improves across the board.

    episodes.append(
        _ep(
            "seed-acme-learned",
            "acme-corp",
            SIT_ACME,
            "propose_expansion_offer",
            "Propose an expansion offer",
            "Package an upsell aligned to demonstrated value and seat growth.",
            phase="learned",
            decision="approve",
            nrr=112.0,
            arr=180000,
            created_at="2026-06-10T09:00:00+00:00",
            reason="Applied learned preference: expand healthy, growing accounts rather than discount them.",
        )
    )
    episodes.append(
        _ep(
            "seed-globex-learned",
            "globex",
            SIT_GLOBEX,
            "schedule_executive_business_review",
            "Schedule an executive business review",
            "Book a strategic review with the buying committee before renewal.",
            phase="learned",
            decision="approve",
            nrr=106.0,
            arr=240000,
            created_at="2026-06-10T09:05:00+00:00",
            reason="Applied learned preference: disengaged sponsor near renewal needs a senior save motion.",
        )
    )
    episodes.append(
        _ep(
            "seed-initech-learned",
            "initech",
            SIT_INITECH,
            "assign_onboarding_taskforce",
            "Assign an onboarding taskforce",
            "Bring in an onboarding specialist and SE to unblock activation.",
            phase="learned",
            decision="approve",
            nrr=104.0,
            arr=120000,
            created_at="2026-06-10T09:10:00+00:00",
            reason="Applied learned preference: intervene on overdue onboarding instead of monitoring.",
        )
    )
    episodes.append(
        _ep(
            "seed-umbrella-learned",
            "umbrella-co",
            SIT_UMBRELLA,
            "open_executive_escalation",
            "Open an executive escalation",
            "Engage CS leadership and product to triage a remediation plan.",
            phase="learned",
            decision="approve",
            nrr=103.0,
            arr=300000,
            created_at="2026-06-10T09:15:00+00:00",
            reason="Reinforced existing correct preference.",
        )
    )
    episodes.append(
        _ep(
            "seed-soylent-learned",
            "soylent",
            SIT_SOYLENT,
            "resolve_billing_dispute",
            "Resolve the billing dispute",
            "Coordinate finance and CS to clear the dispute and confirm terms.",
            phase="learned",
            decision="approve",
            nrr=102.0,
            arr=150000,
            created_at="2026-06-10T09:20:00+00:00",
            reason="Reinforced existing correct preference.",
        )
    )

    return episodes


# A json-shaped export, handy for inspection / fixtures.
SEED_EPISODES_JSON: List[Dict[str, Any]] = [e.model_dump() for e in load_seed_episodes()]
