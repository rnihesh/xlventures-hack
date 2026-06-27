"""Domain Pack loader.

``load_pack`` reads ``domain_packs/<domain>.yaml`` and validates it into a
:class:`~app.packs.schema.DomainPack`. ``list_packs`` scans the pack folder and
returns a compact summary for each pack (used by the /domains endpoint).

The pack directory is resolved robustly so the backend works whether it is run
from the repo root, from ``backend/``, or inside a container. An override is
available through the ``DOMAIN_PACKS_DIR`` environment variable.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.packs.schema import DomainPack

# ---------------------------------------------------------------------------
# Org-uploaded pack registry.
#
# Base packs ship as YAML on disk. An org can also upload a brand new domain at
# runtime (the "add a domain in 60 seconds" flow); those packs are not on disk,
# so the loader keeps an in-process registry keyed by ``(org_id, domain)``. The
# org_packs repository populates it on save and clears it on delete. A run sets
# the current org (via ``pack_org`` / ``set_pack_org``) so the synchronous graph,
# which calls ``load_pack(domain)`` with no org argument, still resolves the
# correct org's uploaded pack. The registry is consulted before disk, so an org
# pack can also shadow a base pack of the same key for that org only.
# ---------------------------------------------------------------------------

_ORG_PACKS: Dict[tuple[str, str], DomainPack] = {}

# Best-effort, domain-keyed fallback (last uploaded wins). The run path drives
# the graph through ``load_pack(domain)`` with no org bound; this lets a run on a
# just-added domain resolve its uploaded pack so the "run a decision now"
# shortcut works. It is consulted ONLY when no org is bound, so an org-scoped
# caller (the API, which binds the org) never crosses tenant boundaries.
_LAST_PACKS: Dict[str, DomainPack] = {}

# The org whose packs ``load_pack`` should prefer for the current task. Defaults
# to None (base packs only), which keeps every existing caller unchanged.
_current_pack_org: ContextVar[Optional[str]] = ContextVar("current_pack_org", default=None)


def set_pack_org(org_id: Optional[str]):
    """Bind the org whose uploaded packs ``load_pack`` should resolve.

    Returns the ContextVar token so the caller can ``reset`` it. Safe to call
    from async request handlers: the binding propagates into the graph nodes
    that run within the same task.
    """

    return _current_pack_org.set(org_id)


def reset_pack_org(token) -> None:
    """Undo a previous :func:`set_pack_org` using its token."""

    try:
        _current_pack_org.reset(token)
    except (ValueError, LookupError):  # pragma: no cover - defensive only
        pass


# Per-org decision-point roster overrides (Workflow Studio edits), bound for the
# duration of a run so the SYNCHRONOUS planner can honor them without a DB call.
# Shape: {decision_point_key: [capability, ...]}. The empty default leaves every
# existing run unchanged (the planner selects the roster as before).
_current_roster_overrides: ContextVar[Dict[str, List[str]]] = ContextVar(
    "current_roster_overrides", default={}
)


def set_roster_overrides(rosters: Optional[Dict[str, List[str]]]):
    """Bind the org's per-decision-point roster overrides for this run."""

    return _current_roster_overrides.set(dict(rosters or {}))


def reset_roster_overrides(token) -> None:
    """Undo a previous :func:`set_roster_overrides`."""

    try:
        _current_roster_overrides.reset(token)
    except (ValueError, LookupError):  # pragma: no cover - defensive only
        pass


def roster_override_for(decision_point: str) -> Optional[List[str]]:
    """Return the org's configured roster for a decision point, or None."""

    caps = (_current_roster_overrides.get() or {}).get(decision_point)
    return [str(c) for c in caps] if caps else None


def register_org_pack(org_id: str, domain: str, parsed: Dict[str, Any]) -> None:
    """Register a validated, org-uploaded pack so runs and lookups resolve it."""

    try:
        pack = DomainPack.model_validate(parsed)
    except Exception:  # noqa: BLE001 - never let a bad cached blob break loading.
        _ORG_PACKS.pop((org_id, domain), None)
        return
    _ORG_PACKS[(org_id, domain)] = pack
    _LAST_PACKS[domain] = pack


def unregister_org_pack(org_id: str, domain: str) -> None:
    """Drop an org-uploaded pack from the registry (on delete)."""

    _ORG_PACKS.pop((org_id, domain), None)
    # Clear the domain-only fallback only when no other org still has this pack.
    if not any(d == domain for (_o, d) in _ORG_PACKS):
        _LAST_PACKS.pop(domain, None)


def org_pack(org_id: Optional[str], domain: str) -> Optional[DomainPack]:
    """Return an org's uploaded pack for ``domain`` if registered, else None."""

    if not org_id:
        return None
    return _ORG_PACKS.get((org_id, domain))


def _candidate_dirs() -> List[Path]:
    """Ordered candidate locations for the ``domain_packs`` directory."""

    candidates: List[Path] = []

    env_dir = os.environ.get("DOMAIN_PACKS_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    # This file lives at <repo>/backend/app/packs/loader.py
    here = Path(__file__).resolve()
    # parents[3] -> <repo>/backend ; parents[4] -> <repo>
    backend_dir = here.parents[2]  # <repo>/backend/app -> .. -> backend
    repo_dir = here.parents[3]

    candidates.append(repo_dir / "domain_packs")
    candidates.append(backend_dir / "domain_packs")
    candidates.append(Path.cwd() / "domain_packs")
    candidates.append(Path.cwd().parent / "domain_packs")

    return candidates


def packs_dir() -> Path:
    """Return the first existing ``domain_packs`` directory.

    Falls back to the repo-root candidate (which may not exist yet) so callers
    get a deterministic path for error messages.
    """

    for candidate in _candidate_dirs():
        if candidate.is_dir():
            return candidate
    return _candidate_dirs()[-3]


def _disk_pack_exists(domain: str) -> bool:
    """True when a base pack YAML for ``domain`` ships on disk."""

    directory = packs_dir()
    return (directory / f"{domain}.yaml").is_file() or (
        directory / f"{domain}.yml"
    ).is_file()


def _minimal_pack(domain: str) -> DomainPack:
    """A safe, generic pack so the engine still runs if a YAML is missing."""

    return DomainPack(
        domain=domain,
        display_name=domain.replace("_", " ").title(),
        decision_points={
            "general_review": {
                "label": "General review",
                "description": "A generic decision point used when no pack is found.",
                "trigger_signals": [],
                "primary_kpi": "outcome_score",
                "default_persona": "operator",
            }
        },
        actions=[
            {
                "key": "monitor_no_action",
                "title": "Monitor and hold",
                "description": "Keep the entity on a watch list with re-evaluation thresholds.",
                "eligibility": "Use when signals are weak or contradicting.",
            }
        ],
        kpis=[
            {
                "key": "outcome_score",
                "label": "Outcome Score",
                "description": "Generic composite outcome metric.",
                "unit": "index_0_100",
                "target": ">= 70",
            }
        ],
        planner_prompt=(
            "You are a generic decision planner. Turn signals into a single, "
            "explainable next best action grounded in retrieved evidence."
        ),
    )


def load_pack(domain: str) -> DomainPack:
    """Resolve the effective domain pack for the current org, by key.

    Resolution order: an org-uploaded pack for the org bound via
    :func:`set_pack_org` (so a run on a freshly added domain uses it), then the
    base YAML on disk, then a minimal generic pack so the walking skeleton never
    crashes on a missing pack. The disk read is cached; the org registry lookup
    is not, so an org's edits take effect immediately.
    """

    org_id = _current_pack_org.get()
    uploaded = org_pack(org_id, domain)
    if uploaded is not None:
        return uploaded
    # No org bound (for example the run path that drives the graph org-blind):
    # fall back to the last uploaded pack for this domain so a just-added domain
    # is runnable. An org-bound caller never reaches here cross-tenant.
    if org_id is None:
        last = _LAST_PACKS.get(domain)
        if last is not None and not _disk_pack_exists(domain):
            return last
    return _load_pack_from_disk(domain)


@lru_cache(maxsize=32)
def _load_pack_from_disk(domain: str) -> DomainPack:
    """Load and validate a base domain pack from ``domain_packs/<domain>.yaml``."""

    path = packs_dir() / f"{domain}.yaml"
    if not path.is_file():
        # Try a .yml extension before giving up.
        alt = packs_dir() / f"{domain}.yml"
        path = alt if alt.is_file() else path

    if not path.is_file():
        return _minimal_pack(domain)

    with path.open("r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    raw.setdefault("domain", domain)
    return DomainPack.model_validate(raw)


# ---------------------------------------------------------------------------
# Org overrides: configurable rules and actions.
#
# An org tailors a domain pack without forking it. The base pack (loaded from
# YAML) stays intact; an org's edits are stored as a small JSONB override blob
# shaped like ``{"policies": [...], "actions": [...]}``. The helpers below merge
# that override onto the base pack so ``app.policy`` and the planner can read the
# *effective* pack for the current org. The merge is replace-by-id: when the
# override carries a ``policies`` (or ``actions``) list it defines the effective
# set, and each entry is backfilled from the matching base entry by id so a
# partial edit keeps the base fields it did not touch. Absent a list, the base
# is used unchanged. This supports adding, editing, and removing entries while
# never mutating the cached base pack.
# ---------------------------------------------------------------------------


def _merge_entries(
    base: List[Dict[str, Any]],
    override: Any,
    id_key: str,
) -> List[Dict[str, Any]]:
    """Merge an override list onto a base list, keyed by ``id_key``.

    Returns the base list unchanged when ``override`` is not a list (no edit).
    Otherwise the override list defines membership and ordering, with each entry
    shallow-merged over the matching base entry so partial edits inherit the
    base fields they omit.
    """

    if not isinstance(override, list):
        return [dict(item) for item in base]

    base_by_id: Dict[str, Dict[str, Any]] = {
        str(item.get(id_key, "")): item for item in base if isinstance(item, dict)
    }
    merged: List[Dict[str, Any]] = []
    for entry in override:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get(id_key, ""))
        if not entry_id:
            continue
        base_entry = base_by_id.get(entry_id, {})
        merged.append({**base_entry, **entry})
    return merged


def _base_policy_dicts(domain: str) -> List[Dict[str, Any]]:
    """The base policy rules for a domain as plain dicts (pack or built-ins)."""

    # Lazy import keeps the packs layer free of a hard dependency on the policy
    # layer (which imports the loader), avoiding an import cycle at module load.
    from app.policy.rules import load_policies

    return [rule.model_dump() for rule in load_policies(domain)]


def _base_action_dicts(domain: str) -> List[Dict[str, Any]]:
    """The base action catalog for a domain as plain dicts."""

    return [action.model_dump() for action in load_pack(domain).actions]


def effective_rules(domain: str, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the effective policies and actions for an org as plain dicts.

    Merges ``overrides`` (``{"policies"?: [...], "actions"?: [...]}``) onto the
    base pack and returns ``{"policies": [...], "actions": [...]}``. Never raises
    and never mutates the cached base pack, so it is safe for the API, the policy
    engine, and the planner to call on every request.
    """

    overrides = overrides or {}
    policies = _merge_entries(
        _base_policy_dicts(domain), overrides.get("policies"), "id"
    )
    actions = _merge_entries(
        _base_action_dicts(domain), overrides.get("actions"), "key"
    )
    return {"policies": policies, "actions": actions}


def merged_pack(domain: str, overrides: Optional[Dict[str, Any]]) -> DomainPack:
    """Return a DomainPack with the org's overrides merged onto the base pack.

    The base pack is copied (never mutated), then its ``actions`` and the extra
    ``policies`` section are replaced with the effective, merged values. The
    planner and policy layer can treat the result exactly like a normally loaded
    pack while seeing the current org's configured rules and actions.
    """

    base = load_pack(domain)
    data: Dict[str, Any] = base.model_dump()
    effective = effective_rules(domain, overrides)
    data["actions"] = effective["actions"]
    data["policies"] = effective["policies"]
    return DomainPack.model_validate(data)


def list_packs() -> List[Dict[str, Any]]:
    """Scan the pack folder and return a compact summary per pack."""

    directory = packs_dir()
    summaries: List[Dict[str, Any]] = []
    if not directory.is_dir():
        return summaries

    seen: set[str] = set()
    for path in sorted(directory.glob("*.y*ml")):
        domain = path.stem
        if domain in seen:
            continue
        seen.add(domain)
        try:
            pack = load_pack(domain)
            summaries.append(pack.summary())
        except Exception:  # noqa: BLE001 - never let one bad pack break the list
            summaries.append(
                {
                    "key": domain,
                    "display_name": domain.replace("_", " ").title(),
                    "actions_count": 0,
                    "decision_points_count": 0,
                }
            )
    return summaries
