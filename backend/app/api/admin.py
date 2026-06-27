"""Admin panel API (allowlisted operators only).

Surfaces who signed up, how active each org is, and how much each org is
spending on OpenAI. Every route requires the caller's email to be in
``settings.admin_emails``; non-admins get 403. All queries degrade to empty
results when no database pool is configured.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import get_current_user
from app.config import settings
from app.deps import get_pool
from app.repositories import usage as usage_repo

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Allow only allowlisted admin emails; 403 otherwise."""
    if not settings.is_admin(user.get("email")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user


@router.get("/overview")
async def overview(
    days: int = Query(30, ge=1, le=365),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    pool = await get_pool()
    base = {"orgs": 0, "users": 0, "accounts": 0, "runs": 0}
    if pool is None:
        return {**base, "usage": await usage_repo.totals(days),
                "usage_all_time": await usage_repo.totals(36500), "days": days}
    base["orgs"] = await pool.fetchval("SELECT count(*) FROM orgs") or 0
    base["users"] = await pool.fetchval("SELECT count(*) FROM users") or 0
    base["accounts"] = await pool.fetchval("SELECT count(*) FROM accounts") or 0
    base["runs"] = await pool.fetchval("SELECT count(*) FROM episodes") or 0
    return {
        **base,
        "usage": await usage_repo.totals(days),
        "usage_all_time": await usage_repo.totals(36500),
        "days": days,
    }


@router.get("/orgs")
async def orgs(
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        """
        SELECT o.id, o.name, o.created_at,
               (SELECT count(*) FROM users u WHERE u.org_id = o.id) AS users,
               (SELECT count(*) FROM accounts a WHERE a.org_id = o.id) AS accounts,
               (SELECT count(*) FROM episodes e WHERE e.org_id = o.id) AS runs,
               (SELECT max(e.created_at) FROM episodes e WHERE e.org_id = o.id) AS last_run
        FROM orgs o
        ORDER BY o.created_at DESC
        """
    )
    cost = await usage_repo.cost_by_org_map(None)
    out = []
    for r in rows:
        d = dict(r)
        c = cost.get(d["id"], {})
        d["total_tokens"] = c.get("total_tokens", 0)
        d["cost_usd"] = round(c.get("cost_usd", 0.0), 4)
        out.append(d)
    return out


@router.get("/users")
async def users(
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        """
        SELECT u.id, u.email, u.name, u.org_id, o.name AS org_name,
               u.role, u.email_verified, u.created_at, u.last_login_at
        FROM users u
        LEFT JOIN orgs o ON o.id = u.org_id
        ORDER BY u.created_at DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/usage")
async def usage(
    days: int = Query(30, ge=1, le=365),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    by_org = await usage_repo.by_org(days)
    # Attach org display names.
    pool = await get_pool()
    if pool is not None and by_org:
        names = {
            r["id"]: r["name"]
            for r in await pool.fetch("SELECT id, name FROM orgs")
        }
        for row in by_org:
            row["org_name"] = names.get(row["org_id"], row["org_id"])
    return {
        "days": days,
        "totals": await usage_repo.totals(days),
        "by_org": by_org,
        "by_model": await usage_repo.by_model(days),
        "daily": await usage_repo.daily(days),
    }
