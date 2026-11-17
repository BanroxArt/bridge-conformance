"""Standard Webhooks signing: HMAC-SHA256 over ``id.timestamp.body``, base64,
sent as ``webhook-signature: v1,<sig>``."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from typing import Final

TOLERANCE_S: Final = 300


def secret_bytes(secret: str) -> bytes:
    return base64.b64decode(secret.removeprefix("whsec_"), validate=True)


def sign(secret: str, msg_id: str, ts: int, body: bytes) -> str:
    mac = hmac.new(secret_bytes(secret), f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def headers(secret: str, msg_id: str, ts: int, body: bytes) -> dict[str, str]:
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": sign(secret, msg_id, ts, body),
        "content-type": "application/json",
    }


class Invalid(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def verify(secret: str, h: Mapping[str, str], body: bytes, now: float, tolerance_s: int = TOLERANCE_S) -> str:
    """Return the message id, or raise Invalid. Used by the reference handlers."""
    lower = {k.lower(): v for k, v in h.items()}
    try:
        msg_id, ts_raw, sigs = lower["webhook-id"], lower["webhook-timestamp"], lower["webhook-signature"]
    except KeyError as e:
        raise Invalid(f"missing header {e.args[0]}") from e
    if not ts_raw.isdigit():
        raise Invalid("bad timestamp")
    want = sign(secret, msg_id, int(ts_raw), body).split(",", 1)[1]
    if not any(
        v == "v1" and hmac.compare_digest(s, want) for v, _, s in (p.partition(",") for p in sigs.split())
    ):
        raise Invalid("bad signature")
    if abs(now - int(ts_raw)) > tolerance_s:
        raise Invalid("timestamp outside tolerance")
    return msg_id
