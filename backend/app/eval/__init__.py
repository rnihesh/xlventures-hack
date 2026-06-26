"""Evaluation harness for the Intelligent Next Best Action platform.

Three suites, all real and computable offline:

* ``component``  -> retrieval faithfulness + citation grounding checks.
* ``scenario``   -> runs the planner graph on golden cases, scores action
                    match and trajectory validity.
* ``outcome``    -> business outcomes (acceptance rate, simulated churn
                    reduction / NRR uplift, time to action) with a baseline
                    versus platform delta.

``runner.run_all`` aggregates every suite into the ``/eval`` response shape
and is callable from the CLI via ``python -m app.eval.runner``.
"""

from __future__ import annotations

__all__ = ["component", "scenario", "outcome", "runner"]
