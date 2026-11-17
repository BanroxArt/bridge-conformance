"""Markdown for campaigns and single cases."""

from __future__ import annotations

import datetime as dt

from .case import T0
from .fuzz import Campaign
from .runner import RULES, Result


def _t(at: int) -> str:
    return f"+{dt.timedelta(seconds=at - T0)}"


def result_md(r: Result) -> str:
    lines = [
        f"Case: profile {r.case.profile}, {len(r.case.payments())} payment(s), {len(r.case.faults)} fault(s)",
        "",
    ]
    for pid, evs in r.case.payments().items():
        lines.append(
            f"- {pid}: " + " -> ".join(f"{e.status} ({e.id})" for e in evs) + f", {evs[0].amount_cents} cents"
        )
    for f in r.case.faults:
        lines.append(f"- fault: {f.describe()}")
    lines += ["", "| time | event | delivery | attempt | response | note |", "|---|---|---|---|---|---|"]
    for ln in r.log:
        lines.append(f"| {_t(ln.at)} | {ln.event_id} | {ln.kind} | {ln.attempt} | {ln.code} | {ln.note} |")
    lines.append("")
    for v in r.violations:
        lines.append(f"- **{v.rule}** ({v.severity}) {v.payment_id}: {v.detail}")
    return "\n".join(lines) + "\n"


def campaign_md(name: str, c: Campaign) -> str:
    lines = [
        f"### {name} on {c.profile}",
        "",
        f"{c.failing_cases} of {c.cases} cases failed ({c.payments} payments each).",
        "",
    ]
    if c.by_rule or c.warnings:
        lines += ["| rule | what it checks | errors | warnings |", "|---|---|---|---|"]
        for rule, what in RULES.items():
            if c.by_rule[rule] or c.warnings[rule]:
                lines.append(f"| {rule} | {what} | {c.by_rule[rule]} | {c.warnings[rule]} |")
        lines.append("")
    done: list[int] = []
    for _rule, ex in sorted(c.examples.items()):
        if id(ex) in done:
            continue
        done.append(id(ex))
        shown = sorted(r for r, e in c.examples.items() if e is ex)
        lines += [f"#### Smallest case found for {', '.join(shown)}", "", result_md(ex)]
    return "\n".join(lines) + "\n"
