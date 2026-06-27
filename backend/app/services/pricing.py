"""OpenAI token pricing, in USD per 1M tokens.

Used to turn recorded token counts into a dollar cost for the admin panel.
Prices are approximate list prices and easy to update in one place. Unknown
models fall back to a conservative default so cost is never silently zero.
"""

from __future__ import annotations

# (input_per_1m, output_per_1m) in USD. Embedding models price all tokens as
# "input" (output is 0).
_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o4-mini": (1.10, 4.40),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-ada-002": (0.10, 0.0),
}

_DEFAULT = (0.15, 0.60)  # gpt-4o-mini, a safe non-zero floor.


def _rate(model: str | None) -> tuple[float, float]:
    if not model:
        return _DEFAULT
    name = model.strip()
    if name in _PRICES:
        return _PRICES[name]
    # Match on a known prefix (handles dated suffixes like gpt-4o-mini-2024-..).
    for key, rate in _PRICES.items():
        if name.startswith(key):
            return rate
    return _DEFAULT


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Dollar cost for a single model call given its token counts."""
    in_rate, out_rate = _rate(model)
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
