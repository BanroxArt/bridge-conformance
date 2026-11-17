from __future__ import annotations

from collections.abc import Mapping

from hypothesis import given, settings
from hypothesis import strategies as st

from bridgeconf import Careful, Case, Event, Fault, Naive, ShortDedupe, generate, run, shrink, sign
from bridgeconf.case import T0
from bridgeconf.sut import Hook


def one(profile: str, statuses: list[str], faults: list[tuple[str, int, int]], amount: int = 10_000) -> Case:
    evs = tuple(Event(f"e{i}", "p1", s, amount, T0 + 60 * i, i) for i, s in enumerate(statuses))
    return Case(profile, evs, tuple(Fault(k, f"e{i}", p) for k, i, p in faults))


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 100_000), profile=st.sampled_from(["ach", "instant", "onchain"]))
def test_careful_receiver_passes_everything(seed: int, profile: str) -> None:
    r = run(generate(profile, 8, seed), lambda: Careful(profile))
    assert r.violations == []


def test_clean_delivery_passes_all_three() -> None:
    c = one("ach", ["submitted", "settled"], [])
    for cls in (Naive, ShortDedupe, Careful):
        assert run(c, lambda cls=cls: cls("ach")).violations == []


def test_five_minute_dedupe_double_credits_a_retry() -> None:
    # One lost response: the retry 5 s later is inside the 300 s memory.
    assert (
        run(
            one("instant", ["accepted", "settled"], [("lost_response", 1, 1)]), lambda: ShortDedupe("instant")
        ).errors
        == []
    )
    # Two lost responses: the third attempt comes at +305 s, after the id was forgotten.
    r = run(
        one("instant", ["accepted", "settled"], [("lost_response", 1, 2)]), lambda: ShortDedupe("instant")
    )
    assert [v.rule for v in r.errors] == ["BC-LEDGER"] and "balance 20000" in r.errors[0].detail
    assert (
        run(
            one("instant", ["accepted", "settled"], [("lost_response", 1, 3)]), lambda: Careful("instant")
        ).errors
        == []
    )


def test_out_of_order_return_before_settlement() -> None:
    c = one("ach", ["submitted", "settled", "returned"], [("reorder", 1, 900)])
    bad = run(c, lambda: ShortDedupe("ach"))
    assert {"BC-ORDER", "BC-FINAL"} <= bad.rules()
    assert run(c, lambda: Careful("ach")).errors == []


def test_crash_between_writes_is_caught() -> None:
    c = one("ach", ["submitted", "settled"], [("crash", 1, 2)])
    r = run(c, lambda: Naive("ach"))
    assert "BC-ROLLBACK" in r.rules() and "BC-LEDGER" in r.rules()
    assert any(ln.note == "crashed at ledger written" for ln in r.log)
    assert run(c, lambda: Careful("ach")).errors == []


def test_unreached_crash_point_is_noted() -> None:
    r = run(one("ach", ["submitted"], [("crash", 0, 9)]), lambda: Careful("ach"))
    assert r.errors == [] and "not reached" in r.log[0].note


def test_stale_replay() -> None:
    c = one("onchain", ["detected", "confirmed", "dropped"], [("replay", 1, 3600)])
    r = run(c, lambda: Naive("onchain"))
    assert "BC-REPLAY" in r.rules()
    careful = run(c, lambda: Careful("onchain"))
    assert careful.violations == [] and any(ln.kind == "replay" and ln.code == 401 for ln in careful.log)


class _NoAuth(Careful):
    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        h = dict(headers)
        h["webhook-signature"] = sign.sign(self.secret, h["webhook-id"], int(h["webhook-timestamp"]), body)
        return super().handle(h, body, now, hook)


class _RejectsRetries(Careful):
    def handle(self, headers: Mapping[str, str], body: bytes, now: float, hook: Hook) -> int:
        if {k.lower(): v for k, v in headers.items()}["webhook-id"] in self.db.seen:
            return 409  # a replay cache that refuses the sender's legitimate retry
        return super().handle(headers, body, now, hook)


def test_unverified_tamper_and_retry_refusal() -> None:
    c = one("ach", ["submitted", "settled"], [("tamper", 1, 0)])
    assert "BC-AUTH" in run(c, lambda: _NoAuth("ach")).rules()
    r = run(one("ach", ["submitted", "settled"], [("lost_response", 1, 1)]), lambda: _RejectsRetries("ach"))
    assert r.rules() == {"BC-LIVENESS"} and "gave up" in r.errors[0].detail
    assert sum(1 for ln in r.log if ln.event_id == "e1") == 10


def test_shrink_finds_a_small_case() -> None:
    big = generate("ach", 25, 3)
    r = run(big, lambda: ShortDedupe("ach"))
    assert r.errors
    small = shrink(r, lambda: ShortDedupe("ach"))
    assert small.errors and len(small.case.payments()) == 1 and len(small.case.faults) <= 2
    assert sorted(r.rules())[0] in small.rules()


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(0, 100_000), profile=st.sampled_from(["ach", "instant", "onchain"]))
def test_without_faults_every_reference_receiver_passes(seed: int, profile: str) -> None:
    c = generate(profile, 6, seed, rates={})
    assert c.faults == ()
    # On chain, confirmed and finalized are both credited states, so a receiver
    # that credits per event double counts even when nothing goes wrong.
    for cls in (Careful,) if profile == "onchain" else (Naive, ShortDedupe, Careful):
        assert run(c, lambda cls=cls: cls(profile)).violations == []


def test_per_event_credit_double_counts_on_chain() -> None:
    c = one("onchain", ["detected", "confirmed", "finalized"], [])
    r = run(c, lambda: ShortDedupe("onchain"))
    assert r.rules() == {"BC-LEDGER"} and "balance 20000" in r.errors[0].detail


def test_finalized_before_confirmed() -> None:
    c = one("onchain", ["detected", "confirmed", "finalized"], [("reorder", 1, 900)])
    r = run(c, lambda: Careful("onchain"))
    assert r.errors == [] and r.case.events[2].status == "finalized"
    assert "BC-ORDER" in run(c, lambda: ShortDedupe("onchain")).rules()


def test_reorg_takes_the_credit_back() -> None:
    c = one("onchain", ["detected", "confirmed", "dropped"], [])
    r = run(c, lambda: Careful("onchain"))
    assert r.errors == []
    sut = Careful("onchain")
    run(c, lambda: sut)
    assert sut.balance("p1") == 0 and sut.status("p1") == "dropped"


def test_duplicate_copy_is_harmless_only_with_dedupe() -> None:
    c = one("instant", ["accepted", "settled"], [("duplicate", 1, 20)])
    assert "BC-LEDGER" in run(c, lambda: Naive("instant")).rules()
    assert run(c, lambda: ShortDedupe("instant")).errors == []


def test_ddmin() -> None:
    from bridgeconf.shrink import _ddmin

    fs = [Fault("duplicate", f"e{i}", i) for i in range(12)]
    need = {fs[3], fs[9]}
    out = _ddmin(fs, lambda xs: need <= set(xs))
    assert set(out) == need
    assert _ddmin(fs, lambda xs: True) == []
