"""Ingest-specific helpers: deterministic signal extraction and a recent-feed.

These are owned by the ingest slice (not the shared retrieval / embeddings core).
Everything here is fully offline: no LLM and no database are required.

* :func:`extract_signals` runs a light, deterministic pass over a pasted
  interaction and surfaces a short title plus a few candidate signal phrases
  (sentences that mention churn, renewal, usage, sentiment, and friends). It
  gives the engine structured hints the moment a human pastes raw text.
* :class:`RecentIngestStore` keeps an org-scoped, in-memory feed of what was
  ingested this process, most recent first, so the UI can show a live list and
  so repeat pastes are idempotent (same content returns the same record).

The store mirrors the offline pattern used elsewhere in the API layer (an
in-process dict keyed by ``org_id``); a database is never required for the
ingest experience to work.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------
# Ordered category buckets. The first bucket whose keywords match a sentence
# wins, so higher-priority risks (churn, renewal) label a sentence ahead of
# softer ones (sentiment). Keywords are matched on word boundaries, lowercased.
_SIGNAL_BUCKETS: List[Dict[str, Any]] = [
    {
        "category": "churn_risk",
        "label": "Churn risk",
        "keywords": [
            "churn", "cancel", "cancelled", "canceling", "terminate", "termination",
            "leaving", "leave", "walk away", "at risk", "not renew", "non-renewal",
            "downgrade", "downgrading", "dissatisfied", "unhappy", "escalation",
            "escalate", "frustrated", "frustration", "blocker", "deal breaker",
        ],
    },
    {
        "category": "renewal",
        "label": "Renewal",
        "keywords": [
            "renewal", "renew", "renewing", "contract", "term", "expires",
            "expiration", "up for renewal", "auto-renew", "commitment",
        ],
    },
    {
        "category": "competitor",
        "label": "Competitor",
        "keywords": [
            "competitor", "competing", "evaluating", "alternative", "switching",
            "switch to", "rfp", "bake-off", "vendor", "rip and replace",
        ],
    },
    {
        "category": "expansion",
        "label": "Expansion",
        "keywords": [
            "expand", "expansion", "upsell", "upgrade", "add seats", "more seats",
            "additional licenses", "grow", "new use case", "roll out", "rollout",
        ],
    },
    {
        "category": "usage",
        "label": "Usage / adoption",
        "keywords": [
            "usage", "adoption", "adopt", "active users", "logins", "log in",
            "engagement", "stalled", "stall", "declin", "drop in", "inactive",
            "onboarding", "ramp", "power user", "seats", "feature request",
        ],
    },
    {
        "category": "pricing",
        "label": "Pricing / budget",
        "keywords": [
            "price", "pricing", "budget", "cost", "discount", "spend",
            "too expensive", "roi", "value for money",
        ],
    },
    {
        "category": "support",
        "label": "Support / reliability",
        "keywords": [
            "ticket", "bug", "outage", "incident", "downtime", "support",
            "issue", "broken", "slow", "performance", "sev1", "sev2",
        ],
    },
    {
        "category": "sentiment",
        "label": "Sentiment",
        "keywords": [
            "happy", "delighted", "love", "great", "excited", "satisfied",
            "concern", "concerned", "worried", "complaint", "disappointed",
            "champion", "advocate", "detractor", "sentiment",
        ],
    },
]

# Split on sentence terminators and hard newlines while keeping it cheap.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WHITESPACE = re.compile(r"\s+")
_MAX_SIGNALS = 6
_MAX_SIGNAL_CHARS = 220
_MAX_TITLE_CHARS = 80


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace into single spaces and trim."""
    return _WHITESPACE.sub(" ", text or "").strip()


def _sentences(text: str) -> List[str]:
    """Split text into trimmed, non-trivial sentence-ish fragments."""
    out: List[str] = []
    for raw in _SENTENCE_SPLIT.split(text or ""):
        frag = _normalize_ws(raw)
        if len(frag) >= 12:  # skip stray fragments, headers, bullet dashes
            out.append(frag)
    return out


def _classify(sentence: str) -> Optional[Dict[str, str]]:
    """Return the best-matching category for a sentence, or None.

    The first bucket (in priority order) with a keyword hit wins. The matched
    keyword is returned so the UI can show what tripped the signal.
    """
    low = sentence.lower()
    for bucket in _SIGNAL_BUCKETS:
        for kw in bucket["keywords"]:
            # Word-ish boundary match so "renew" does not fire inside "renewable".
            if re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", low):
                return {
                    "category": bucket["category"],
                    "label": bucket["label"],
                    "keyword": kw,
                }
    return None


def derive_title(text: str, source_type: str, given: Optional[str] = None) -> str:
    """Pick a short, human title for an interaction.

    Prefers a caller-supplied title, then the first meaningful line / sentence,
    and finally a generic ``"<Source type> import"`` label. Always trimmed to a
    compact length so it reads well as a list row.
    """
    if (given or "").strip():
        return _normalize_ws(given)[:_MAX_TITLE_CHARS]

    for line in (text or "").splitlines():
        candidate = _normalize_ws(line)
        if len(candidate) >= 8:
            # If the first line is itself a long paragraph, clip to its first
            # sentence so the title stays tight.
            first = _sentences(candidate)
            candidate = first[0] if first else candidate
            if len(candidate) > _MAX_TITLE_CHARS:
                candidate = candidate[: _MAX_TITLE_CHARS - 1].rstrip() + "…"
            return candidate

    return f"{source_type.replace('_', ' ').title()} import"


def extract_signals(text: str) -> List[Dict[str, str]]:
    """Deterministically surface candidate signal phrases from raw text.

    Returns up to a handful of ``{category, label, keyword, text}`` hints, one
    per distinct sentence, ordered by how many signal keywords each sentence
    carries (strongest first) and then by where it appears. Pure function: no
    network, no LLM, stable for the same input.
    """
    signals: List[Dict[str, Any]] = []
    seen_text: set[str] = set()

    for index, sentence in enumerate(_sentences(text)):
        match = _classify(sentence)
        if match is None:
            continue
        key = sentence.lower()
        if key in seen_text:
            continue
        seen_text.add(key)
        phrase = sentence
        if len(phrase) > _MAX_SIGNAL_CHARS:
            phrase = phrase[: _MAX_SIGNAL_CHARS - 1].rstrip() + "…"
        # Strength: count distinct buckets that fire on this sentence.
        low = sentence.lower()
        strength = sum(
            1
            for bucket in _SIGNAL_BUCKETS
            if any(
                re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", low)
                for kw in bucket["keywords"]
            )
        )
        signals.append(
            {
                "category": match["category"],
                "label": match["label"],
                "keyword": match["keyword"],
                "text": phrase,
                "_strength": strength,
                "_order": index,
            }
        )

    signals.sort(key=lambda s: (-s["_strength"], s["_order"]))
    trimmed = signals[:_MAX_SIGNALS]
    return [
        {"category": s["category"], "label": s["label"], "keyword": s["keyword"], "text": s["text"]}
        for s in trimmed
    ]


# ---------------------------------------------------------------------------
# Recent-ingest feed (org-scoped, in-memory, idempotent)
# ---------------------------------------------------------------------------
def content_fingerprint(
    org_id: str, account_id: Optional[str], source_type: str, text: str
) -> str:
    """Stable hash of an ingest payload, used to dedupe repeat pastes per org."""
    normalized = _normalize_ws(text).lower()
    raw = "".join([org_id, account_id or "", source_type, normalized])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RecentIngestStore:
    """Per-org, most-recent-first feed of ingested interactions (in-memory).

    Offline-safe and process-local: it backs the ingest page's "recently
    ingested" list and makes repeat pastes idempotent. Each org keeps at most
    :attr:`cap` records, evicting the oldest beyond that.
    """

    def __init__(self, cap: int = 50) -> None:
        self.cap = cap
        # org_id -> OrderedDict[fingerprint -> record]. Insertion order is most
        # recent last; readers reverse it for newest-first.
        self._by_org: Dict[str, "OrderedDict[str, Dict[str, Any]]"] = {}

    def get(self, org_id: str, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Return a previously ingested record for this org, if any."""
        return self._by_org.get(org_id, {}).get(fingerprint)

    def add(self, org_id: str, fingerprint: str, record: Dict[str, Any]) -> None:
        """Record an ingested interaction for the org (newest wins, capped)."""
        bucket = self._by_org.setdefault(org_id, OrderedDict())
        # Re-insert to move an existing fingerprint to the most-recent position.
        if fingerprint in bucket:
            del bucket[fingerprint]
        bucket[fingerprint] = record
        while len(bucket) > self.cap:
            bucket.popitem(last=False)

    def list(
        self, org_id: str, account_id: Optional[str] = None, limit: int = 25
    ) -> List[Dict[str, Any]]:
        """Newest-first records for the org, optionally filtered by account."""
        bucket = self._by_org.get(org_id, {})
        records = list(bucket.values())[::-1]
        if account_id:
            records = [r for r in records if r.get("account_id") == account_id]
        return records[: max(0, limit)]

    def clear(self, org_id: Optional[str] = None) -> None:
        """Clear one org's feed, or all of them (used by tests)."""
        if org_id is None:
            self._by_org.clear()
        else:
            self._by_org.pop(org_id, None)


# Process-wide singleton shared by the ingest endpoints.
recent_store = RecentIngestStore()
