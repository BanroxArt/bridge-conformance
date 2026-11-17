"""A test case: what really happened to some payments, and what goes wrong on
the way to the system under test."""

from __future__ import annotations

import base64
import json
import random
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from .lifecycle import PROFILES, Lifecycle

T0 = 1_796_342_400  # 2026-12-03T00:00:00Z
# Made-up sender keys, derived from fixed phrases so no key material sits in the source.
TEST_SECRET = "whsec_" + base64.b64encode(b"bridge-conformance test sender").decode()
OTHER_SECRET = "whsec_" + base64.b64encode(b"bridge-conformance forger").decode()

FAULTS = ("duplicate", "reorder", "lost_response", "crash", "replay", "tamper", "forge")
DEFAULT_RATES: Mapping[str, float] = {
    "duplicate": 0.15,
    "reorder": 0.2,
    "lost_response": 0.1,
    "crash": 0.1,
    "replay": 0.05,
    "tamper": 0.03,
    "forge": 0.03,
}


@dataclass(frozen=True)
class Event:
    id: str
    payment_id: str
    status: str
    amount_cents: int
    at: int  # when the sender first tries to deliver it
    seq: int  # position in the sender's own order for this payment

    def body(self, currency: str = "USD") -> bytes:
        return json.dumps(
            {
                "type": f"payment.{self.status}",
                "event_id": self.id,
                "payment_id": self.payment_id,
                "status": self.status,
                "amount_cents": self.amount_cents,
                "currency": currency,
                "seq": self.seq,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()


@dataclass(frozen=True)
class Fault:
    kind: str
    event_id: str
    param: int = 0

    def describe(self) -> str:
        what = {
            "duplicate": f"sent twice, the copy {self.param} s later",
            "reorder": f"held back {self.param} s, so later events overtake it",
            "lost_response": f"the first {self.param} successful response(s) never reach the sender",
            "crash": f"the handler crashes at fault point {self.param}",
            "replay": f"an attacker resends a captured copy {self.param} s later",
            "tamper": "a copy with a changed amount and the original signature",
            "forge": "a copy signed with the wrong secret",
        }[self.kind]
        return f"{self.event_id}: {what}"


@dataclass(frozen=True)
class Case:
    profile: str
    events: tuple[Event, ...]
    faults: tuple[Fault, ...]
    seed: int = 0

    @property
    def lifecycle(self) -> Lifecycle:
        return PROFILES[self.profile]

    def payments(self) -> dict[str, list[Event]]:
        out: dict[str, list[Event]] = {}
        for e in self.events:
            out.setdefault(e.payment_id, []).append(e)
        for v in out.values():
            v.sort(key=lambda e: e.seq)
        return out

    def keep(self, payment_ids: set[str]) -> Case:
        ev = tuple(e for e in self.events if e.payment_id in payment_ids)
        ids = {e.id for e in ev}
        return Case(self.profile, ev, tuple(f for f in self.faults if f.event_id in ids), self.seed)

    def with_faults(self, faults: tuple[Fault, ...]) -> Case:
        return Case(self.profile, self.events, faults, self.seed)

    def to_json(self) -> str:
        return json.dumps(
            {
                "profile": self.profile,
                "seed": self.seed,
                "events": [asdict(e) for e in self.events],
                "faults": [asdict(f) for f in self.faults],
            },
            indent=1,
        )


def case_from_json(text: str) -> Case:
    d = json.loads(text)
    if d.get("profile") not in PROFILES:
        raise ValueError(f"unknown profile {d.get('profile')!r}")
    events = tuple(Event(**e) for e in d["events"])
    faults = tuple(Fault(**f) for f in d["faults"])
    ids = {e.id for e in events}
    for f in faults:
        if f.kind not in FAULTS or f.event_id not in ids:
            raise ValueError(f"bad fault {f}")
    return Case(d["profile"], events, faults, int(d.get("seed", 0)))


def generate(profile: str, payments: int, seed: int, rates: Mapping[str, float] = DEFAULT_RATES) -> Case:
    """Random payments that follow the lifecycle, and random faults on their events."""
    lc = PROFILES[profile]
    rng = random.Random(seed)
    paths = lc.paths()
    events: list[Event] = []
    faults: list[Fault] = []
    for i in range(payments):
        pid = f"pay_{i:04d}"
        amount = rng.choice([1_500, 25_000, 120_000, 999_999, 5_000_000])
        t = T0 + i * 20 + rng.randint(0, 15)
        for n, status in enumerate(rng.choice(paths)):
            t += 0 if n == 0 else rng.choice([1, 5, 30, 90, 600, 3600])
            events.append(Event(f"evt_{i:04d}_{n}", pid, status, amount, t, n))
    for e in events:
        for kind in FAULTS:
            if rng.random() < rates.get(kind, 0.0):
                param = {
                    "duplicate": rng.choice([0, 1, 20]),
                    "reorder": rng.choice([10, 120, 900, 4000]),
                    "lost_response": rng.choice([1, 1, 2, 3]),
                    "crash": rng.randint(1, 4),
                    "replay": rng.choice([900, 3600, 86_400]),
                    "tamper": 0,
                    "forge": 0,
                }[kind]
                faults.append(Fault(kind, e.id, param))
    return Case(profile, tuple(events), tuple(faults), seed)
