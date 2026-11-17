"""Command line: demo, run, replay."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from .case import case_from_json
from .fuzz import campaign
from .lifecycle import PROFILES
from .reference import REFERENCE
from .report import campaign_md, result_md
from .runner import run
from .sut import System

NOTE = "Engineering checklist, not legal advice. Tested on synthetic data only."


def load_target(spec: str, profile: str) -> Callable[[], System]:
    """``module:callable``. The callable gets the profile name and returns a fresh system."""
    if spec in REFERENCE:
        cls = REFERENCE[spec]

        def make() -> System:
            return cls(profile)

        return make
    mod_name, _, attr = spec.partition(":")
    if not attr:
        raise ValueError("target must be module:callable or a reference name: " + ", ".join(REFERENCE))
    sys.path.insert(0, os.getcwd())
    fn = getattr(importlib.import_module(mod_name), attr)
    return lambda: cast(System, fn(profile))


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="bridgeconf", description="Fault-injection harness for payment callbacks."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run the three reference receivers on every profile")
    d.add_argument("--cases", type=int, default=50)
    r = sub.add_parser("run", help="fuzz one receiver")
    r.add_argument("--target", required=True, help="module:callable, or naive, short-dedupe, careful")
    r.add_argument("--profile", choices=sorted(PROFILES), default="ach")
    r.add_argument("--cases", type=int, default=200)
    r.add_argument("--payments", type=int, default=20)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--save", help="directory for the smallest failing case per rule, as JSON")
    rp = sub.add_parser("replay", help="run one saved case again")
    rp.add_argument("case")
    rp.add_argument("--target", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "demo":
            for profile in sorted(PROFILES):
                for name in REFERENCE:
                    c = campaign(
                        load_target(name, profile),
                        profile,
                        a.cases,
                        10,
                        0,
                        shrink_examples=False,
                    )
                    rules = ", ".join(f"{k} {v}" for k, v in sorted(c.by_rule.items())) or "none"
                    print(
                        f"{profile:8} {name:13} failing cases {c.failing_cases:>3}/{a.cases}  errors: {rules}"
                    )
            print(NOTE)
            return 0
        if a.cmd == "replay":
            case = case_from_json(Path(a.case).read_text(encoding="utf-8"))
            res = run(case, load_target(a.target, case.profile))
            print(result_md(res))
            return 2 if res.errors else 0
        factory = load_target(a.target, a.profile)
        c = campaign(factory, a.profile, a.cases, a.payments, a.seed)
        print(campaign_md(a.target, c))
        if a.save:
            out = Path(a.save)
            out.mkdir(parents=True, exist_ok=True)
            for rule, ex in c.examples.items():
                (out / f"{rule}.json").write_text(ex.case.to_json() + "\n", encoding="utf-8")
        print(NOTE)
        return 2 if c.failing_cases else 0
    except (OSError, ValueError, ImportError, AttributeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
