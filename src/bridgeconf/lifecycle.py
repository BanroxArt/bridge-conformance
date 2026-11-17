"""Payment lifecycles: which statuses exist, which can follow which, and
which ones mean the money is on the ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property


@dataclass(frozen=True)
class Lifecycle:
    name: str
    # status -> statuses that may come next. A status missing from the keys is terminal.
    next: Mapping[str, frozenset[str]]
    first: frozenset[str]  # statuses a payment can start with
    credited: frozenset[str]  # while a payment is in one of these, its amount is on the ledger
    description: str = ""
    may_rest: frozenset[str] = frozenset()  # non-terminal statuses a payment may stay in for good

    @cached_property
    def statuses(self) -> frozenset[str]:
        out = set(self.first)
        for k, v in self.next.items():
            out.add(k)
            out |= v
        return frozenset(out)

    def terminal(self, status: str) -> bool:
        return not self.next.get(status)

    def reachable(self, frm: str | None, to: str) -> bool:
        """``to`` can come after ``frm`` (directly or later). From nothing, any status can."""
        if frm is None:
            return to in self.statuses
        seen: set[str] = set()
        stack = list(self.next.get(frm, ()))
        while stack:
            s = stack.pop()
            if s == to:
                return True
            if s not in seen:
                seen.add(s)
                stack.extend(self.next.get(s, ()))
        return False

    def paths(self) -> list[tuple[str, ...]]:
        """Every complete history: from a first status to a terminal one, or to
        one the payment may rest in."""
        out: list[tuple[str, ...]] = []

        def walk(path: tuple[str, ...]) -> None:
            nxt = self.next.get(path[-1], frozenset())
            if not nxt or path[-1] in self.may_rest:
                out.append(path)
            for s in sorted(nxt):
                walk((*path, s))

        for f in sorted(self.first):
            walk((f,))
        return out


def _fs(*xs: str) -> frozenset[str]:
    return frozenset(xs)


INSTANT = Lifecycle(
    "instant",
    {"accepted": _fs("settled", "rejected")},
    _fs("accepted", "rejected"),
    _fs("settled"),
    "An incoming instant credit (FedNow, RTP): accepted, then settled or rejected. A later "
    "return is a new payment in the other direction, not a status of this one.",
)

ACH = Lifecycle(
    "ach",
    {"submitted": _fs("settled", "returned"), "settled": _fs("returned")},
    _fs("submitted"),
    _fs("settled"),
    "An ACH credit: submitted, settled, and possibly returned after settlement.",
    _fs("settled"),
)

ONCHAIN = Lifecycle(
    "onchain",
    {"detected": _fs("confirmed", "dropped"), "confirmed": _fs("finalized", "dropped")},
    _fs("detected"),
    _fs("confirmed", "finalized"),
    "A stablecoin deposit seen on chain: detected, confirmed (credited), then finalized, or "
    "dropped by a reorganisation, which takes the credit back.",
)

PROFILES = {p.name: p for p in (INSTANT, ACH, ONCHAIN)}
