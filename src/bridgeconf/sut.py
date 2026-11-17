"""What a system under test looks like to the harness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class Crash(Exception):
    """Raised inside the system under test at a fault point the harness picked."""


class Hook(Protocol):
    def __call__(self, point: str) -> None: ...


def no_faults(point: str) -> None:
    return None


class System(Protocol):
    """Adapter around the service being tested.

    ``handle`` receives one HTTP delivery and returns the status code it would
    send. It should call ``hook(name)`` at the points where a crash would hurt
    (after verifying, after each write, before commit); the harness raises
    ``Crash`` at one of them for some deliveries. A crash must leave no trace:
    the harness treats it as a 500 and checks nothing changed.

    ``status`` and ``balance`` read what the service believes about one payment.
    Balance is in minor units, positive for money credited.
    """

    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int: ...

    def status(self, payment_id: str) -> str | None: ...

    def balance(self, payment_id: str) -> int: ...
