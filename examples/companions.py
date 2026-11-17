"""A receiver built from webhook-verify (signature and timestamp) and
idempotency-store (one execution per webhook-id), with forward-only status
changes, to run under the harness:

    bridgeconf run --target examples.companions:CompanionReceiver --profile ach

Needs ``pip install hookverify idemstore`` from their repositories.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from hookverify import StandardWebhooks, VerificationError
from idemstore import Acquired, IdempotencyGuard, InFlight, MemoryBackend, Mismatch, Replay, StoredResponse

from bridgeconf.case import TEST_SECRET
from bridgeconf.lifecycle import PROFILES
from bridgeconf.sut import Hook

WEEK = 7 * 86_400


class CompanionReceiver:
    def __init__(self, profile: str, secret: str = TEST_SECRET, keep_ids_s: float = WEEK) -> None:
        self.lc = PROFILES[profile]
        self.now = 0.0
        # No replay cache in the verifier: a legitimate retry carries the same
        # webhook-id and must get a 2xx, which the idempotency store gives it.
        self.verifier = StandardWebhooks(secret, tolerance_s=300, clock=lambda: self.now)
        # Keep ids longer than the sender retries (Standard Webhooks' example
        # schedule runs about 75 hours).
        self.guard = IdempotencyGuard(MemoryBackend(), lease_s=30, ttl_s=keep_ids_s, clock=lambda: self.now)
        self._status: dict[str, str] = {}
        self._balance: dict[str, int] = {}

    def status(self, payment_id: str) -> str | None:
        return self._status.get(payment_id)

    def balance(self, payment_id: str) -> int:
        return self._balance.get(payment_id, 0)

    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        self.now = now
        try:
            v = self.verifier.verify(headers, body)
        except VerificationError:
            return 401
        assert v.delivery_id is not None
        out = self.guard.begin("sender", v.delivery_id, hashlib.sha256(body).hexdigest())
        match out:
            case Replay(response):
                return response.status
            case InFlight():
                return 409
            case Mismatch():
                return 422
            case Acquired(lease):
                pass
        hook("verified")
        ev = json.loads(body)
        pid, new, amount = ev["payment_id"], ev["status"], ev["amount_cents"]
        # Work on copies and swap them in at the end: the in-memory stand-in
        # for one database transaction.
        status, balance = dict(self._status), dict(self._balance)
        old = status.get(pid)
        if self.lc.reachable(old, new):
            was, now_in = old in self.lc.credited, new in self.lc.credited
            if now_in and not was:
                balance[pid] = balance.get(pid, 0) + amount
            elif was and not now_in:
                balance[pid] = balance.get(pid, 0) - amount
            hook("ledger written")
            status[pid] = new
        hook("before commit")
        self._status, self._balance = status, balance
        # A crash between the commit above and this line leaves the key in
        # flight; the sender's retry gets 409, then takes over after the lease
        # and finds nothing left to do because the status already moved.
        self.guard.complete(lease, StoredResponse(200))
        return 200
