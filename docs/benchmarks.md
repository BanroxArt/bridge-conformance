# Benchmarks

`python bench/run.py` runs generated ACH cases against the careful reference receiver, then a 100-case campaign with shrinking against short-dedupe. Measured on 2026-11-16 on an 8-vCPU Linux VM with CPython 3.13:

| payments | deliveries | time |
|---|---|---|
| 20 | 70 | 0.002 s |
| 200 | 682 | 0.015 s |
| 2,000 | 7,157 | 0.26 s |

A 100-case campaign of 20 payments each, shrinking one example per rule, takes about 0.14 s. The reference receivers copy their whole state for each transaction, which is why throughput drops on the largest case; your own receiver's speed will dominate.
