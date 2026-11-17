from __future__ import annotations

import pytest

from bridgeconf import ACH, INSTANT, ONCHAIN, case_from_json, generate, sign
from bridgeconf.case import OTHER_SECRET, T0, TEST_SECRET, Event


def test_lifecycles() -> None:
    assert ACH.reachable("submitted", "returned") and ACH.reachable("settled", "returned")
    assert not ACH.reachable("returned", "settled") and not ACH.reachable("settled", "settled")
    assert ACH.reachable(None, "settled") and not ACH.reachable(None, "teleported")
    assert sorted(ACH.paths()) == [
        ("submitted", "returned"),
        ("submitted", "settled"),
        ("submitted", "settled", "returned"),
    ]
    assert INSTANT.terminal("settled") and not INSTANT.terminal("accepted")
    assert ("detected", "confirmed", "dropped") in ONCHAIN.paths()
    assert ONCHAIN.credited == {"confirmed", "finalized"}


def test_signing() -> None:
    body = Event("evt_1", "pay_1", "settled", 100, T0, 0).body()
    h = sign.headers(TEST_SECRET, "evt_1", T0, body)
    assert sign.verify(TEST_SECRET, h, body, T0 + 299) == "evt_1"
    with pytest.raises(sign.Invalid, match="tolerance"):
        sign.verify(TEST_SECRET, h, body, T0 + 301)
    with pytest.raises(sign.Invalid, match="signature"):
        sign.verify(TEST_SECRET, h, body.replace(b"100", b"999"), T0)
    with pytest.raises(sign.Invalid, match="signature"):
        sign.verify(TEST_SECRET, sign.headers(OTHER_SECRET, "evt_1", T0, body), body, T0)
    with pytest.raises(sign.Invalid, match="missing"):
        sign.verify(TEST_SECRET, {}, body, T0)
    rotated = dict(h, **{"webhook-signature": "v1,AAAA " + h["webhook-signature"]})
    assert sign.verify(TEST_SECRET, rotated, body, T0) == "evt_1"


def test_generate_is_deterministic_and_follows_lifecycle() -> None:
    a, b = generate("ach", 30, 5), generate("ach", 30, 5)
    assert a == b and a != generate("ach", 30, 6)
    for evs in a.payments().values():
        assert tuple(e.status for e in evs) in ACH.paths()
        assert [e.at for e in evs] == sorted(e.at for e in evs)
    assert case_from_json(a.to_json()) == a


@pytest.mark.parametrize(
    "bad",
    [
        '{"profile": "telex", "events": [], "faults": []}',
        '{"profile": "ach", "events": [], "faults": [{"kind": "crash", "event_id": "nope", "param": 1}]}',
        '{"profile": "ach", "events": [{"id": "e", "payment_id": "p", "status": "settled", "amount_cents": 1,'
        ' "at": 0, "seq": 0}], "faults": [{"kind": "gremlin", "event_id": "e", "param": 1}]}',
    ],
)
def test_bad_case_files(bad: str) -> None:
    with pytest.raises(ValueError):
        case_from_json(bad)
