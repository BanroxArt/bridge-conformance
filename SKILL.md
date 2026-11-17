---
name: bridge-conformance
description: Test a service that receives payment or stablecoin status callbacks (accepted, settled, returned, confirmed, finalized, dropped) and posts them to a ledger, by replaying known histories through injected faults (duplicates, reordering, lost responses with late retries, crashes between writes, stale replays, tampered and forged copies) and checking balances, final statuses, ordering, rollback, authentication and liveness. Use when an engineer is building or reviewing a webhook receiver for bank rails, card processors or stablecoin issuers, or a failure shows money credited twice. Uses the bridgeconf package from this repo. Engineering checklist only, not legal advice.
---

# bridge-conformance

You help an engineer find the delivery orders that break their receiver, then fix the receiver, not the test.

## 1. Adapter

- Wrap the receiver in a class with `handle(headers, body, now, hook)`, `status(payment_id)` and `balance(payment_id)`. Point its verifier at `bridgeconf.case.TEST_SECRET` and its clock at `now`.
- Put `hook("...")` after verification, after each write, and before commit. Without hooks the crash faults cannot reach it, and the log says so.
- Pick the lifecycle that matches the sender, or write one. Ask the engineer which statuses the sender can send after which.

## 2. Run

- `bridgeconf run --target module:Class --profile <profile> --cases 500 --save failures/`.
- Read the smallest case for each rule with the engineer: the timeline shows exactly which delivery did the damage.

## 3. Fix

- Double credits: post ledger entries on status transitions, not on events. Keep processed ids in the same transaction as the ledger, and keep them longer than the sender retries.
- Status going backwards: apply a status only if it can follow the current one; acknowledge and ignore the rest.
- Liveness failures: a known id must get a 2xx, not a 409 or 401.
- `bridgeconf replay failures/<rule>.json --target ...` until it passes, then run the campaign again with a new seed.

End with: engineering checklist, not legal advice; tested on synthetic data only.
