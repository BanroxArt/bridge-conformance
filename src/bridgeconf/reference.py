"""Three reference receivers, from careless to careful, to show what the
harness catches. They keep state in memory; a real service would use a
database transaction where these use ``_Tx``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from . import sign
from .case import TEST_SECRET
from .lifecycle import PROFILES, Lifecycle
from .sut import Hook


@dataclass
class _State:
    status: dict[str, str] = field(default_factory=dict)
    balance: dict[str, int] = field(default_factory=dict)
    seen: dict[str, float] = field(default_factory=dict)  # event id -> remember until

    def copy(self) -> _State:
        return _State(dict(self.status), dict(self.balance), dict(self.seen))


class _Base:
    def __init__(self, profile: str = "ach", secret: str = TEST_SECRET) -> None:
        self.lc: Lifecycle = PROFILES[profile]
        self.secret = secret
        self.db = _State()

    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        raise NotImplementedError

    def status(self, payment_id: str) -> str | None:
        return self.db.status.get(payment_id)

    def balance(self, payment_id: str) -> int:
        return self.db.balance.get(payment_id, 0)

    def _move(self, st: _State, pid: str, new: str, amount: int, hook: Hook) -> None:
        """Set the status and post the ledger difference."""
        old = st.status.get(pid)
        was = old in self.lc.credited
        now = new in self.lc.credited
        if now and not was:
            st.balance[pid] = st.balance.get(pid, 0) + amount
        elif was and not now:
            st.balance[pid] = st.balance.get(pid, 0) - amount
        hook("ledger written")
        st.status[pid] = new
        hook("status written")


class Naive(_Base):
    """Checks the signature, nothing else. Credits on every delivery of a
    credited status, takes the last status it heard, writes as it goes."""

    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        try:
            sign.verify(self.secret, headers, body, now, tolerance_s=10**9)
        except sign.Invalid:
            return 401
        hook("verified")
        ev = json.loads(body)
        pid, new = ev["payment_id"], ev["status"]
        if new in self.lc.credited:
            self.db.balance[pid] = self.db.balance.get(pid, 0) + ev["amount_cents"]
        elif new not in self.lc.credited and self.db.status.get(pid) in self.lc.credited:
            self.db.balance[pid] = self.db.balance.get(pid, 0) - ev["amount_cents"]
        hook("ledger written")
        self.db.status[pid] = new
        hook("status written")
        return 200


class ShortDedupe(_Base):
    """Signature and timestamp checked, one transaction per delivery, event ids
    remembered for five minutes (the example in the Standard Webhooks spec).
    Each credited-status event posts a credit, as in "on payment.settled,
    credit the customer", and the status is whatever arrived last."""

    ttl_s = 300

    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        try:
            msg_id = sign.verify(self.secret, headers, body, now)
        except sign.Invalid:
            return 401
        if self.db.seen.get(msg_id, -1.0) >= now:
            return 200
        hook("verified")
        ev = json.loads(body)
        pid, new, amount = ev["payment_id"], ev["status"], ev["amount_cents"]
        tx = self.db.copy()
        if new in self.lc.credited:
            tx.balance[pid] = tx.balance.get(pid, 0) + amount
        elif tx.status.get(pid) in self.lc.credited:
            tx.balance[pid] = tx.balance.get(pid, 0) - amount
        hook("ledger written")
        tx.status[pid] = new
        tx.seen[msg_id] = now + self.ttl_s
        hook("before commit")
        self.db = tx
        return 200


class Careful(_Base):
    """Signature and timestamp checked; event ids kept for good in the same
    transaction as the ledger; a status is applied only if it can follow the
    current one, so late or repeated events are acknowledged and ignored."""

    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        try:
            msg_id = sign.verify(self.secret, headers, body, now)
        except sign.Invalid:
            return 401
        if msg_id in self.db.seen:
            return 200
        hook("verified")
        try:
            ev = json.loads(body)
            pid, new, amount = ev["payment_id"], ev["status"], ev["amount_cents"]
        except (ValueError, KeyError):
            return 400
        if new not in self.lc.statuses:
            return 422
        tx = self.db.copy()
        if self.lc.reachable(tx.status.get(pid), new):
            self._move(tx, pid, new, amount, hook)
        tx.seen[msg_id] = float("inf")
        hook("before commit")
        self.db = tx
        return 200


REFERENCE: dict[str, type[_Base]] = {"naive": Naive, "short-dedupe": ShortDedupe, "careful": Careful}
