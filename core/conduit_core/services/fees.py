"""Platform fee — the Conduit operator's per-payment revenue.

Self-hosted model: the operator runs Conduit against their OWN LND node. On every
successful outbound payment, Conduit debits the agent a small platform fee ON TOP
of the payment amount and the LND routing-fee budget. The payment amount + actual
routing fee leave the operator's node over Lightning; the platform fee never leaves
— it is simply retained in the operator's node as revenue. So "fees collected" is an
accounting view over settled transactions (sum of platform_fee_sats), not a separate
transfer.

This fee is DISTINCT from `fee_sats` (the LND routing-fee budget, which pays Lightning
routing nodes and whose unused remainder is refunded to the agent). Never conflate them.
"""

from __future__ import annotations


def compute_platform_fee(
    amount_sats: int, percent: float, min_sats: int, max_sats: int
) -> int:
    """Platform fee for a payment of `amount_sats`.

    `percent` is a percentage (0.5 == 0.5%). The raw fee is clamped to
    [min_sats, max_sats] so tiny payments still pay the floor and large payments
    aren't punished beyond the cap. `percent <= 0` disables the fee entirely
    (returns 0) — a self-hosting operator may choose to charge nothing.
    """
    if percent <= 0 or amount_sats <= 0:
        return 0
    raw = round(amount_sats * percent / 100.0)
    # Guard against a misconfigured min > max: the cap always wins.
    floor = max(0, min(min_sats, max_sats))
    return max(floor, min(max_sats, raw))
