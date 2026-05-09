"""
Agent Card — v3.1 wire format extension.

Per DESIGN-v1: a signed JSON document describing an agent's identity, keys,
capabilities, and offered trust tier. Lives at a well-known git URL.

Schema-compatible with Google A2A AgentCard (subset). Extends with:
- DID-formatted handle (`did:wire:<handle>`)
- Trust tier offered + required
- Per-policy limits (body size, clock skew, rate limit)
- Old verify keys for rotation transition

Discovery flow:
  1. Operator publishes <handle>.card.json to wire repo
  2. Peer fetches via HTTPS (TLS to github.com is one trust hop)
  3. Peer verifies sig in card body using key from card itself (TOFU)
  4. Peer pins keys to trust.json at tier=UNTRUSTED
  5. Operator runs SAS verification → tier=VERIFIED
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from signing import (
    b64decode,
    b64encode,
    canonical,
    fingerprint,
    make_key_id,
)

try:
    from nacl import signing as _signing
    _backend = "pynacl"
except ImportError:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        _backend = "cryptography"
    except ImportError:
        _backend = None


CARD_SCHEMA_VERSION = "v3.1"
DID_METHOD = "did:wire"


def did_for(handle: str) -> str:
    """Compute DID-formatted handle. `paul` -> `did:wire:paul`."""
    if handle.startswith("did:"):
        return handle
    return f"{DID_METHOD}:{handle}"


def card_canonical(card: Mapping[str, Any]) -> bytes:
    """Canonical bytes for sign/verify. Drops signature field only."""
    body = {k: v for k, v in card.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_agent_card(
    handle: str,
    public_key_bytes: bytes,
    *,
    name: str | None = None,
    host: str | None = None,
    agent_card_url: str | None = None,
    capabilities: list[str] | None = None,
    supported_kinds: list[int] | None = None,
    trust_tier_offered: str = "ATTESTED",
    trust_tier_required_from_peers: str = "VERIFIED",
    max_body_kb: int = 64,
    max_clock_skew_seconds: int = 300,
    rate_limit_msg_per_min: int = 60,
    old_verify_keys: dict[str, dict] | None = None,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build an unsigned agent card. Caller must sign_agent_card() before publishing."""
    key_id = make_key_id(handle, public_key_bytes)
    issued_at = issued_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "schema_version": CARD_SCHEMA_VERSION,
        "did": did_for(handle),
        "name": name or handle.capitalize(),
        "host": host or "",
        "agent_card_url": agent_card_url or "",
        "verify_keys": {
            f"ed25519:{key_id}": {
                "key": b64encode(public_key_bytes),
                "valid_from": issued_at,
                "valid_until": None,
            }
        },
        "old_verify_keys": old_verify_keys or {},
        "capabilities": capabilities or [
            "heartbeat", "claim", "release", "decision", "ship",
            "incident", "ack", "proposal",
        ],
        "supported_kinds": supported_kinds or [
            100, 1, 1100, 1101, 1200, 1201, 1300, 1400, 1500, 1600, 10000,
        ],
        "trust_tier_offered": trust_tier_offered,
        "trust_tier_required_from_peers": trust_tier_required_from_peers,
        "policies": {
            "max_message_body_kb": max_body_kb,
            "max_clock_skew_seconds": max_clock_skew_seconds,
            "rate_limit_msg_per_min": rate_limit_msg_per_min,
        },
        "issued_at": issued_at,
    }


def sign_agent_card(card: Mapping[str, Any], private_key_bytes: bytes) -> dict[str, Any]:
    """Sign card body and attach signature field."""
    if _backend is None:
        raise RuntimeError("no Ed25519 backend installed")

    payload = card_canonical(card)
    if _backend == "pynacl":
        sk = _signing.SigningKey(private_key_bytes)
        sig = sk.sign(payload).signature
    else:
        sk = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        sig = sk.sign(payload)

    out = dict(card)
    out["signature"] = b64encode(sig)
    return out


def verify_agent_card(card: Mapping[str, Any]) -> tuple[bool, str]:
    """
    Self-verify: check sig using a public key listed in the card itself (TOFU).

    Caller is responsible for higher-level trust decisions (pin to trust.json
    at UNTRUSTED tier, await SAS verification before promoting).

    Returns (ok, reason). reason is "" on success.
    """
    if _backend is None:
        return False, "no Ed25519 backend installed"
    if "signature" not in card:
        return False, "missing signature"
    if "verify_keys" not in card or not card["verify_keys"]:
        return False, "no verify_keys in card"

    sig_bytes = b64decode(card["signature"])
    payload = card_canonical(card)

    # Try each current verify_key until one matches
    for key_id, key_record in card["verify_keys"].items():
        try:
            pub_b = b64decode(key_record["key"])
            if _backend == "pynacl":
                from nacl.signing import VerifyKey
                VerifyKey(pub_b).verify(payload, sig_bytes)
            else:
                Ed25519PublicKey.from_public_bytes(pub_b).verify(sig_bytes, payload)
            return True, ""
        except Exception:
            continue

    return False, "no verify_key in card matched signature"


def write_card_file(card: Mapping[str, Any], path: Path) -> None:
    """Write card JSON to file with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, indent=2, sort_keys=False) + "\n")


def load_card_file(path: Path) -> dict[str, Any]:
    """Load and parse a card file. Does not verify."""
    return json.loads(path.read_text())


def compute_sas(*public_keys: bytes) -> str:
    """
    Short Authentication String. 6-digit code over sorted concat of pubkeys.
    Bilateral: either side computes the same digits regardless of order.

    Operators read aloud over voice/Signal/in-person to confirm match.
    """
    sorted_keys = sorted(public_keys)
    h = hashlib.sha256(b"".join(sorted_keys)).digest()
    n = int.from_bytes(h[:4], "big") % 1_000_000
    return f"{n:06d}"


__all__ = [
    "CARD_SCHEMA_VERSION",
    "DID_METHOD",
    "build_agent_card",
    "card_canonical",
    "compute_sas",
    "did_for",
    "load_card_file",
    "sign_agent_card",
    "verify_agent_card",
    "write_card_file",
]
