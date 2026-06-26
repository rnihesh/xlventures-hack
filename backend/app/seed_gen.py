"""Deterministic synthetic seed generator.

Produces a rich, internally consistent corpus for every domain and writes it to
``backend/seeds/<domain>/{accounts,documents}.json`` in the exact schema the
existing loaders (``app.seed_data``, ``app.retrieval.store``) already expect.

The generator is fully deterministic (fixed RNG seeds) so re-running it yields
byte-identical files: the seed corpus is data under version control, not a
random fixture. Every document is built from a single per-account "story" so
meeting notes, transcripts, tickets, usage, and CRM notes all corroborate the
same facts and are safe to cite.

Run it with::

    python -m app.seed_gen           # regenerate all domains
    python -m app.seed_gen --domain customer_success

It writes no run history and no learning episodes: the learning loop starts
empty and fills from real runs only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _seeds_root() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent / "seeds"  # backend/seeds


def _write(domain: str, accounts: List[dict], documents: List[dict]) -> None:
    root = _seeds_root() / domain
    root.mkdir(parents=True, exist_ok=True)
    with (root / "accounts.json").open("w", encoding="utf-8") as fh:
        json.dump(accounts, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with (root / "documents.json").open("w", encoding="utf-8") as fh:
        json.dump(documents, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _email(name: str) -> str:
    return name.lower().replace(" ", ".").replace("'", "") + "@example.com"


def _pct(active: int, seats: int) -> int:
    return int(round(100 * active / seats)) if seats else 0


OWNERS = [
    "Priya Nair", "Marcus Lee", "Dana Whitfield", "Sofia Romero",
    "James Okafor", "Elena Petrova", "Tara Mensah", "Devon Pierce",
    "Hana Kim", "Mateo Alvarez", "Aisha Bello", "Lukas Novak",
]

CONTACTS = [
    "Karim Haddad", "Lena Ortiz", "Sven Larsson", "Maya Chen", "Tom Becker",
    "Ravi Menon", "Grace Owens", "Diego Castro", "Nadia Petrosyan",
    "Felix Wagner", "Bianca Rossi", "Omar Khalil", "Wendy Zhao", "Paul Adler",
    "Ingrid Solberg", "Carlos Mendez", "Yuki Tanaka", "Sara Lindqvist",
]


# ===========================================================================
# Customer Success
# ===========================================================================
CS_INDUSTRIES = [
    "Freight & Logistics", "B2B SaaS / Analytics", "EdTech",
    "Industrial Manufacturing", "Financial Services", "Omnichannel Retail",
    "Healthcare Technology", "Travel & Hospitality", "Insurance",
    "Telecommunications", "Media & Entertainment", "Energy & Utilities",
    "Professional Services", "Gaming", "AgTech", "Construction Tech",
    "Marketing Technology", "Cybersecurity", "Real Estate Tech", "Biotech",
]

# scenario -> (risk_level, health range, sentiment, signals)
CS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "escalation": {
        "risk": "critical", "health": (30, 42), "sentiment": "strongly_negative",
        "signals": ["support_ticket_spike", "negative_sentiment", "nps_detractor"],
    },
    "health_drop": {
        "risk": "high", "health": (38, 50), "sentiment": "negative",
        "signals": ["usage_drop", "login_decline", "champion_departure"],
    },
    "renewal_risk": {
        "risk": "high", "health": (44, 58), "sentiment": "mixed",
        "signals": ["renewal_window_open", "qbr_missed", "competitor_eval"],
    },
    "onboarding_stall": {
        "risk": "medium", "health": (50, 62), "sentiment": "neutral",
        "signals": ["onboarding_milestone_late", "login_decline", "qbr_missed"],
    },
    "adoption_gap": {
        "risk": "medium", "health": (55, 68), "sentiment": "neutral",
        "signals": ["feature_abandonment", "login_decline"],
    },
    "champion_change": {
        "risk": "medium", "health": (52, 66), "sentiment": "mixed",
        "signals": ["champion_departure", "stakeholder_change"],
    },
    "expansion_signal": {
        "risk": "low", "health": (80, 92), "sentiment": "very_positive",
        "signals": ["seat_growth", "expansion_intent"],
    },
    "steady": {
        "risk": "low", "health": (74, 88), "sentiment": "positive",
        "signals": [],
    },
}

# Distribution: controls how many accounts of each scenario (sums to 26).
CS_DISTRIBUTION = (
    ["escalation"] * 2
    + ["health_drop"] * 4
    + ["renewal_risk"] * 4
    + ["onboarding_stall"] * 3
    + ["adoption_gap"] * 3
    + ["champion_change"] * 3
    + ["expansion_signal"] * 3
    + ["steady"] * 4
)

CS_NAMES = [
    "Northwind Logistics", "Helios Analytics", "Brightpath Education",
    "Atlas Manufacturing", "Vertex Financial", "Cobalt Retail Group",
    "Meridian Health Systems", "Voyage Hospitality", "Sentinel Insurance",
    "Lumen Telecom", "Cascade Media", "Aurora Energy", "Keystone Advisory",
    "Pixel Forge Games", "Harvest AgTech", "Ironclad Construction",
    "Beacon Marketing Cloud", "Citadel Security", "Anchor Realty",
    "Helix Biolabs", "Summit Freight", "Orchard Learning", "Quartz Robotics",
    "Tideway Bank", "Evergreen Retail", "Falcon Telematics",
]

SEGMENTS = {
    "Enterprise": {"seats": (120, 300), "arr": (240000, 600000)},
    "Mid-Market": {"seats": (50, 120), "arr": (80000, 220000)},
    "SMB": {"seats": (10, 45), "arr": (18000, 70000)},
}
REGIONS = ["North America", "EMEA", "APAC", "LATAM"]
LIFECYCLE = {
    "escalation": "at_risk",
    "health_drop": "at_risk",
    "renewal_risk": "renewal",
    "onboarding_stall": "onboarding",
    "adoption_gap": "adoption",
    "champion_change": "adoption",
    "expansion_signal": "expansion",
    "steady": "established",
}


def _cs_renewal(rng: random.Random, scenario: str) -> str:
    # At-risk and renewal scenarios renew sooner; healthy ones later.
    if scenario in ("escalation", "health_drop", "renewal_risk"):
        month = rng.choice([8, 9, 10, 11])
        year = 2026
    elif scenario in ("onboarding_stall", "champion_change", "adoption_gap"):
        month = rng.choice([11, 12, 1, 2])
        year = 2026 if month >= 11 else 2027
    else:
        month = rng.choice([2, 3, 4, 5, 6])
        year = 2027
    day = rng.randint(1, 27)
    return f"{year}-{month:02d}-{day:02d}"


def build_cs() -> tuple[List[dict], List[dict]]:
    rng = random.Random(20260626)
    accounts: List[dict] = []

    for i, scenario in enumerate(CS_DISTRIBUTION):
        spec = CS_SCENARIOS[scenario]
        name = CS_NAMES[i]
        segment = rng.choices(
            ["Enterprise", "Mid-Market", "SMB"], weights=[4, 5, 3]
        )[0]
        srange = SEGMENTS[segment]
        seats = rng.randint(*srange["seats"])
        arr = int(round(rng.randint(*srange["arr"]) / 1000) * 1000)
        health = rng.randint(*spec["health"])

        # Active seats reflect the scenario (low utilisation when at risk).
        if scenario in ("escalation", "health_drop"):
            util = rng.uniform(0.40, 0.62)
        elif scenario in ("onboarding_stall",):
            util = rng.uniform(0.18, 0.40)
        elif scenario in ("adoption_gap", "champion_change", "renewal_risk"):
            util = rng.uniform(0.60, 0.82)
        elif scenario == "expansion_signal":
            util = rng.uniform(0.92, 0.99)
        else:
            util = rng.uniform(0.82, 0.95)
        active = max(1, min(seats, int(round(seats * util))))

        owner = OWNERS[i % len(OWNERS)]
        renewal = _cs_renewal(rng, scenario)
        story = _cs_story(rng, name, scenario, seats, active, arr, renewal, owner)

        acc = {
            "account_id": f"ACC-{1001 + i}",
            "name": name,
            "arr": arr,
            "health_score": health,
            "risk_level": spec["risk"],
            "industry": CS_INDUSTRIES[i % len(CS_INDUSTRIES)],
            "segment": segment,
            "region": rng.choice(REGIONS),
            "seats": seats,
            "active_seats": active,
            "owner": owner,
            "owner_email": _email(owner),
            "lifecycle_stage": LIFECYCLE[scenario],
            "scenario": scenario,
            "renewal_date": renewal,
            "contract_term_months": rng.choice([12, 12, 12, 24, 36]),
            "sentiment": spec["sentiment"],
            "last_signal": story["last_signal"],
            "active_signals": list(spec["signals"]),
            "summary": story["summary"],
        }
        acc["_story"] = story  # transient, stripped before write
        accounts.append(acc)

    documents = _cs_documents(rng, accounts)
    for acc in accounts:
        acc.pop("_story", None)
    documents.extend(_cs_shared())
    return accounts, documents


def _cs_story(
    rng: random.Random, name: str, scenario: str, seats: int, active: int,
    arr: int, renewal: str, owner: str,
) -> Dict[str, Any]:
    util = _pct(active, seats)
    champ = rng.choice(CONTACTS)
    admin = rng.choice([c for c in CONTACTS if c != champ])
    exec_name = rng.choice([c for c in CONTACTS if c not in (champ, admin)])
    arr_k = f"{arr // 1000}k"
    tnum = rng.randint(4400, 4999)

    if scenario == "health_drop":
        prior = int(round(active / max(0.5, util / 100) * 0.80))
        return {
            "last_signal": f"Weekly active users down {rng.randint(28, 42)}% MoM",
            "summary": (
                f"Usage fell sharply after an integration broke and the champion "
                f"departed. Seat utilisation is {util}% ({active} of {seats}). Risk "
                f"is product-reliability and relationship, not commercial: it needs "
                f"an integration fix sprint plus executive re-engagement before the "
                f"{renewal} renewal."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": "carrier API change broke the core integration on May 28",
            "root_cause": "sync jobs began failing silently after a third-party API change",
            "ticket": (tnum, "High", "Integration sync jobs failing since May 28"),
            "wau_series": "96, 94, 91, 88, 71, 64, 59, 57",
            "next_step": "restore the integration this week and book a VP re-engagement",
            "csat": (2, "The tool stopped showing live data and we lost time before anyone explained why."),
            "arr_k": arr_k, "util": util, "renewal": renewal,
        }
    if scenario == "escalation":
        return {
            "last_signal": "Sev-1 outage during quarter close; exec escalation open",
            "summary": (
                f"A Sev-1 outage during quarter-end triggered a formal executive "
                f"escalation with explicit churn language. Highest-priority account "
                f"this week: same-day VP apology, RCA within 48 hours, a remediation "
                f"roadmap, proactive SLA credit, and a weekly exec check-in before "
                f"the {renewal} renewal."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": "a six-hour Sev-1 outage during quarter-end close",
            "root_cause": "a failed deploy degraded the primary data pipeline",
            "ticket": (tnum, "Critical", "Sev-1 outage during quarter close"),
            "wau_series": "210, 208, 205, 201, 0, 188, 190, 192",
            "next_step": "deliver RCA in 48h, an SLA credit, and a weekly exec check-in",
            "csat": (1, "An outage during our close window is unacceptable; we are reviewing alternatives."),
            "arr_k": arr_k, "util": util, "renewal": renewal,
        }
    if scenario == "renewal_risk":
        return {
            "last_signal": f"Renewal in {rng.randint(45, 80)} days; new VP evaluating competitor",
            "summary": (
                f"Strong adoption ({util}% of seats active) but a newly hired VP with "
                f"no relationship is running a competitive evaluation and procurement "
                f"wants a discount. The risk is relationship and commercial, not value. "
                f"Lead with an ROI business review, then counter with a multi-year "
                f"structure before the {renewal} renewal."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": "a new VP opened a competitive evaluation",
            "root_cause": "leadership change with no executive relationship to the platform",
            "ticket": (tnum, "Medium", "Procurement requesting a renewal discount"),
            "wau_series": "171, 173, 170, 174, 172, 175, 176, 174",
            "next_step": "run an ROI business review, then propose a multi-year structure",
            "csat": (4, "The product works well; the question is price and the new VP's preferences."),
            "arr_k": arr_k, "util": util, "renewal": renewal,
        }
    if scenario == "onboarding_stall":
        return {
            "last_signal": f"Day-45 onboarding: {rng.randint(2, 3)} of 7 milestones complete",
            "summary": (
                f"Onboarding is behind plan at day 45 because the customer's admin is "
                f"consumed by other work. Cooperative but capacity-constrained, with "
                f"only {util}% of seats active. Needs an onboarding rescue: an "
                f"implementation specialist, a two-week milestone sprint, async "
                f"training, and a sponsor checkpoint."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": "onboarding milestones slipped past the day-45 plan",
            "root_cause": "the customer admin lacks bandwidth to drive configuration",
            "ticket": (tnum, "Medium", "Onboarding milestones behind plan at day 45"),
            "wau_series": "8, 9, 11, 10, 12, 11, 13, 12",
            "next_step": "assign an implementation specialist and run a two-week sprint",
            "csat": (3, "We are keen but stretched thin; we need more hands-on help to go live."),
            "arr_k": arr_k, "util": util, "renewal": renewal,
        }
    if scenario == "adoption_gap":
        return {
            "last_signal": "Analytics module adoption reversed; logins down 12% MoM",
            "summary": (
                f"Core product is sticky but the analytics module never landed, so "
                f"value is partial and a renewal case is thin. Seat utilisation is "
                f"{util}%. Needs a targeted adoption campaign and an enablement "
                f"session on the underused module before {renewal}."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": "the analytics module was adopted then abandoned",
            "root_cause": "teams never received enablement on the advanced module",
            "ticket": (tnum, "Low", "Request for analytics module training"),
            "wau_series": "84, 86, 85, 83, 80, 79, 78, 77",
            "next_step": "launch an in-app adoption campaign and a live enablement session",
            "csat": (4, "The basics are great; we just never got the analytics piece working for us."),
            "arr_k": arr_k, "util": util, "renewal": renewal,
        }
    if scenario == "champion_change":
        return {
            "last_signal": "Primary champion moved roles; new sponsor unmapped",
            "summary": (
                f"The day-to-day champion changed roles and a new sponsor is not yet "
                f"mapped, leaving the relationship thin even though usage holds at "
                f"{util}%. Needs a fast stakeholder re-mapping and a value recap with "
                f"the incoming owner before momentum fades."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": "the primary champion moved to a different team",
            "root_cause": "relationship concentration on a single departed stakeholder",
            "ticket": (tnum, "Low", "Reassign account contacts after champion change"),
            "wau_series": "120, 121, 119, 122, 120, 118, 121, 120",
            "next_step": "re-map stakeholders and run a value recap with the new sponsor",
            "csat": (4, "Things still work; I am just getting up to speed as the new owner."),
            "arr_k": arr_k, "util": util, "renewal": renewal,
        }
    if scenario == "expansion_signal":
        new_seats = rng.randint(40, 80)
        return {
            "last_signal": f"Hit {util}% seat utilisation; {rng.randint(2, 4)} new teams piloting",
            "summary": (
                f"Seat-saturated promoter with several teams borrowing logins and an "
                f"approved budget. Utilisation is {util}% ({active} of {seats}). A "
                f"product-qualified expansion worth roughly +{new_seats} seats, plus a "
                f"reference and case-study opportunity."
            ),
            "champion": champ, "admin": admin, "exec": exec_name,
            "incident": f"seat saturation at {util}% with {rng.randint(2, 4)} teams piloting",
            "root_cause": "demonstrated value driving unsanctioned cross-team adoption",
            "ticket": (tnum, "Medium", "Enable SSO/SCIM ahead of a seat expansion"),
            "wau_series": f"{active-6}, {active-5}, {active-4}, {active-3}, {active-2}, {active-1}, {active}, {active}",
            "next_step": f"build a {new_seats}-seat expansion proposal with SSO/SCIM included",
            "csat": (5, "We consider you standard tooling; we are basically out of seats."),
            "arr_k": arr_k, "util": util, "renewal": renewal, "new_seats": new_seats,
        }
    # steady
    return {
        "last_signal": "Steady usage; strong NPS from economic buyer",
        "summary": (
            f"Healthy, steady account with a reference-willing promoter and one minor "
            f"enhancement request. Utilisation is {util}%. No churn risk: a future "
            f"expansion candidate to nurture rather than an active save today."
        ),
        "champion": champ, "admin": admin, "exec": exec_name,
        "incident": "no material risk event this quarter",
        "root_cause": "n/a, the account is healthy",
        "ticket": (tnum, "Low", "Minor enhancement request on reporting export"),
        "wau_series": f"{active-3}, {active-2}, {active-1}, {active}, {active}, {active}, {active}, {active}",
        "next_step": "nurture the relationship and line up a Q4 expansion conversation",
        "csat": (5, "Solid product and responsive team; we would happily be a reference."),
        "arr_k": arr_k, "util": util, "renewal": renewal,
    }


def _cs_documents(rng: random.Random, accounts: List[dict]) -> List[dict]:
    docs: List[dict] = []
    for acc in accounts:
        s = acc["_story"]
        aid = acc["account_id"]
        name = acc["name"]
        owner = acc["owner"]
        seats = acc["seats"]
        active = acc["active_seats"]
        arr = acc["arr"]
        renewal = acc["renewal_date"]
        tnum, tprio, ttitle = s["ticket"]

        # Always-present core documents (5).
        docs.append({
            "id": f"DOC-{aid}-MN", "account_id": aid, "source_type": "meeting_notes",
            "title": f"{name} - Weekly CS Sync",
            "text": (
                f"Attendees: {owner} (CSM); {s['champion']} (customer).\n"
                f"Context: {name} is at {arr // 1000}k ARR across {seats} licensed seats, "
                f"renewing {renewal}. Seat utilisation is {s['util']}% ({active} of {seats}).\n"
                f"Discussion: {s['incident'].capitalize()}. Root cause hypothesis: "
                f"{s['root_cause']}.\n"
                f"Agreed next step: {s['next_step']}. Owner: {owner}."
            ),
        })
        docs.append({
            "id": f"DOC-{aid}-CT", "account_id": aid, "source_type": "call_transcript",
            "title": f"{name} - Customer Call",
            "text": (
                f"Customer ({s['champion']}): {s['csat'][1]}\n"
                f"CSM ({owner}): Understood. That lines up with {s['incident']}. "
                f"If we {s['next_step']}, would that put us back on track?\n"
                f"Customer ({s['champion']}): It would help. Let us see the plan and timeline.\n"
                f"CSM ({owner}): I will send a written plan today and confirm the {renewal} renewal path."
            ),
        })
        docs.append({
            "id": f"DOC-{aid}-ST", "account_id": aid, "source_type": "support_tickets",
            "title": f"{name} - Open Support Tickets",
            "text": (
                f"Ticket {aid[-4:]}-{tnum} (Priority: {tprio}, Status: Open). "
                f"Title: {ttitle}. Description: Reported by {s['admin']}; "
                f"{s['root_cause']}. Engineering and CS are coordinating on "
                f"{s['next_step']}."
            ),
        })
        docs.append({
            "id": f"DOC-{aid}-CRM", "account_id": aid, "source_type": "crm_notes",
            "title": f"{name} - CRM Account Notes",
            "text": (
                f"Stage: {acc['lifecycle_stage']}. Sentiment: {acc['sentiment']}.\n"
                f"Key contacts: {s['champion']} (primary), {s['admin']} (day-to-day admin), "
                f"{s['exec']} (executive sponsor).\n"
                f"ARR {arr // 1000}k, {seats} seats, renewal {renewal}, health {acc['health_score']}.\n"
                f"Active signals: {', '.join(acc['active_signals']) or 'none'}.\n"
                f"Open risk and motion: {s['summary']}"
            ),
        })
        docs.append({
            "id": f"DOC-{aid}-US", "account_id": aid, "source_type": "usage_summary",
            "title": f"{name} - Product Usage Summary (trailing 8 weeks)",
            "text": (
                f"Weekly active users by week: {s['wau_series']}. "
                f"Seat utilisation is {s['util']}% ({active} of {seats} licensed seats). "
                f"This usage pattern is consistent with {s['incident']}. "
                f"Recommendation flag: {s['last_signal']}."
            ),
        })

        # Optional documents to reach 5-8.
        extra_pool = [
            {
                "id": f"DOC-{aid}-SR", "account_id": aid, "source_type": "survey_response",
                "title": f"{name} - CSAT Survey",
                "text": (
                    f"Survey type: Post-interaction CSAT. Score: {s['csat'][0]} of 5. "
                    f"Respondent: {s['admin']}.\n"
                    f"Verbatim: '{s['csat'][1]}'\n"
                    f"This reading is consistent with the account's {acc['sentiment']} sentiment."
                ),
            },
            {
                "id": f"DOC-{aid}-BL", "account_id": aid, "source_type": "billing_events",
                "title": f"{name} - Billing and Invoice History",
                "text": (
                    f"Annual invoice for {arr // 1000}k issued and paid within terms; "
                    f"payment history is clean with no open billing dispute. The renewal "
                    f"invoice for the {renewal} term has not yet been issued. Note for the "
                    f"motion: there is no payment friction, so the play should lead with "
                    f"{s['next_step']} rather than a pricing concession."
                ),
            },
            {
                "id": f"DOC-{aid}-EML", "account_id": aid, "source_type": "crm_notes",
                "title": f"{name} - Stakeholder Email Recap",
                "text": (
                    f"From {owner} to {s['exec']}: Recapping our position on {name}. "
                    f"{s['incident'].capitalize()}. We propose to {s['next_step']} and will "
                    f"review progress at the next checkpoint ahead of the {renewal} renewal."
                ),
            },
        ]
        n_extra = rng.randint(0, 3)
        for extra in extra_pool[:n_extra]:
            docs.append(extra)

    return docs


def _cs_shared() -> List[dict]:
    kb = [
        ("KB-001", "Health score model and risk thresholds",
         "The health score blends product usage (seat utilisation and weekly active "
         "users), relationship strength (mapped sponsor, NPS), and commercial signals "
         "(renewal window, billing disputes). A drop of 20% or more in weekly active "
         "users month over month crosses the high-risk threshold and triggers a save "
         "review. Critical risk is reserved for executive escalations and Sev-1 incidents."),
        ("KB-002", "Stakeholder mapping and champion continuity",
         "Every account should map at least three contacts: a day-to-day champion, an "
         "administrator, and an executive sponsor. When a champion departs, re-map within "
         "two weeks and run a value recap with the incoming owner. Relationship "
         "concentration on a single contact is a leading churn indicator."),
        ("KB-003", "Seat utilisation and expansion qualification",
         "Seat utilisation above 90% with active cross-team interest is a product-qualified "
         "expansion signal. Confirm an approved budget, then package an upsell aligned to "
         "demonstrated value, including SSO and SCIM for clean provisioning at scale."),
        ("KB-004", "Renewal motion and competitive defense",
         "Open the renewal motion 90 days out. When a new buyer runs a competitive "
         "evaluation, lead with an ROI business review grounded in realised value, then "
         "counter price pressure with a multi-year structure rather than a flat discount."),
        ("KB-005", "Onboarding milestones and time to value",
         "Healthy onboarding hits 7 milestones by day 60. When milestones slip past plan, "
         "assign an implementation specialist, compress the work into a two-week sprint, "
         "and add async training so a single overloaded admin is not the bottleneck."),
        ("KB-006", "Incident response and executive escalation",
         "For a Sev-1 incident or an executive escalation, deliver a same-day apology from "
         "leadership, a root cause analysis within 48 hours, a remediation roadmap, a "
         "proactive SLA credit, and a weekly executive check-in until trust is restored."),
    ]
    plays = [
        ("PLAY-HEALTH-DROP", "Reverse a usage decline",
         "1) Confirm the technical root cause and open an engineering ticket. 2) Restore "
         "the broken capability with a fix sprint. 3) Re-engage the executive sponsor. "
         "4) Track weekly active users back to baseline before the renewal."),
        ("PLAY-RENEWAL", "Defend an at-risk renewal",
         "1) Quantify realised value in an ROI business review. 2) Map and meet the new "
         "decision maker. 3) Counter discount pressure with a multi-year structure. "
         "4) Confirm terms and close the renewal."),
        ("PLAY-ONBOARD", "Rescue a stalled onboarding",
         "1) Assign an implementation specialist. 2) Compress milestones into a two-week "
         "sprint. 3) Provide async training for the admin. 4) Hold a sponsor checkpoint at go-live."),
        ("PLAY-ESCALATION", "Run an executive escalation",
         "1) Same-day VP apology. 2) RCA within 48 hours. 3) Remediation roadmap and SLA "
         "credit. 4) Weekly executive check-in until health recovers."),
        ("PLAY-EXPANSION", "Convert a product-qualified expansion",
         "1) Confirm seat saturation and approved budget. 2) Package a seat expansion with "
         "SSO/SCIM. 3) Propose volume pricing. 4) Capture a reference or case study."),
    ]
    docs = []
    for kid, title, text in kb:
        docs.append({"id": kid, "source_type": "kb_article",
                     "title": title, "text": text})
    for pid, title, text in plays:
        docs.append({"id": pid, "source_type": "playbook",
                     "title": title, "text": text})
    return docs


# ===========================================================================
# Collections (accounts receivable)
# ===========================================================================
COL_NAMES = [
    "Riverstone Builders", "Cardinal Freight Systems", "Harbor Point Foods",
    "Granite Peak Supply", "Lakeshore Apparel", "Summit Auto Parts",
    "Beacon Hospitality Group", "Ironwood Furniture", "Coastal Print Works",
    "Highland Dairy Co",
]
COL_INDUSTRIES = [
    "Construction", "Logistics", "Food & Beverage", "Wholesale Distribution",
    "Apparel & Retail", "Automotive", "Hospitality", "Manufacturing",
    "Printing & Packaging", "Agriculture",
]
COL_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "early_stage_overdue": {"risk": "low", "dpd": (5, 28), "bucket": "1-30",
                            "sentiment": "neutral", "signals": ["invoice_past_due", "no_remittance_response"]},
    "broken_promise": {"risk": "high", "dpd": (35, 60), "bucket": "31-60",
                       "sentiment": "negative", "signals": ["high_value_overdue", "broken_promise_to_pay"]},
    "dispute_block": {"risk": "medium", "dpd": (30, 55), "bucket": "31-60",
                      "sentiment": "mixed", "signals": ["invoice_disputed", "short_payment"]},
    "pre_writeoff": {"risk": "high", "dpd": (95, 150), "bucket": "90+",
                     "sentiment": "strongly_negative", "signals": ["bankruptcy_signal", "broken_promise_to_pay"]},
    "partial_payer": {"risk": "medium", "dpd": (40, 70), "bucket": "61-90",
                      "sentiment": "neutral", "signals": ["partial_payment", "slow_payer"]},
}
COL_DISTRIBUTION = (
    ["early_stage_overdue"] * 3
    + ["broken_promise"] * 2
    + ["dispute_block"] * 2
    + ["pre_writeoff"] * 1
    + ["partial_payer"] * 2
)


def build_collections() -> tuple[List[dict], List[dict]]:
    rng = random.Random(20260627)
    accounts: List[dict] = []
    for i, scenario in enumerate(COL_DISTRIBUTION):
        spec = COL_SCENARIOS[scenario]
        dpd = rng.randint(*spec["dpd"])
        segment = rng.choices(["Enterprise", "Mid-Market", "SMB"], weights=[3, 5, 3])[0]
        if segment == "Enterprise":
            balance = rng.randint(120000, 320000)
        elif segment == "Mid-Market":
            balance = rng.randint(35000, 120000)
        else:
            balance = rng.randint(6000, 35000)
        balance = int(round(balance / 50) * 50)
        owner = OWNERS[(i + 6) % len(OWNERS)]
        credit = int(round(balance * rng.uniform(1.1, 1.8) / 1000) * 1000)
        story = _col_story(rng, COL_NAMES[i], scenario, balance, dpd, owner, credit)
        # health_score = inverse of recovery risk so the shared inbox renders it.
        health = {"low": rng.randint(72, 85), "medium": rng.randint(45, 62),
                  "high": rng.randint(12, 35)}[spec["risk"]]
        acc = {
            "account_id": f"AR-{2001 + i}",
            "name": COL_NAMES[i],
            "balance_due": balance,
            "currency": "USD",
            "health_score": health,
            "days_past_due": dpd,
            "aging_bucket": spec["bucket"],
            "risk_level": spec["risk"],
            "industry": COL_INDUSTRIES[i % len(COL_INDUSTRIES)],
            "segment": segment,
            "region": rng.choice(REGIONS),
            "owner": owner,
            "owner_email": _email(owner),
            "credit_limit": credit,
            "payment_terms": rng.choice(["net-30", "net-45", "net-60"]),
            "lifecycle_stage": "collections",
            "scenario": scenario,
            "sentiment": spec["sentiment"],
            "last_signal": story["last_signal"],
            "active_signals": list(spec["signals"]),
            "summary": story["summary"],
        }
        acc["_story"] = story
        accounts.append(acc)

    documents = _col_documents(rng, accounts)
    for acc in accounts:
        acc.pop("_story", None)
    documents.extend(_col_shared())
    return accounts, documents


def _col_story(rng, name, scenario, balance, dpd, owner, credit) -> Dict[str, Any]:
    contact = rng.choice(CONTACTS)
    bal = f"${balance:,}"
    inv = rng.randint(40000, 49999)
    common = {"contact": contact, "balance": bal, "invoice": f"INV-{inv}",
              "owner": owner, "dpd": dpd, "credit": f"${credit:,}"}
    if scenario == "early_stage_overdue":
        common.update({
            "last_signal": f"Invoice {dpd} days past due; first reminder unanswered",
            "summary": (f"A reliable payer with one invoice {dpd} days past due and no open "
                        f"dispute. Routine early dunning (reminder, then a call) should clear "
                        f"{bal} without straining the relationship."),
            "next_step": "send a second reminder, then place a courtesy call",
            "promise": "no promise to pay on file yet",
        })
    elif scenario == "broken_promise":
        common.update({
            "last_signal": f"{bal} overdue; first promise to pay was missed",
            "summary": (f"A large balance of {bal} is {dpd} days past due and the first "
                        f"promise to pay was missed. Escalate to a structured payment plan "
                        f"with management sign-off and a credit hold if the next commitment slips."),
            "next_step": "escalate to a structured payment plan and apply a credit hold",
            "promise": "first promise to pay missed on the agreed date",
        })
    elif scenario == "dispute_block":
        common.update({
            "last_signal": f"Payment withheld pending an invoice dispute ({bal})",
            "summary": (f"Payment of {bal} is blocked by a billing dispute, not unwillingness "
                        f"to pay. Resolve the dispute (pricing or proof of delivery) with "
                        f"finance, issue any credit memo, then confirm the corrected due date."),
            "next_step": "resolve the dispute with finance and reissue a corrected invoice",
            "promise": "payment withheld pending dispute resolution",
        })
    elif scenario == "pre_writeoff":
        common.update({
            "last_signal": f"{dpd}+ days past due; insolvency rumour and broken promises",
            "summary": (f"{bal} is {dpd} days past due with an insolvency rumour and repeated "
                        f"broken promises. Move to a pre-write-off motion: final demand, "
                        f"settlement offer, and a referral to a third-party agency if unresolved."),
            "next_step": "issue a final demand and prepare an agency referral",
            "promise": "multiple promises to pay broken",
        })
    else:  # partial_payer
        common.update({
            "last_signal": f"Partial payments only; {bal} balance remains {dpd} days past due",
            "summary": (f"The customer pays partially and slowly, leaving {bal} outstanding at "
                        f"{dpd} days. Negotiate a firm instalment schedule with auto-pay and "
                        f"monitor adherence before extending further credit."),
            "next_step": "agree a firm instalment schedule with auto-pay enrolment",
            "promise": "partial payments received against the balance",
        })
    return common


def _col_documents(rng, accounts) -> List[dict]:
    docs: List[dict] = []
    for acc in accounts:
        s = acc["_story"]
        aid = acc["account_id"]
        name = acc["name"]
        docs.append({
            "id": f"DOC-{aid}-INV", "account_id": aid, "source_type": "invoice_record",
            "title": f"{name} - Invoice {s['invoice']}",
            "text": (f"Invoice {s['invoice']} for {s['balance']} ({acc['payment_terms']}) is "
                     f"{s['dpd']} days past due, aging bucket {acc['aging_bucket']}. Customer "
                     f"credit limit is {s['credit']}. Status: {s['last_signal']}."),
        })
        docs.append({
            "id": f"DOC-{aid}-COMM", "account_id": aid, "source_type": "communication_log",
            "title": f"{name} - Collections Communication Log",
            "text": (f"Collector {s['owner']} contacted {s['contact']} regarding {s['balance']} "
                     f"outstanding. Outcome: {s['promise']}. Agreed next step: {s['next_step']}."),
        })
        docs.append({
            "id": f"DOC-{aid}-PAY", "account_id": aid, "source_type": "payment_record",
            "title": f"{name} - Payment History",
            "text": (f"Trailing payment history for {name}: a mix of on-time and late "
                     f"settlements; current balance {s['balance']} at {s['dpd']} days past due. "
                     f"This pattern is consistent with the {acc['scenario'].replace('_', ' ')} scenario."),
        })
        docs.append({
            "id": f"DOC-{aid}-CRM", "account_id": aid, "source_type": "credit_record",
            "title": f"{name} - Credit and Account Notes",
            "text": (f"Risk level {acc['risk_level']}, recovery health {acc['health_score']}. "
                     f"Credit limit {s['credit']}, terms {acc['payment_terms']}. "
                     f"Active signals: {', '.join(acc['active_signals'])}. Motion: {s['summary']}"),
        })
        if acc["scenario"] == "dispute_block":
            docs.append({
                "id": f"DOC-{aid}-DSP", "account_id": aid, "source_type": "dispute_case",
                "title": f"{name} - Open Dispute Case",
                "text": (f"Dispute opened by {s['contact']} on invoice {s['invoice']} for "
                         f"{s['balance']}. Reason: pricing and proof-of-delivery discrepancy. "
                         f"Resolution path: finance to validate and issue a credit memo, then "
                         f"reissue a corrected invoice and confirm the new due date."),
            })
    return docs


def _col_shared() -> List[dict]:
    kb = [
        ("KB-COL-001", "Aging buckets and escalation thresholds",
         "Invoices age through 1-30, 31-60, 61-90, and 90+ day buckets. Early buckets call "
         "for automated reminders and a courtesy call. By 60+ days, escalate to a structured "
         "payment plan; by 90+ days, move toward a final demand and possible agency referral."),
        ("KB-COL-002", "Promise to pay and credit holds",
         "Record every promise to pay with a date and amount. A broken promise raises risk and "
         "justifies a credit hold to stop new orders shipping against unpaid balances. Two or "
         "more broken promises should trigger management review."),
        ("KB-COL-003", "Dispute handling and short payments",
         "Treat a disputed or short-paid invoice as a process problem, not a refusal to pay. "
         "Route to finance for validation, issue a credit memo where warranted, and reissue a "
         "corrected invoice so the clock restarts on a clean balance."),
    ]
    plays = [
        ("PLAY-COL-AGING", "Work an aging balance",
         "1) Send the reminder sequence. 2) Place a courtesy call. 3) Confirm a promise to pay. "
         "4) Escalate to a payment plan if the promise slips."),
        ("PLAY-COL-DISPUTE", "Resolve a disputed invoice",
         "1) Log the dispute reason. 2) Validate with finance. 3) Issue any credit memo. "
         "4) Reissue a corrected invoice and confirm the due date."),
        ("PLAY-COL-PREWRITEOFF", "Pre-write-off recovery",
         "1) Issue a final demand. 2) Offer a settlement. 3) Apply a credit hold. "
         "4) Refer to a third-party agency if unresolved."),
    ]
    docs = []
    for kid, title, text in kb:
        docs.append({"id": kid, "source_type": "policy", "title": title, "text": text})
    for pid, title, text in plays:
        docs.append({"id": pid, "source_type": "playbook", "title": title, "text": text})
    return docs


# ===========================================================================
# SaaS Sales (pipeline)
# ===========================================================================
SAAS_NAMES = [
    "Brightwave Media", "Cobalt Robotics", "Northgate Retail", "Pinecone Health",
    "Vanta Logistics", "Solstice Energy", "Mosaic Fintech", "Driftwood Travel",
    "Kestrel Security", "Lattice Manufacturing",
]
SAAS_INDUSTRIES = [
    "Media", "Manufacturing", "Retail", "Healthcare", "Logistics", "Energy",
    "Fintech", "Travel", "Cybersecurity", "Industrial",
]
SAAS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "deal_stall": {"risk": "medium", "stage": "Negotiation", "sentiment": "neutral",
                   "signals": ["stage_stall", "no_recent_activity"], "health": (45, 62)},
    "closing_signal": {"risk": "low", "stage": "Proposal", "sentiment": "positive",
                       "signals": ["buying_intent", "stakeholder_alignment"], "health": (66, 82)},
    "early_discovery": {"risk": "medium", "stage": "Discovery", "sentiment": "neutral",
                        "signals": ["no_recent_activity"], "health": (40, 58)},
    "champion_risk": {"risk": "high", "stage": "Evaluation", "sentiment": "mixed",
                      "signals": ["stage_stall", "stakeholder_change"], "health": (35, 52)},
}
SAAS_DISTRIBUTION = (
    ["deal_stall"] * 3 + ["closing_signal"] * 3 + ["early_discovery"] * 2 + ["champion_risk"] * 2
)


def build_saas_sales() -> tuple[List[dict], List[dict]]:
    rng = random.Random(20260628)
    accounts: List[dict] = []
    for i, scenario in enumerate(SAAS_DISTRIBUTION):
        spec = SAAS_SCENARIOS[scenario]
        segment = rng.choices(["Enterprise", "Mid-Market", "SMB"], weights=[4, 4, 3])[0]
        if segment == "Enterprise":
            deal = rng.randint(90000, 280000)
        elif segment == "Mid-Market":
            deal = rng.randint(35000, 90000)
        else:
            deal = rng.randint(9000, 35000)
        deal = int(round(deal / 1000) * 1000)
        owner = OWNERS[(i + 3) % len(OWNERS)]
        month = rng.choice([8, 9, 10, 11, 12])
        close_date = f"2026-{month:02d}-{rng.randint(1, 27):02d}"
        story = _saas_story(rng, SAAS_NAMES[i], scenario, deal, owner, spec["stage"], close_date)
        health = rng.randint(*spec["health"])
        acc = {
            "account_id": f"OPP-{3001 + i}",
            "name": SAAS_NAMES[i],
            "deal_size": deal,
            "arr": 0,
            "currency": "USD",
            "health_score": health,
            "risk_level": spec["risk"],
            "industry": SAAS_INDUSTRIES[i % len(SAAS_INDUSTRIES)],
            "segment": segment,
            "region": rng.choice(REGIONS),
            "owner": owner,
            "owner_email": _email(owner),
            "stage": spec["stage"],
            "lifecycle_stage": "pipeline",
            "scenario": scenario,
            "close_date": close_date,
            "sentiment": spec["sentiment"],
            "last_signal": story["last_signal"],
            "active_signals": list(spec["signals"]),
            "summary": story["summary"],
        }
        acc["_story"] = story
        accounts.append(acc)

    documents = _saas_documents(rng, accounts)
    for acc in accounts:
        acc.pop("_story", None)
    documents.extend(_saas_shared())
    return accounts, documents


def _saas_story(rng, name, scenario, deal, owner, stage, close_date) -> Dict[str, Any]:
    champ = rng.choice(CONTACTS)
    buyer = rng.choice([c for c in CONTACTS if c != champ])
    d = f"${deal:,}"
    common = {"champion": champ, "buyer": buyer, "deal": d, "owner": owner,
              "stage": stage, "close_date": close_date}
    if scenario == "deal_stall":
        days = rng.randint(14, 30)
        common.update({
            "last_signal": f"Stuck in {stage} {days} days; no buyer reply in {rng.randint(7, 12)} days",
            "summary": (f"A {d} opportunity has stalled in {stage} for {days} days with no recent "
                        f"buyer activity. Confirm the blocker with the champion, send a tailored "
                        f"value recap, and propose a concrete next step before the {close_date} target."),
            "blocker": "the economic buyer has gone quiet pending an internal budget review",
            "next_step": "confirm the blocker with the champion and send a value recap",
        })
    elif scenario == "closing_signal":
        common.update({
            "last_signal": "Champion requested final pricing; economic buyer engaged",
            "summary": (f"A {d} opportunity in {stage} shows clear readiness to close: the champion "
                        f"asked for final pricing and the economic buyer is looped in. Send a "
                        f"closing proposal with terms and a mutual close plan toward {close_date}."),
            "blocker": "none material; the buyer is ready to move",
            "next_step": "send a closing proposal with pricing, terms, and a mutual close plan",
        })
    elif scenario == "early_discovery":
        common.update({
            "last_signal": "Discovery underway; awaiting stakeholder confirmation",
            "summary": (f"A {d} opportunity is early in {stage} with one champion but no confirmed "
                        f"economic buyer. Run multi-threaded discovery to map the buying committee "
                        f"and quantify the problem before advancing the stage."),
            "blocker": "the buying committee is not yet mapped",
            "next_step": "multi-thread into the buying committee and quantify the pain",
        })
    else:  # champion_risk
        common.update({
            "last_signal": f"Stalled in {stage}; primary champion changed roles",
            "summary": (f"A {d} opportunity in {stage} is at risk after the primary champion "
                        f"changed roles. Re-establish a new internal sponsor and re-validate the "
                        f"business case before the {close_date} target slips."),
            "blocker": "the original champion left and no new sponsor is confirmed",
            "next_step": "identify and develop a new champion, then re-validate the business case",
        })
    return common


def _saas_documents(rng, accounts) -> List[dict]:
    docs: List[dict] = []
    for acc in accounts:
        s = acc["_story"]
        aid = acc["account_id"]
        name = acc["name"]
        docs.append({
            "id": f"DOC-{aid}-CRM", "account_id": aid, "source_type": "crm_record",
            "title": f"{name} - Opportunity Record",
            "text": (f"Opportunity {name}: {s['deal']} in {s['stage']}, target close {s['close_date']}, "
                     f"owner {s['owner']}. Risk {acc['risk_level']}. Signals: "
                     f"{', '.join(acc['active_signals'])}. Status: {s['last_signal']}."),
        })
        docs.append({
            "id": f"DOC-{aid}-NOTE", "account_id": aid, "source_type": "crm_note",
            "title": f"{name} - Deal Notes",
            "text": (f"Champion {s['champion']}; economic buyer {s['buyer']}. Current blocker: "
                     f"{s['blocker']}. Plan: {s['next_step']}."),
        })
        docs.append({
            "id": f"DOC-{aid}-CALL", "account_id": aid, "source_type": "call_transcript",
            "title": f"{name} - Discovery / Status Call",
            "text": (f"Buyer ({s['champion']}): Here is where we stand internally.\n"
                     f"AE ({s['owner']}): Understood. To keep momentum on a {s['deal']} deal toward "
                     f"{s['close_date']}, I will {s['next_step']}.\n"
                     f"Buyer ({s['champion']}): That works; send it over and we will review."),
        })
        docs.append({
            "id": f"DOC-{aid}-EML", "account_id": aid, "source_type": "crm_note",
            "title": f"{name} - Buyer Email Thread",
            "text": (f"From {s['owner']} to {s['buyer']}: Recapping next steps on {name} ({s['deal']}). "
                     f"Blocker noted: {s['blocker']}. Proposed action: {s['next_step']} ahead of {s['close_date']}."),
        })
        if acc["scenario"] in ("closing_signal", "champion_risk"):
            docs.append({
                "id": f"DOC-{aid}-MN", "account_id": aid, "source_type": "meeting_notes",
                "title": f"{name} - Deal Review",
                "text": (f"Deal review for {name} ({s['deal']}, {s['stage']}). {s['summary']} "
                         f"Forecast category set accordingly; next checkpoint before {s['close_date']}."),
            })
    return docs


def _saas_shared() -> List[dict]:
    kb = [
        ("KB-SAAS-001", "Stage definitions and exit criteria",
         "Each pipeline stage has explicit exit criteria: Discovery requires a quantified problem "
         "and a mapped buying committee; Evaluation requires a validated business case; Proposal "
         "requires agreed scope and pricing; Negotiation requires a mutual close plan. Do not "
         "advance a stage until its exit criteria are met."),
        ("KB-SAAS-002", "Multi-threading and champion development",
         "Single-threaded deals are fragile. Develop at least one champion plus an economic buyer, "
         "and re-map quickly when a stakeholder changes roles. A deal that loses its only champion "
         "should drop in forecast confidence until a new sponsor is confirmed."),
        ("KB-SAAS-003", "Closing motion and mutual close plans",
         "When buying intent and budget are confirmed, send a closing proposal with clear pricing "
         "and a mutual close plan that lists the steps and dates to signature. This protects deal "
         "velocity and forecast accuracy."),
    ]
    plays = [
        ("PLAY-SAAS-UNSTICK", "Unstick a stalled deal",
         "1) Confirm the blocker with the champion. 2) Send a tailored value recap. "
         "3) Propose a concrete next step and date. 4) Multi-thread if the buyer stays quiet."),
        ("PLAY-SAAS-CLOSE", "Run the closing motion",
         "1) Confirm intent and budget. 2) Send pricing and terms. 3) Agree a mutual close plan. "
         "4) Drive to signature on the planned date."),
    ]
    docs = []
    for kid, title, text in kb:
        docs.append({"id": kid, "source_type": "kb_article", "title": title, "text": text})
    for pid, title, text in plays:
        docs.append({"id": pid, "source_type": "playbook", "title": title, "text": text})
    return docs


# ===========================================================================
# Orchestration
# ===========================================================================
BUILDERS = {
    "customer_success": build_cs,
    "collections": build_collections,
    "saas_sales": build_saas_sales,
}


def generate(domains: Optional[List[str]] = None) -> Dict[str, Dict[str, int]]:
    targets = domains or list(BUILDERS)
    summary: Dict[str, Dict[str, int]] = {}
    for domain in targets:
        accounts, documents = BUILDERS[domain]()
        _write(domain, accounts, documents)
        summary[domain] = {"accounts": len(accounts), "documents": len(documents)}
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="app.seed_gen", description="Regenerate seed corpora.")
    parser.add_argument("--domain", action="append", dest="domains",
                        help="Limit to a domain (repeatable). Defaults to all.")
    args = parser.parse_args(argv)
    summary = generate(args.domains)
    for domain, counts in summary.items():
        print(f"{domain}: accounts={counts['accounts']} documents={counts['documents']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
