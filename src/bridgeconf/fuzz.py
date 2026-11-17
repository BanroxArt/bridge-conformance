"""Run many random cases and collect what breaks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .case import DEFAULT_RATES, generate
from .runner import Result, run
from .shrink import shrink
from .sut import System


@dataclass
class Campaign:
    profile: str
    cases: int
    payments: int
    failing_cases: int = 0
    by_rule: Counter[str] = field(default_factory=Counter)
    warnings: Counter[str] = field(default_factory=Counter)
    examples: dict[str, Result] = field(default_factory=dict)  # rule -> shrunk failing case


def campaign(
    factory: Callable[[], System],
    profile: str,
    cases: int = 100,
    payments: int = 20,
    seed: int = 0,
    rates: Mapping[str, float] = DEFAULT_RATES,
    shrink_examples: bool = True,
) -> Campaign:
    out = Campaign(profile, cases, payments)
    for i in range(cases):
        r = run(generate(profile, payments, seed + i, rates), factory)
        for v in r.violations:
            (out.by_rule if v.severity == "error" else out.warnings)[v.rule] += 1
        if r.errors:
            out.failing_cases += 1
            for rule in sorted(r.rules()):
                if rule not in out.examples and shrink_examples:
                    focused = Result(r.case, [v for v in r.errors if v.rule == rule], r.log)
                    small = shrink(focused, factory)
                    for shown in small.rules() or {rule}:
                        out.examples.setdefault(shown, small)
    return out
