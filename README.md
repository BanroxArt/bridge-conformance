# bridge-conformance

A fault-injection harness for the part of a payments or stablecoin service that receives status callbacks (accepted, settled, returned, confirmed, dropped) and turns them into ledger entries. It replays a known history of payments into your receiver through a hostile network: duplicate deliveries, events that arrive out of order, responses that never reach the sender so it retries hours later, crashes between two writes, stale captured deliveries resent by an attacker, and tampered or forged copies. Then it checks what your receiver ended up believing against what really happened, and cuts any failure down to the smallest case that still fails.

Built and maintained by Art Akopian, CEO of [Banrox](https://banrox.com).

> **Engineering checklist, not legal advice.** Passing these checks says your receiver survived these faults on these lifecycles. It does not certify a system or replace a review of your own sender's documentation. Tested on synthetic data only: every payment, event, key and amount here is made up.

## Why

Senders say plainly that callbacks are neither unique nor ordered:

- Stripe: "Webhook endpoints might occasionally receive the same event more than once", and "Stripe doesn't guarantee the delivery of events in the order that they're generated" ([Stripe webhooks docs](https://docs.stripe.com/webhooks)).
- The Standard Webhooks spec keeps the `webhook-id` the same across retries and changes the timestamp on every attempt. It recommends a retry schedule spanning multiple days; its example runs to 75 hours. It also suggests using the id as an idempotency key, for example by saving ids "in redis for 5 minutes" ([Standard Webhooks spec](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md)).

Those two lines in the same spec are worth reading together. If a receiver credits the customer on each `payment.settled` and remembers ids for five minutes, a response lost twice means the third attempt arrives at 5 minutes 5 seconds, after the id is forgotten, and credits again. The harness finds that in a few cases:

```text
- pay_0003: accepted -> settled, 25000 cents
- fault: evt_0003_1: the first 3 successful response(s) never reach the sender

| +0:01:09 | evt_0003_1 | genuine | 0 | 200 | response lost |
| +0:01:14 | evt_0003_1 | genuine | 1 | 200 | response lost |
| +0:06:14 | evt_0003_1 | genuine | 2 | 200 | response lost |
| +0:36:14 | evt_0003_1 | genuine | 3 | 200 |  |

- BC-LEDGER (error) pay_0003: balance 75000, should be 25000 (settled)
```

A longer memory hides the problem until the gap between retries outgrows it. What fixes it is a ledger that moves with the payment's status: credit when the payment enters a credited status, take it back when it leaves, and ignore a status that cannot follow the current one. The id table then only saves work.

## What it checks

| rule | the receiver must |
|---|---|
| BC-LEDGER | end with a balance that matches each payment's true final status |
| BC-FINAL | end with the true final status |
| BC-ORDER | never move a status to one that cannot follow it (settled back to accepted, returned back to settled) |
| BC-ROLLBACK | leave nothing behind when it crashes mid-delivery |
| BC-AUTH | answer a tampered or forged copy with a 4xx and change nothing |
| BC-REPLAY | refuse a captured delivery resent after the timestamp window, and change nothing (accepting one that changes nothing is a warning) |
| BC-LIVENESS | acknowledge every genuine event with a 2xx before the sender runs out of retries |

BC-LIVENESS catches the opposite mistake to double crediting: a replay cache that answers the sender's own retry with 409 or 401. The sender keeps retrying, gives up after the last attempt, and may disable the endpoint.

## Lifecycles

| profile | statuses | credited while in |
|---|---|---|
| instant | accepted, then settled or rejected | settled |
| ach | submitted, settled, and possibly returned after settlement | settled |
| onchain | detected, confirmed, then finalized, or dropped by a reorganisation | confirmed, finalized |

These are models for testing, not descriptions of a particular network's message set. An instant payment that is later sent back is a new payment in the other direction, so `instant` has no returned status. Add your own `Lifecycle` if your sender's statuses differ.

## Use

Wrap your receiver in a small adapter with three methods:

```python
class MyReceiver:
    def __init__(self, profile: str): ...
    def handle(self, headers, body: bytes, now: float, hook) -> int: ...  # call hook("name") between writes
    def status(self, payment_id: str) -> str | None: ...
    def balance(self, payment_id: str) -> int: ...
```

`hook` is how crashes get in: call it after verifying, after each write and before committing, and the harness raises `Crash` at one of those points for some deliveries. Deliveries are signed with the Standard Webhooks scheme (`webhook-id`, `webhook-timestamp`, `webhook-signature`) using a made-up key in `bridgeconf.case.TEST_SECRET`; point your verifier at it in tests.

```sh
pip install 'bridgeconf @ git+https://github.com/BanroxArt/bridge-conformance'
bridgeconf demo                                   # the three reference receivers on every profile
bridgeconf run --target mypkg.adapter:MyReceiver --profile ach --cases 500 --save failures/
bridgeconf replay failures/BC-LEDGER.json --target mypkg.adapter:MyReceiver
```

`run` exits 2 if any case failed and writes the smallest failing case per rule as JSON, which `replay` runs again after you fix the bug. Cases are deterministic from the seed.

### Reference receivers

`bridgeconf demo`, 40 cases of 10 payments each:

| profile | naive | short-dedupe | careful |
|---|---|---|---|
| ach | 40 failing | 38 failing | 0 failing |
| instant | 37 failing | 28 failing | 0 failing |
| onchain | 40 failing | 40 failing | 0 failing |

- **naive** checks the signature and nothing else, credits on every credited event, and writes as it goes. It fails on every profile, including BC-ROLLBACK and BC-REPLAY.
- **short-dedupe** checks the signature and timestamp, writes in one transaction, remembers ids for five minutes, credits per event and takes the last status it heard. Out-of-order events and late retries break it. On chain it double counts even with no faults, because confirmed and finalized are both credited states.
- **careful** keeps ids for good in the same transaction as the ledger and applies only statuses that can follow the current one.

`examples/companions.py` builds the same careful behaviour from the webhook-verify and idempotency-store packages: the verifier without a replay cache (so retries are not refused), the idempotency store keyed by `webhook-id`, and forward-only status changes. It passes every profile. It also passes when its id memory is cut to five minutes, which is the point: the status machine carries the correctness.

## What is real and what is not

Real, with sources in [docs/sources.md](docs/sources.md): the Standard Webhooks signature scheme, retry behaviour and five-minute example; Stripe's statements on duplicates and ordering.

Not real: every payment and event; the lifecycles, which are simplified models; the fault rates. The harness runs in one process with a simulated clock. It does not test concurrency between two workers handling the same id at the same moment; for that, see the lease and fencing tests in idempotency-store.

## Development

```sh
make check    # ruff, content lint, mypy --strict, pytest
python bench/run.py
```

MIT licence. Copyright (c) 2026 Banrox Inc.
