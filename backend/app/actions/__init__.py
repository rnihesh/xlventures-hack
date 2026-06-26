"""Action execution slice.

Turns a recommendation (the explainable next best action) into a concrete,
ready-to-use artifact: a drafted email, a CRM task, or a Slack handoff message.

The generators degrade gracefully. When ``OPENAI_API_KEY`` is configured the
LLM writes the artifact; otherwise deterministic templates derived from the
recommendation fields are used so the feature works fully offline with no
network access.
"""

from __future__ import annotations

from app.actions.generators import (
    ARTIFACT_TYPES,
    create_crm_task,
    draft_email,
    generate_artifact,
    slack_handoff,
)

__all__ = [
    "ARTIFACT_TYPES",
    "create_crm_task",
    "draft_email",
    "generate_artifact",
    "slack_handoff",
]
