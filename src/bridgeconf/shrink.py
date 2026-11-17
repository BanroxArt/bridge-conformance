"""Cut a failing case down to the payments and faults that matter."""

from __future__ import annotations

from collections.abc import Callable

from .case import Case, Fault
from .runner import Result, run
from .sut import System


def _ddmin(items: list[Fault], fails: Callable[[list[Fault]], bool]) -> list[Fault]:
    n = 2
    while len(items) >= 2:
        size = max(1, len(items) // n)
        chunks = [items[i : i + size] for i in range(0, len(items), size)]
        reduced = False
        for i in range(len(chunks)):
            rest = [f for j, c in enumerate(chunks) if j != i for f in c]
            if fails(rest):
                items, n, reduced = rest, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(items):
                break
            n = min(len(items), n * 2)
    if len(items) == 1 and fails([]):
        return []
    return items


def shrink(result: Result, factory: Callable[[], System]) -> Result:
    """Keep one failing rule, then drop payments and faults while it still fails."""
    if not result.errors:
        return result
    target = sorted(result.rules())[0]
    first = next(v for v in result.errors if v.rule == target)

    def fails(c: Case) -> bool:
        return target in run(c, factory).rules()

    case = result.case
    one = case.keep({first.payment_id})
    if fails(one):
        case = one
    else:
        for pid in list(case.payments()):
            smaller = case.keep(set(case.payments()) - {pid})
            if smaller.events and fails(smaller):
                case = smaller
    faults = _ddmin(list(case.faults), lambda fs: fails(case.with_faults(tuple(fs))))
    case = case.with_faults(tuple(faults))
    return run(case, factory)
