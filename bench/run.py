"""Time the harness against the careful reference receiver."""

from __future__ import annotations

import time

from bridgeconf import Careful, ShortDedupe, campaign, generate, run


def main() -> None:
    for payments in (20, 200, 2000):
        case = generate("ach", payments, 1)
        t0 = time.perf_counter()
        r = run(case, lambda: Careful("ach"))
        dt = time.perf_counter() - t0
        n = len(r.log)
        print(f"{payments:>5} payments: {n:>6} deliveries in {dt:.3f} s ({n / dt:,.0f} per s)")
    t0 = time.perf_counter()
    c = campaign(lambda: ShortDedupe("ach"), "ach", 100, 20, 0)
    took = time.perf_counter() - t0
    print(f"100-case campaign with shrinking, short-dedupe: {took:.2f} s, {len(c.examples)} rules shrunk")


if __name__ == "__main__":
    main()
