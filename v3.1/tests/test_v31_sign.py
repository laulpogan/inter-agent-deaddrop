"""
Tests for v3.1 wire format: event_id, kind ranges, sign-over-event-id.

Run: cd /home/admin/Source/inter-agent-deaddrop-v3 && python -m pytest tests/test_v31_sign.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signing import (
    KIND_RANGES,
    KINDS,
    canonical,
    compute_event_id,
    generate_keypair,
    kind_class,
    make_key_id,
    sign_message_v31,
    trust_add_key,
    verify_message_v31,
)


def _base_msg(handle="paul", kind=100):
    return {
        "timestamp": "2026-05-08T18:00:00Z",
        "from": handle,
        "kind": kind,
        "subject": "test",
        "body": "hello world",
        "refs": [],
        "priority": "normal",
        "correlation_id": "test-2026-05-08T18:00:00Z",
        "ack_required": False,
    }


def test_canonical_strict_escapes_drops_event_id():
    msg = _base_msg()
    msg["event_id"] = "ffff" * 16
    out = canonical(msg, strict_escapes=True)
    assert b"event_id" not in out


def test_canonical_v3_keeps_event_id():
    """v3.0 backwards compat: canonical without strict_escapes keeps event_id field."""
    msg = _base_msg()
    msg["event_id"] = "ffff" * 16
    out = canonical(msg, strict_escapes=False)
    assert b"event_id" in out


def test_compute_event_id_deterministic():
    msg = _base_msg()
    id1 = compute_event_id(msg)
    id2 = compute_event_id(msg)
    assert id1 == id2
    assert len(id1) == 64
    assert all(c in "0123456789abcdef" for c in id1)


def test_compute_event_id_differs_on_body_change():
    msg1 = _base_msg()
    msg2 = _base_msg()
    msg2["body"] = "different"
    assert compute_event_id(msg1) != compute_event_id(msg2)


def test_compute_event_id_ignores_signing_fields():
    """event_id must NOT change when public_key_id or signature added."""
    msg = _base_msg()
    base = compute_event_id(msg)
    msg["public_key_id"] = "paul:abc12345"
    msg["signature"] = "AAAA"
    msg["event_id"] = "ffff" * 16
    after = compute_event_id(msg)
    assert base == after


def test_sign_v31_attaches_event_id_and_sig():
    priv, pub = generate_keypair()
    msg = _base_msg()
    signed = sign_message_v31(msg, priv, pub, "paul")
    assert "event_id" in signed
    assert "public_key_id" in signed
    assert "signature" in signed
    assert signed["public_key_id"].startswith("paul:")


def test_verify_v31_passes_for_valid_message():
    priv, pub = generate_keypair()
    msg = _base_msg()
    signed = sign_message_v31(msg, priv, pub, "paul")

    trust = trust_add_key({}, "paul", pub, key_id=make_key_id("paul", pub))
    ok, reason = verify_message_v31(signed, trust)
    assert ok, f"verify failed: {reason}"


def test_verify_v31_rejects_tampered_body():
    priv, pub = generate_keypair()
    msg = _base_msg()
    signed = sign_message_v31(msg, priv, pub, "paul")
    signed["body"] = "tampered"

    trust = trust_add_key({}, "paul", pub, key_id=make_key_id("paul", pub))
    ok, reason = verify_message_v31(signed, trust)
    assert not ok
    assert "event_id mismatch" in reason


def test_verify_v31_rejects_swapped_event_id():
    priv, pub = generate_keypair()
    msg = _base_msg()
    signed = sign_message_v31(msg, priv, pub, "paul")
    # forge a fake event_id consistent with body content but a different message
    signed["event_id"] = "0" * 64

    trust = trust_add_key({}, "paul", pub, key_id=make_key_id("paul", pub))
    ok, reason = verify_message_v31(signed, trust)
    assert not ok
    assert "event_id mismatch" in reason


def test_verify_v31_rejects_wrong_signer():
    priv1, pub1 = generate_keypair()
    priv2, pub2 = generate_keypair()
    msg = _base_msg()
    # Sign with priv2 but claim to be paul (whose pubkey is pub1)
    signed = sign_message_v31(msg, priv2, pub2, "paul")

    # Trust only paul=pub1
    trust = trust_add_key({}, "paul", pub1, key_id=make_key_id("paul", pub1))
    ok, reason = verify_message_v31(signed, trust)
    assert not ok
    # Will fail at key_id-not-found because public_key_id is paul:<fingerprint(pub2)>
    assert "not found" in reason or "verification failed" in reason


def test_verify_v31_accepts_did_wire_from_field():
    priv, pub = generate_keypair()
    msg = _base_msg(handle="did:wire:paul")
    signed = sign_message_v31(msg, priv, pub, "paul")

    trust = trust_add_key({}, "paul", pub, key_id=make_key_id("paul", pub))
    ok, reason = verify_message_v31(signed, trust)
    assert ok, f"DID-form from should verify: {reason}"


def test_kind_class_ephemeral_range():
    assert kind_class(20000) == "ephemeral"
    assert kind_class(29999) == "ephemeral"
    assert kind_class(30000) == "addressable"  # boundary


def test_kind_class_regular_range():
    assert kind_class(1000) == "regular"
    assert kind_class(1100) == "regular"  # claim
    assert kind_class(9999) == "regular"


def test_kind_class_replaceable_range():
    assert kind_class(10000) == "replaceable"
    assert kind_class(10001) == "replaceable"
    assert kind_class(19999) == "replaceable"


def test_kind_class_addressable_range():
    assert kind_class(30000) == "addressable"
    assert kind_class(39999) == "addressable"


def test_kind_class_unknown_returns_none():
    assert kind_class(999999) is None


def test_kinds_dictionary_has_known_types():
    assert KINDS[100] == "heartbeat"
    assert KINDS[1100] == "claim"
    assert KINDS[10000] == "agent_card"
