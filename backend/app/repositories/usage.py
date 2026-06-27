"""Persistence and aggregation for ``usage_events`` (OpenAI cost accounting).

All functions degrade to a no-op / empty result when no database pool is
configured, so the app and its tests run without Postgres.
"""

from __future__ import annotations

import logging
from typing import Any

from app.deps import get_pool

logger = logging.getLogger("app.repositories.usage")


async def insert_events(rows: list[dict[str, Any]]) -> None:
    """Bulk-insert usage rows. Best effort: never raises into the request."""
    if not rows:
        return
    pool = await get_pool()
    if pool is None:
        return
    try:
        await pool.executemany(
            """
            INSERT INTO usage_events
              (org_id, kind, model, input_tokens, output_tokens, total_tokens, cost_usd)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [
                (
                    r["org_id"],
                    r["kind"],
                    r.get("model", ""),
                    r.get("input_tokens", 0),
                    r.get("output_tokens", 0),
                    r.get("total_tokens", 0),
                    r.get("cost_usd", 0.0),
                )
                for r in rows
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("usage insert failed: %s", exc)


async def totals(days: int = 30) -> dict[str, Any]:
    """Grand totals over the window: events, tokens, cost."""
    pool = await get_pool()
    if pool is None:
        return {"events": 0, "total_tokens": 0, "cost_usd": 0.0}
    row = await pool.fetchrow(
        """
        SELECT count(*) AS events,
               COALESCE(sum(total_tokens), 0) AS total_tokens,
               COALESCE(sum(cost_usd), 0) AS cost_usd
        FROM usage_events
        WHERE created_at >= now() - ($1 || ' days')::interval
        """,
        str(days),
    )
    return dict(row) if row else {"events": 0, "total_tokens": 0, "cost_usd": 0.0}


async def by_org(days: int = 30) -> list[dict[str, Any]]:
    """Per-org token + cost totals over the window."""
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        """
        SELECT org_id,
               COALESCE(sum(input_tokens), 0) AS input_tokens,
               COALESCE(sum(output_tokens), 0) AS output_tokens,
               COALESCE(sum(total_tokens), 0) AS total_tokens,
               COALESCE(sum(cost_usd), 0) AS cost_usd,
               count(*) AS events,
               max(created_at) AS last_used
        FROM usage_events
        WHERE created_at >= now() - ($1 || ' days')::interval
        GROUP BY org_id
        ORDER BY cost_usd DESC
        """,
        str(days),
    )
    return [dict(r) for r in rows]


async def by_model(days: int = 30) -> list[dict[str, Any]]:
    """Per-model token + cost totals over the window."""
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        """
        SELECT model, kind,
               COALESCE(sum(total_tokens), 0) AS total_tokens,
               COALESCE(sum(cost_usd), 0) AS cost_usd,
               count(*) AS events
        FROM usage_events
        WHERE created_at >= now() - ($1 || ' days')::interval
        GROUP BY model, kind
        ORDER BY cost_usd DESC
        """,
        str(days),
    )
    return [dict(r) for r in rows]


async def daily(days: int = 30) -> list[dict[str, Any]]:
    """Per-day token + cost series over the window (zero-filled)."""
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        """
        SELECT to_char(d.day, 'YYYY-MM-DD') AS day,
               COALESCE(sum(u.total_tokens), 0) AS total_tokens,
               COALESCE(sum(u.cost_usd), 0) AS cost_usd
        FROM generate_series(
               (now() - ($1 || ' days')::interval)::date, now()::date, '1 day'
             ) AS d(day)
        LEFT JOIN usage_events u ON u.created_at::date = d.day
        GROUP BY d.day
        ORDER BY d.day
        """,
        str(days),
    )
    return [dict(r) for r in rows]


async def cost_by_org_map(days: int | None = None) -> dict[str, dict[str, Any]]:
    """Org -> {total_tokens, cost_usd} over an optional window (all time if None)."""
    pool = await get_pool()
    if pool is None:
        return {}
    if days is None:
        rows = await pool.fetch(
            """
            SELECT org_id,
                   COALESCE(sum(total_tokens), 0) AS total_tokens,
                   COALESCE(sum(cost_usd), 0) AS cost_usd
            FROM usage_events GROUP BY org_id
            """
        )
    else:
        rows = await pool.fetch(
            """
            SELECT org_id,
                   COALESCE(sum(total_tokens), 0) AS total_tokens,
                   COALESCE(sum(cost_usd), 0) AS cost_usd
            FROM usage_events
            WHERE created_at >= now() - ($1 || ' days')::interval
            GROUP BY org_id
            """,
            str(days),
        )
    return {r["org_id"]: {"total_tokens": r["total_tokens"], "cost_usd": r["cost_usd"]} for r in rows}
