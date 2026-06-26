"""Current-org dependency resolution for the data-scoping layer.

User endpoints scope every read and write to the caller's org. The org is
resolved from the authenticated session by ``app.auth.deps.get_current_org``
(the auth slice). This module binds to that dependency when it is importable and
otherwise falls back to the demo org, which keeps the offline / single-tenant
path (tests, no auth configured) working against the seeded demo data exactly as
before.

Import the dependency from here so every scoped endpoint shares one resolution
strategy:

    from app.api._org import current_org
    ...
    async def handler(org_id: str = Depends(current_org)): ...
"""

from __future__ import annotations

DEMO_ORG = "org_demo"

try:  # Prefer the real auth-backed dependency when the auth slice is present.
    from app.auth.deps import get_current_org as current_org  # type: ignore
except Exception:  # noqa: BLE001 - auth slice absent (offline / tests): use demo org.

    def current_org() -> str:
        """Fallback org resolver: the demo org owns all seed data."""

        return DEMO_ORG


__all__ = ["current_org", "DEMO_ORG"]
