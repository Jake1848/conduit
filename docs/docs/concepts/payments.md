# Payments

Conduit supports the three Lightning payment shapes you'll actually use.

## Lightning address (`name@host`)

The friendly form. Conduit resolves `name@host` via
[LNURL-pay](https://github.com/lnurl/luds/blob/luds/06.md), fetches an
invoice for the requested amount, and pays it.

```python
agent.pay(to="alice@strike.me", sats=500, memo="lunch")
```

## BOLT11 invoice

When the receiver gives you a BOLT11 string (`lnbc…`), pay it directly.

```python
agent.send_invoice("lnbc500u1p3...", memo="…optional")
```

The `sats` argument is optional unless the invoice is zero-amount.

## Keysend

Push payment to a node by pubkey, no invoice needed. Useful for
machine-to-machine flows where neither side wants to negotiate an invoice
first.

```python
agent.keysend(dest_pubkey="03abcdef...", sats=120, memo="vector embedding")
```

## Receipt

Every successful payment returns a `Receipt`:

```python
receipt.id              # tx_…
receipt.status          # 'settled' | 'failed' | 'pending'
receipt.hash            # payment hash (hex)
receipt.amount_sats     # exact amount paid
receipt.fee_sats        # routing fee paid
receipt.settled_in_ms   # end-to-end Lightning latency
receipt.destination     # whatever you passed in
```

## Receiving

```python
invoice = agent.receive(amount=5_000, memo="data feed")
print(invoice.payment_request)
# lnbc50u1p3...
```

Hand `payment_request` to the payer. When it settles, Conduit fires a
`payment.settled` webhook (if you have one configured).
