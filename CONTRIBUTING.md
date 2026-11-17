# Contributing

Useful contributions:

- lifecycles for other senders, with the sender's documentation cited
- new fault kinds with a documented cause
- adapters for common web frameworks

Code changes:

- `ruff check .`, `ruff format --check .`, `python scripts/check.py`, `mypy` and `pytest -q` must pass.
- synthetic data only; never a real payment or a real signing key
- every claim about a sender cites its own documentation in docs/sources.md
- mypy --strict and the content lint must pass
- Synthetic data only. Never commit a real customer, account, address or case.
