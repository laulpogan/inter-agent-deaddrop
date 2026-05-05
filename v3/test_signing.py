"""
Round-trip tests for v3 signing.

Run with: python3 v3/test_signing.py
Or via pytest if available.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signing import (
    canonical,
    fingerprint,
    generate_keypair,
    make_key_id,
    sign_message,
    signed_append_jsonl,
    trust_add_key,
    trust_deactivate_key,
    verify_message,
)


def assert_eq(a, b, label=""):
    if a != b:
        raise AssertionError(f"{label}: expected {b!r}, got {a!r}")


def test_canonical_stable():
    msg1 = {"a": 1, "b": 2, "from": "x"}
    msg2 = {"b": 2, "from": "x", "a": 1}
    assert_eq(canonical(msg1), canonical(msg2), "key order")
    msg3 = {"a": 1, "b": 2, "from": "x", "signature": "ignored", "public_key_id": "ignored"}
    assert_eq(canonical(msg1), canonical(msg3), "signing fields excluded")
    print("OK canonical_stable")


def test_keypair_generation():
    priv, pub = generate_keypair()
    assert len(priv) == 32, f"private_key len={len(priv)}"
    assert len(pub) == 32, f"public_key len={len(pub)}"
    assert priv != pub
    fp = fingerprint(pub)
    assert len(fp) == 8 and all(c in "0123456789abcdef" for c in fp)
    print(f"OK keypair_generation (fingerprint={fp})")


def test_sign_verify_roundtrip():
    priv, pub = generate_keypair()
    msg = {
        "timestamp": "2026-05-05T16:00:00Z",
        "from": "agent_a",
        "type": "heartbeat",
        "subject": "test",
        "body": "hello",
        "refs": [],
        "priority": "low",
        "correlation_id": "2026-05-05T16:00:00Z",
        "ack_required": False,
    }
    signed = sign_message(msg, priv, pub, "agent_a")
    assert "signature" in signed
    assert "public_key_id" in signed
    assert signed["public_key_id"] == make_key_id("agent_a", pub)

    trust = trust_add_key({}, "agent_a", pub)
    ok, reason = verify_message(signed, trust)
    assert ok, f"verify failed: {reason}"
    print(f"OK sign_verify_roundtrip (key_id={signed['public_key_id']})")


def test_tamper_detection():
    priv, pub = generate_keypair()
    msg = {
        "timestamp": "2026-05-05T16:00:00Z",
        "from": "agent_a",
        "type": "ship",
        "subject": "tamper test",
        "body": "original",
        "refs": [],
        "priority": "medium",
        "correlation_id": "2026-05-05T16:00:00Z",
        "ack_required": False,
    }
    signed = sign_message(msg, priv, pub, "agent_a")
    trust = trust_add_key({}, "agent_a", pub)

    # Tamper with body
    tampered = dict(signed)
    tampered["body"] = "tampered"
    ok, reason = verify_message(tampered, trust)
    assert not ok, "tampered message should fail verification"
    assert "signature verification failed" in reason
    print("OK tamper_detection (body change rejected)")

    # Tamper with from-field
    tampered2 = dict(signed)
    tampered2["from"] = "agent_b"
    ok, reason = verify_message(tampered2, trust)
    assert not ok, "from-field mismatch should fail"
    assert "mismatches" in reason
    print("OK tamper_detection (from mismatch rejected)")


def test_unknown_key():
    priv1, pub1 = generate_keypair()
    priv2, pub2 = generate_keypair()
    msg = {
        "timestamp": "2026-05-05T16:00:00Z",
        "from": "agent_a",
        "type": "ship",
        "subject": "unknown key test",
        "body": "x",
        "refs": [],
        "priority": "low",
        "correlation_id": "2026-05-05T16:00:00Z",
        "ack_required": False,
    }
    # Sign with key1, but trust list only knows key2
    signed = sign_message(msg, priv1, pub1, "agent_a")
    trust = trust_add_key({}, "agent_a", pub2)
    ok, reason = verify_message(signed, trust)
    assert not ok
    assert "not found" in reason
    print("OK unknown_key (rejected)")


def test_deactivated_key():
    priv, pub = generate_keypair()
    msg = {
        "timestamp": "2026-05-05T16:00:00Z",
        "from": "agent_a",
        "type": "heartbeat",
        "subject": "deactivated test",
        "body": "x",
        "refs": [],
        "priority": "low",
        "correlation_id": "2026-05-05T16:00:00Z",
        "ack_required": False,
    }
    signed = sign_message(msg, priv, pub, "agent_a")
    trust = trust_add_key({}, "agent_a", pub)
    key_id = make_key_id("agent_a", pub)
    trust = trust_deactivate_key(trust, key_id)

    ok, reason = verify_message(signed, trust)
    assert not ok
    assert "deactivated" in reason
    print("OK deactivated_key (rejected)")


def test_jsonl_roundtrip():
    priv, pub = generate_keypair()
    trust = trust_add_key({}, "agent_a", pub)

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = Path(f.name)

    try:
        msg = {
            "timestamp": "2026-05-05T16:00:00Z",
            "from": "agent_a",
            "type": "ship",
            "subject": "jsonl roundtrip",
            "body": "v3 signed jsonl test",
            "refs": [],
            "priority": "low",
            "correlation_id": "2026-05-05T16:00:00Z",
            "ack_required": False,
        }
        signed = signed_append_jsonl(path, msg, priv, pub, "agent_a")

        # Read back and verify
        with path.open("r") as fh:
            line = fh.readline().strip()
        parsed = json.loads(line)
        assert parsed["from"] == "agent_a"
        assert parsed["signature"] == signed["signature"]
        ok, reason = verify_message(parsed, trust)
        assert ok, f"jsonl readback verify failed: {reason}"
        print("OK jsonl_roundtrip")
    finally:
        path.unlink()


def test_two_agent_exchange():
    priv_a, pub_a = generate_keypair()
    priv_b, pub_b = generate_keypair()

    # Build mutual trust
    trust = trust_add_key({}, "agent_a", pub_a)
    trust = trust_add_key(trust, "agent_b", pub_b)

    msg_a = {
        "timestamp": "2026-05-05T16:00:00Z",
        "from": "agent_a",
        "type": "proposal",
        "subject": "mutual exchange",
        "body": "v3 two-party test",
        "refs": [],
        "priority": "high",
        "correlation_id": "2026-05-05T16:00:00Z",
        "ack_required": True,
    }
    signed_a = sign_message(msg_a, priv_a, pub_a, "agent_a")
    ok, reason = verify_message(signed_a, trust)
    assert ok, f"agent_a -> trust: {reason}"

    msg_b = {
        "timestamp": "2026-05-05T16:00:30Z",
        "from": "agent_b",
        "type": "ack",
        "subject": "mutual exchange acked",
        "body": "yes",
        "refs": [],
        "priority": "high",
        "correlation_id": "2026-05-05T16:00:00Z",
        "ack_required": False,
    }
    signed_b = sign_message(msg_b, priv_b, pub_b, "agent_b")
    ok, reason = verify_message(signed_b, trust)
    assert ok, f"agent_b -> trust: {reason}"

    # agent_a cannot forge as agent_b (different key)
    forged = dict(msg_b)
    signed_forged = sign_message(forged, priv_a, pub_a, "agent_a")  # signed by a, claims a
    signed_forged["from"] = "agent_b"  # tamper
    ok, reason = verify_message(signed_forged, trust)
    assert not ok
    print("OK two_agent_exchange + forgery rejected")


def main():
    print(f"v3 signing tests (backend autodetect)")
    test_canonical_stable()
    test_keypair_generation()
    test_sign_verify_roundtrip()
    test_tamper_detection()
    test_unknown_key()
    test_deactivated_key()
    test_jsonl_roundtrip()
    test_two_agent_exchange()
    print("\nAll v3 signing tests PASS")


if __name__ == "__main__":
    main()
