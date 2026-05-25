# Policies

A **policy** is a set of spending rules attached to an agent. The Conduit
policy engine evaluates every outbound payment **before** it reaches the
Lightning Network, and rejects it with a stable error code if any rule
fails.

The engine **fails closed**: if it cannot evaluate a rule (DB outage, bug,
malformed input), the payment is denied — never allowed.

## Rules

| field                    | meaning |
| ------------------------ | ------- |
| `max_per_transaction`    | hard cap on the size of any single payment, in sats |
| `max_per_hour`           | rolling 60-minute spend cap, in sats |
| `max_per_day`            | rolling 24-hour spend cap, in sats |
| `max_per_minute_count`   | rate limit on the **number** of payments per 60s (default 60) |
| `allowlist`              | if non-empty, payments may only go to these destinations |
| `blocklist`              | payments to these destinations are always denied |
| `require_memo`           | denies payments without a non-empty memo |
| `enabled`                | master kill switch — `false` blocks all outbound payments |

## How limits compose

A payment is allowed only if it satisfies **every** rule that's set. A
field left as `null` is treated as "no limit". For instance:

```python
agent.policy.attach(max_per_day=50_000)  # only the daily cap is enforced
```

means each individual payment can be any size, but the rolling 24h total
across **settled and pending** payments must stay ≤ 50,000 sats.

## In-flight accounting

Pending payments count against your windows immediately, so a fast loop
trying to race past the limit cannot — every concurrent decision sees
the same pending row.

If the Lightning Network later reports the payment as failed, the engine
moves it to `failed` and stops counting it. There is no race that lets
the agent retroactively go over.

## Error codes

| code | meaning |
| ---- | ------- |
| `POLICY_DISABLED`            | the agent's policy has `enabled=false` |
| `AGENT_INACTIVE`             | the agent itself has been deactivated |
| `PER_TRANSACTION_LIMIT_EXCEEDED` | this payment is larger than `max_per_transaction` |
| `HOURLY_LIMIT_EXCEEDED`      | rolling hour would exceed `max_per_hour` |
| `DAILY_LIMIT_EXCEEDED`       | rolling day would exceed `max_per_day` |
| `RATE_LIMIT_EXCEEDED`        | more than `max_per_minute_count` payments in 60s |
| `DESTINATION_BLOCKLISTED`    | destination matches `blocklist` |
| `DESTINATION_NOT_ALLOWLISTED`| `allowlist` is set and destination is not in it |
| `MEMO_REQUIRED`              | `require_memo=true` and no memo was provided |
| `POLICY_EVALUATION_ERROR`    | engine could not evaluate; **fail-closed** denial |
