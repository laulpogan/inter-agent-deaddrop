"""
Ed25519 signing helpers for inter-agent-deaddrop v3.

Backwards-compatible add-on to v2.0. Wraps `safe_append_jsonl` from examples/.

Dependencies: PyNaCl (preferred) or `cryptography`.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from nacl import signing as _signing
    _backend = "pynacl"
except ImportError:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives import serialization
        _backend = "cryptography"
    except ImportError:
        _backend = None


def _require_backend() -> None:
    if _backend is None:
        raise RuntimeError(
            "no Ed25519 backend installed. pip install pynacl OR pip install cryptography"
        )


def canonical(msg: Mapping[str, Any]) -> bytes:
    """Canonical serialization for sign/verify. Excludes signing fields."""
    body = {k: v for k, v in msg.items() if k not in ("public_key_id", "signature")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def fingerprint(public_key_bytes: bytes) -> str:
    """8-hex-char fingerprint over raw public key bytes."""
    return hashlib.sha256(public_key_bytes).hexdigest()[:8]


def make_key_id(agent: str, public_key_bytes: bytes) -> str:
    return f"{agent}:{fingerprint(public_key_bytes)}"


# ---------- key generation ----------

def generate_keypair() -> tuple[bytes, bytes]:
    """Returns (private_key_bytes, public_key_bytes), both 32 bytes."""
    _require_backend()
    if _backend == "pynacl":
        sk = _signing.SigningKey.generate()
        return bytes(sk), bytes(sk.verify_key)
    if _backend == "cryptography":
        sk = Ed25519PrivateKey.generate()
        priv = sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return priv, pub
    raise RuntimeError(f"unreachable: backend={_backend}")


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


# ---------- sign / verify ----------

def sign_message(
    msg: Mapping[str, Any],
    private_key_bytes: bytes,
    public_key_bytes: bytes,
    agent: str,
) -> dict[str, Any]:
    """Returns msg with public_key_id + signature added."""
    _require_backend()
    msg_dict = dict(msg)  # shallow copy
    payload = canonical(msg_dict)

    if _backend == "pynacl":
        sk = _signing.SigningKey(private_key_bytes)
        sig = sk.sign(payload).signature
    elif _backend == "cryptography":
        sk = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        sig = sk.sign(payload)
    else:
        raise RuntimeError(f"unreachable: backend={_backend}")

    msg_dict["public_key_id"] = make_key_id(agent, public_key_bytes)
    msg_dict["signature"] = b64encode(sig)
    return msg_dict


def verify_message(
    signed_msg: Mapping[str, Any],
    trust: Mapping[str, Any],
) -> tuple[bool, str]:
    """
    Verify signed_msg against trust dict.

    trust shape (subset of trust.json):
        {"agents": {"<agent>": {"public_keys": [{"key_id": "...", "key": "<b64>", "active": True}]}}}

    Returns (ok, reason). reason is "" on success.
    """
    _require_backend()
    if "public_key_id" not in signed_msg:
        return False, "missing public_key_id"
    if "signature" not in signed_msg:
        return False, "missing signature"

    key_id = signed_msg["public_key_id"]
    if ":" not in key_id:
        return False, f"malformed public_key_id: {key_id}"
    claimed_agent, _ = key_id.split(":", 1)

    # Cross-check against `from` field
    if signed_msg.get("from") != claimed_agent:
        return False, f"from={signed_msg.get('from')!r} mismatches public_key_id agent={claimed_agent!r}"

    # Look up key in trust
    agents = trust.get("agents", {})
    agent_entry = agents.get(claimed_agent)
    if not agent_entry:
        return False, f"agent {claimed_agent!r} not in trust list"

    matching_keys = [k for k in agent_entry.get("public_keys", []) if k.get("key_id") == key_id]
    if not matching_keys:
        return False, f"key_id {key_id!r} not found for agent {claimed_agent!r}"

    key_record = matching_keys[0]
    if not key_record.get("active", True):
        return False, f"key_id {key_id!r} is deactivated"

    public_key_bytes = b64decode(key_record["key"])
    payload = canonical(signed_msg)

    try:
        sig_bytes = b64decode(signed_msg["signature"])
    except Exception as e:
        return False, f"signature not valid base64: {e}"

    try:
        if _backend == "pynacl":
            from nacl.signing import VerifyKey
            vk = VerifyKey(public_key_bytes)
            vk.verify(payload, sig_bytes)
        elif _backend == "cryptography":
            pk = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            pk.verify(sig_bytes, payload)
    except Exception as e:
        return False, f"signature verification failed: {type(e).__name__}"

    return True, ""


# ---------- atomic signed append ----------

def signed_append_jsonl(
    path: Path,
    msg: Mapping[str, Any],
    private_key_bytes: bytes,
    public_key_bytes: bytes,
    agent: str,
) -> dict[str, Any]:
    """Sign msg, then atomically append. Returns the signed msg."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "examples"))
    from safe_append_jsonl import safe_append_jsonl  # type: ignore

    signed = sign_message(msg, private_key_bytes, public_key_bytes, agent)
    safe_append_jsonl(path, signed)
    return signed


# ---------- trust list helpers ----------

def trust_add_key(trust: dict, agent: str, public_key_bytes: bytes, key_id: str | None = None) -> dict:
    """Add a public key to trust. Returns updated trust."""
    if key_id is None:
        key_id = make_key_id(agent, public_key_bytes)
    agents = trust.setdefault("agents", {})
    entry = agents.setdefault(agent, {"public_keys": []})
    keys = entry["public_keys"]
    # idempotent: if key_id already present, no-op
    if not any(k.get("key_id") == key_id for k in keys):
        from datetime import datetime, timezone
        keys.append({
            "key_id": key_id,
            "key": b64encode(public_key_bytes),
            "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "active": True,
        })
    return trust


def trust_deactivate_key(trust: dict, key_id: str) -> dict:
    """Mark a key inactive. Returns updated trust."""
    for agent_entry in trust.get("agents", {}).values():
        for k in agent_entry.get("public_keys", []):
            if k.get("key_id") == key_id:
                k["active"] = False
    return trust


__all__ = [
    "canonical",
    "fingerprint",
    "make_key_id",
    "generate_keypair",
    "sign_message",
    "verify_message",
    "signed_append_jsonl",
    "trust_add_key",
    "trust_deactivate_key",
    "b64encode",
    "b64decode",
]
