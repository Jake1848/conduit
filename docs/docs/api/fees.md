# Platform fees API

Conduit's built-in monetization is a per-transaction **platform fee in
satoshis**. It is **your** revenue as the operator running Conduit — not a
Conduit cut, and never custody of your funds. You configure it; Conduit adds it
on top of each payment, keeps it when the payment settles, and refunds it in
full if the payment fails.

## How the fee is computed

The fee is configured entirely by you, the operator, via three env vars:

| var | default | meaning |
| --- | ------- | ------- |
| `PLATFORM_FEE_PERCENT`  | `0.5`  | fee as a percent of the payment amount (0.5 = 0.5%); set `0` to disable |
| `PLATFORM_FEE_MIN_SATS` | `1`    | floor for the per-transaction fee |
| `PLATFORM_FEE_MAX_SATS` | `1000` | ceiling for the per-transaction fee |

For each payment the fee is `clamp(amount × PERCENT%, MIN, MAX)` and is charged
**on top of** the amount being sent. It is debited from the agent's balance when
the payment is sent, **kept** when the payment settles (it stays in your own LND
node's liquidity), and **refunded in full** to the agent if the payment fails.

The fee shows up on every payment receipt as `platform_fee_sats`, separate from
`fee_sats` (the LND routing fee). See the [Payments API](payments.md).

## Get collected fees

`GET /v1/fees` — requires `admin`

Returns the operator's accumulated platform-fee revenue. Only **settled**
payments are counted (failed payments are refunded), so this is an accounting
view over your settled transactions.

```json
{
  "total_collected_sats": 1284417,
  "total_collected_btc": 0.01284417,
  "today_sats": 9032,
  "fees_by_day": [
    { "date": "2026-06-06", "sats": 9032, "tx_count": 41 },
    { "date": "2026-06-05", "sats": 21785, "tx_count": 96 }
    // … up to 30 days, most recent first
  ]
}
```

| field | meaning |
| ----- | ------- |
| `total_collected_sats` | Σ platform fees on settled payments, all time |
| `total_collected_btc`  | the same total expressed in BTC (8 dp) |
| `today_sats`           | platform fees collected since 00:00 UTC today |
| `fees_by_day[]`        | up to **30** daily buckets (UTC), **most-recent-first**, each with `date` (`YYYY-MM-DD`), `sats`, and `tx_count` |

## See also

- The fleet [Metrics API](metrics.md) also surfaces `fee_revenue_total_sats` and
  `fee_revenue_today_sats` for at-a-glance dashboards.
- [Production deployment → Platform fee](../production.md#platform-fee-your-revenue)
  for setting the env vars on your own deployment.
