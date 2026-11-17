"""Deliver a case to a system under test and check what it ends up believing."""

from __future__ import annotations

import heapq
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from . import sign
from .case import OTHER_SECRET, TEST_SECRET, Case, Event, Fault
from .sut import Crash, System

# Standard Webhooks' example retry schedule: seconds after the first attempt.
RETRY_AFTER = (5, 305, 2105, 9305, 27305, 63305, 113705, 185705, 272105)

RULES = {
    "BC-LEDGER": "the balance for a payment matches its true final status",
    "BC-FINAL": "the status a payment ends in matches its true final status",
    "BC-ORDER": "a status never moves to one that cannot follow it",
    "BC-ROLLBACK": "a crash mid-delivery leaves no partial write",
    "BC-AUTH": "a tampered or forged delivery gets a 4xx and changes nothing",
    "BC-REPLAY": "a stale captured delivery is refused and changes nothing",
    "BC-LIVENESS": "every genuine delivery is acknowledged with a 2xx before the sender gives up",
}


@dataclass(frozen=True)
class Violation:
    rule: str
    payment_id: str
    detail: str
    severity: str = "error"


@dataclass(frozen=True)
class LogLine:
    at: int
    event_id: str
    kind: str
    attempt: int
    code: int
    note: str = ""


@dataclass
class Result:
    case: Case
    violations: list[Violation] = field(default_factory=list)
    log: list[LogLine] = field(default_factory=list)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    def rules(self) -> set[str]:
        return {v.rule for v in self.errors}


@dataclass(order=True)
class _Delivery:
    at: int
    order: int
    event_id: str = field(compare=False)
    kind: str = field(compare=False)  # genuine, duplicate, replay, tamper, forge
    attempt: int = field(compare=False, default=0)
    first_at: int = field(compare=False, default=0)
    signed_at: int = field(compare=False, default=0)


def _tampered(e: Event) -> bytes:
    d = json.loads(e.body())
    d["amount_cents"] = e.amount_cents * 100
    return json.dumps(d, separators=(",", ":"), sort_keys=True).encode()


def run(case: Case, factory: Callable[[], System]) -> Result:
    sut = factory()
    lc = case.lifecycle
    res = Result(case)
    events = {e.id: e for e in case.events}
    by_event: dict[str, list[Fault]] = {}
    for f in case.faults:
        by_event.setdefault(f.event_id, []).append(f)
    q: list[_Delivery] = []
    order = 0

    def push(
        at: int,
        eid: str,
        kind: str,
        attempt: int = 0,
        first_at: int | None = None,
        signed_at: int | None = None,
    ) -> None:
        nonlocal order
        order += 1
        heapq.heappush(
            q,
            _Delivery(
                at,
                order,
                eid,
                kind,
                attempt,
                at if first_at is None else first_at,
                at if signed_at is None else signed_at,
            ),
        )

    for e in case.events:
        fs = by_event.get(e.id, [])
        delay = sum(f.param for f in fs if f.kind == "reorder")
        push(e.at + delay, e.id, "genuine")
        for f in fs:
            if f.kind == "duplicate":
                push(e.at + delay + f.param, e.id, "duplicate")
            elif f.kind == "replay":
                # signed when first sent, resent later unchanged
                push(e.at + delay + f.param, e.id, "replay", signed_at=e.at + delay)
            elif f.kind in ("tamper", "forge"):
                push(e.at + delay + 1, e.id, f.kind)
    lost_left = {eid: sum(f.param for f in fs if f.kind == "lost_response") for eid, fs in by_event.items()}
    crash_left = {eid: [f.param for f in fs if f.kind == "crash"] for eid, fs in by_event.items()}
    acked: set[str] = set()
    gave_up: set[str] = set()
    prev_status: dict[str, str | None] = {}

    while q:
        d = heapq.heappop(q)
        e = events[d.event_id]
        pid = e.payment_id
        body = e.body()
        secret = TEST_SECRET
        if d.kind == "tamper":
            body = _tampered(e)
            hdrs = sign.headers(TEST_SECRET, e.id, d.signed_at, e.body())
        else:
            if d.kind == "forge":
                secret = OTHER_SECRET
            hdrs = sign.headers(secret, e.id, d.signed_at, body)
        before = (sut.status(pid), sut.balance(pid))
        crash_at: int | None = None
        if d.kind in ("genuine", "duplicate") and crash_left.get(e.id):
            crash_at = crash_left[e.id].pop(0)
        calls = 0

        def hook(point: str, crash_at: int | None = crash_at) -> None:
            nonlocal calls
            calls += 1
            if crash_at is not None and calls == crash_at:
                raise Crash(point)

        note = ""
        try:
            code = sut.handle(hdrs, body, float(d.at), hook)
        except Crash as c:
            code, note = 500, f"crashed at {c.args[0]}"
        if crash_at is not None and not note:
            note = f"crash point {crash_at} not reached ({calls} fault points)"
        after = (sut.status(pid), sut.balance(pid))
        cur = after[0]
        if note.startswith("crashed") and after != before:
            res.violations.append(
                Violation("BC-ROLLBACK", pid, f"{e.id} {note}; state went from {before} to {after}")
            )
        if d.kind in ("tamper", "forge"):
            if not 400 <= code < 500:
                res.violations.append(Violation("BC-AUTH", pid, f"{d.kind} copy of {e.id} got {code}"))
            if after != before:
                res.violations.append(
                    Violation("BC-AUTH", pid, f"{d.kind} copy of {e.id} changed state {before} -> {after}")
                )
        if d.kind == "replay":
            stale = d.at - d.signed_at > sign.TOLERANCE_S
            if after != before:
                res.violations.append(
                    Violation("BC-REPLAY", pid, f"replayed {e.id} changed state {before} -> {after}")
                )
            elif stale and 200 <= code < 300:
                res.violations.append(
                    Violation(
                        "BC-REPLAY",
                        pid,
                        f"replayed {e.id}, signed {d.at - d.signed_at} s earlier, was accepted",
                        "warn",
                    )
                )
        p = prev_status.get(pid)
        if cur != p and cur is not None:
            if cur not in lc.statuses:
                res.violations.append(Violation("BC-ORDER", pid, f"unknown status {cur!r}"))
            elif p is not None and not lc.reachable(p, cur):
                res.violations.append(
                    Violation("BC-ORDER", pid, f"status went {p} -> {cur} on {d.kind} {e.id}")
                )
        prev_status[pid] = cur
        res.log.append(LogLine(d.at, e.id, d.kind, d.attempt, code, note))
        if d.kind in ("genuine", "duplicate"):
            ok = 200 <= code < 300
            if ok and lost_left.get(e.id, 0) > 0:
                lost_left[e.id] -= 1
                ok = False
                res.log[-1] = LogLine(d.at, e.id, d.kind, d.attempt, code, "response lost")
            if ok:
                acked.add(e.id)
            elif d.kind == "genuine":
                if d.attempt < len(RETRY_AFTER):
                    at = d.first_at + RETRY_AFTER[d.attempt]
                    push(at, e.id, "genuine", d.attempt + 1, d.first_at)
                else:
                    gave_up.add(e.id)

    for pid, evs in case.payments().items():
        final = evs[-1].status
        want = evs[0].amount_cents if final in lc.credited else 0
        got_s, got_b = sut.status(pid), sut.balance(pid)
        if got_s != final:
            res.violations.append(Violation("BC-FINAL", pid, f"ended {got_s}, truly {final}"))
        if got_b != want:
            res.violations.append(Violation("BC-LEDGER", pid, f"balance {got_b}, should be {want} ({final})"))
        for e in evs:
            if e.id not in acked:
                why = "sender gave up after every retry" if e.id in gave_up else "never acknowledged"
                res.violations.append(Violation("BC-LIVENESS", pid, f"{e.id} ({e.status}): {why}"))
    return res
