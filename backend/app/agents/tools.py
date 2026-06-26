"""Shared tools for the specialist agents.

Small, dependency-light helpers that several specialists reuse so the agents can
be more sophisticated without duplicating logic. Everything here is
deterministic and offline-safe: any LLM-backed helper short-circuits to ``None``
in DEMO mode (or on any failure) so callers fall back to deterministic behavior
and self-tests never spend OpenAI tokens.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Words that carry no retrieval signal. Kept compact on purpose: this is a demo
# heuristic, not a linguistics engine.
_STOPWORDS = {
    "a", "an", "and", "the", "of", "to", "in", "on", "for", "with", "at", "by",
    "is", "are", "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "it", "its", "as", "from", "into", "over", "under", "out", "up",
    "down", "has", "have", "had", "not", "no", "but", "or", "if", "then", "so",
    "than", "ahead", "during", "after", "before", "detected", "account",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]+")


def humanize(key: str) -> str:
    """Turn a snake_case key into a readable phrase."""

    return key.replace("_", " ").strip()


def keyword_tokens(text: str, limit: int = 8) -> List[str]:
    """Extract the salient keywords from free text, in first-seen order.

    Lowercased, stop-worded, de-duplicated, and length-filtered so the result is
    a stable seed for query expansion across identical inputs.
    """

    if not text:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for raw in _TOKEN_RE.findall(str(text).lower()):
        token = raw.strip("-_")
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def decision_point_synonyms(pack: Any, decision_point: str) -> List[str]:
    """Derive synonym terms for a decision point from the domain pack.

    Pulls the decision point label, its primary KPI label, and the human labels
    of its trigger signals, so an offline query expansion can broaden recall
    without any LLM. Returns lowercase, de-duplicated terms in a stable order.
    """

    terms: List[str] = []
    try:
        dp = pack.decision_points.get(decision_point) if pack else None
    except Exception:  # noqa: BLE001 - pack shape is best-effort
        dp = None
    if dp is None:
        terms.extend(keyword_tokens(humanize(decision_point), 4))
        return _dedupe_lower(terms)

    terms.extend(keyword_tokens(dp.label, 4))

    # Primary KPI label (e.g. "Gross Revenue Retention") broadens the topic.
    try:
        kpi = pack.kpi_by_key(dp.primary_kpi) if dp.primary_kpi else None
        if kpi is not None:
            terms.extend(keyword_tokens(kpi.label or kpi.key, 4))
        elif dp.primary_kpi:
            terms.extend(keyword_tokens(humanize(dp.primary_kpi), 3))
    except Exception:  # noqa: BLE001
        pass

    # Trigger-signal labels are the strongest synonyms for what to retrieve.
    signal_labels = {}
    try:
        signal_labels = {s.key: s.label for s in pack.signals}
    except Exception:  # noqa: BLE001
        signal_labels = {}
    for sig_key in getattr(dp, "trigger_signals", []) or []:
        label = signal_labels.get(sig_key) or humanize(sig_key)
        terms.extend(keyword_tokens(label, 3))

    return _dedupe_lower(terms)


def _dedupe_lower(terms: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for term in terms:
        low = term.lower().strip()
        if low and low not in seen:
            seen.add(low)
            out.append(low)
    return out


def account_context(account_id: str, domain: str = "customer_success") -> Dict[str, Any]:
    """Best-effort account profile for scoring and policy.

    Prefers the seeded accounts slice (so account-scoped factors have data) and
    always falls back to a minimal identity, so it works offline and never
    raises. Read-only: this never mutates the accounts store.
    """

    base: Dict[str, Any] = {"account_id": account_id, "domain": domain}
    if not account_id:
        return base

    # Preferred: the seed slice, which works fully offline (no app startup).
    try:
        from app import seed_data

        account = seed_data.get_account(account_id, domain)
        if account:
            return {**account, "domain": account.get("domain", domain)}
        # The account may live under a different domain pack; scan known seeds.
        for other in ("customer_success", "saas_sales", "collections"):
            if other == domain:
                continue
            account = seed_data.get_account(account_id, other)
            if account:
                return {**account, "domain": account.get("domain", other)}
    except Exception:  # noqa: BLE001 - seed slice is optional
        pass

    # Fallback: an in-memory accounts map if one is ever exposed by the API.
    try:
        from app.api.accounts import _BY_ID  # type: ignore

        account = _BY_ID.get(account_id)
        if account:
            return {**account, "domain": account.get("domain", domain)}
    except Exception:  # noqa: BLE001 - accounts slice is optional
        pass
    return base


def llm_available() -> bool:
    """True only when a real (non-demo) chat model is configured.

    In DEMO mode (no key, or DEMO_MODE set) this is False so specialists take
    their deterministic path and self-tests never call the network.
    """

    try:
        from app.demo import demo_mode_enabled

        if demo_mode_enabled():
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        from app.deps import get_llm

        return get_llm() is not None
    except Exception:  # noqa: BLE001
        return False


def llm_lines(prompt: str, max_lines: int = 3) -> Optional[List[str]]:
    """Ask the live LLM for a short newline-separated list.

    Returns the parsed, cleaned lines, or ``None`` when no real model is
    available (DEMO mode) or on any failure, so the caller falls back to a
    deterministic derivation. Never raises.
    """

    if not llm_available():
        return None
    try:
        from app.deps import get_llm

        llm = get_llm()
        if llm is None:
            return None
        result = llm.invoke(prompt)
        text = getattr(result, "content", result)
        if not isinstance(text, str) or not text.strip():
            return None
        lines = [
            ln.strip(" -*0123456789.\t").strip()
            for ln in text.splitlines()
            if ln.strip()
        ]
        lines = [ln for ln in lines if ln]
        return lines[:max_lines] or None
    except Exception:  # noqa: BLE001 - the LLM is always optional
        return None
