"""Fault-injection harness for services that turn payment callbacks into ledger entries."""

from .case import FAULTS, Case, Event, Fault, case_from_json, generate
from .fuzz import Campaign, campaign
from .lifecycle import ACH, INSTANT, ONCHAIN, PROFILES, Lifecycle
from .reference import REFERENCE, Careful, Naive, ShortDedupe
from .runner import RETRY_AFTER, RULES, Result, Violation, run
from .shrink import shrink
from .sut import Crash, Hook, System

__all__ = [
    "ACH",
    "FAULTS",
    "INSTANT",
    "ONCHAIN",
    "PROFILES",
    "REFERENCE",
    "RETRY_AFTER",
    "RULES",
    "Campaign",
    "Careful",
    "Case",
    "Crash",
    "Event",
    "Fault",
    "Hook",
    "Lifecycle",
    "Naive",
    "Result",
    "ShortDedupe",
    "System",
    "Violation",
    "campaign",
    "case_from_json",
    "generate",
    "run",
    "shrink",
]
__version__ = "0.1.0"
