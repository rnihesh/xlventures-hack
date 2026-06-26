"""Backend test suite.

Every test in this package runs fully offline: no OPENAI_API_KEY, no
DATABASE_URL, and no network. The application and all of its slices are
designed to degrade to deterministic fallbacks, so the suite exercises the
real planner, policy engine, retriever, and API surface without external
services.
"""
