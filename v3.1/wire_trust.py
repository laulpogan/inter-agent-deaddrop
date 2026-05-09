"""
Wire trust — tiered trust + SAS verification (DESIGN-v1 Build #3).

Tiers (least → most privileged):
  UNTRUSTED — first contact via agent-card. Discovery only. Accept kind=10000 (agent_card),
              kind=100 (heartbeat), kind=10001 (trust_tier_announcement).
  VERIFIED  — operator confirmed identity via SAS. Accept all kinds EXCEPT kind=1100 (claim).
  ATTESTED  — N=10 successful reciprocated transactions completed. Accept all kinds.
  TRUSTED   — operator manually promoted. Bypass body-size cap and rate-limit.

SAS = Short Authentication String over sorted (did, pubkey) pairs (ESSENCE-v4 Amendment C).
Operators read aloud over voice/Signal/in-person. Match → run `wire_trust.verify_sas()`
which sets tier=VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from signing import KINDS, b64decode, b64encode, kind_class

TRUST_TIERS = ("UNTRUSTED", "VERIFIED", "ATTESTED", "TRUSTED")
TIER_ORDER = {tier: idx for idx, tier in enumerate(TRUST_TIERS)}

# Auto-promote ATTESTED after this many successful reciprocated transactions
ATTESTATION_THRESHOLD = 10

# Kind-class allowance per tier (from DESIGN-v1)
# Returns set of kinds (or "all" for blanket allow) acceptable AT or BELOW this tier
TIER_KIND_ALLOWLIST: dict[str, set[int] | str] = {
    "UNTRUSTED": {100, 10000, 10001},  # heartbeat + agent_card + trust_tier_announcement
    "VERIFIED": "all_except_claim",     # accept all kinds except 1100 (claim)
    "ATTESTED": "all",
    "TRUSTED": "all",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------- SAS ----------

def compute_sas_v31(*identities: tuple[str, bytes]) -> str:
    """
    Bilateral 6-digit SAS over sorted (did, pubkey) pairs (Amendment C).

    Either operator computes the same digit string regardless of order.
    Pubkey is bound to did to defeat same-key-different-handle confusion.

    Args:
      identities: (did_string, pubkey_bytes) tuples.

    Returns:
      6-digit string padded with leading zeros.
    """
    sorted_pairs = sorted(identities, key=lambda x: x[0])
    blob = b"".join(did.encode("utf-8") + b":" + pub for did, pub in sorted_pairs)
    h = hashlib.sha256(blob).digest()
    n = int.from_bytes(h[:4], "big") % 1_000_000
    return f"{n:06d}"


# ---------- trust.json schema upgrade ----------

def upgrade_trust_to_v31(trust: dict) -> dict:
    """
    Migrate v3.0 trust.json (no tier field) to v3.1 (tier per agent).

    Existing agents default to ATTESTED (assumed pre-trusted on existing wire).
    New agents from agent-card discovery enter as UNTRUSTED via add_agent_card_pin().
    """
    if trust.get("schema_version") == "v3.1":
        return trust

    out = dict(trust)
    out["schema_version"] = "v3.1"
    for agent_name, agent_entry in out.get("agents", {}).items():
        if "tier" not in agent_entry:
            agent_entry["tier"] = "ATTESTED"
            agent_entry["tier_set_at"] = now_utc()
            agent_entry["sas_verified"] = False
            agent_entry["successful_reciprocations"] = 0
    return out


def add_agent_card_pin(trust: dict, agent: str, pubkey_bytes: bytes, key_id: str, agent_card_url: str) -> dict:
    """
    Pin a new peer at UNTRUSTED tier from agent-card first-contact.

    Caller must have already verified agent-card sig via verify_agent_card().
    This pins the keys to trust.json. Operator must then run verify_sas() to promote.
    """
    out = dict(trust)
    if out.get("schema_version") != "v3.1":
        out = upgrade_trust_to_v31(out)

    agents = out.setdefault("agents", {})
    if agent in agents:
        # Add new key to existing agent without changing tier
        keys = agents[agent].setdefault("public_keys", [])
        if not any(k.get("key_id") == key_id for k in keys):
            keys.append({
                "key_id": key_id,
                "key": b64encode(pubkey_bytes),
                "added_at": now_utc(),
                "active": True,
            })
        return out

    agents[agent] = {
        "tier": "UNTRUSTED",
        "tier_set_at": now_utc(),
        "sas_verified": False,
        "successful_reciprocations": 0,
        "agent_card_url": agent_card_url,
        "agent_card_fetched_at": now_utc(),
        "public_keys": [{
            "key_id": key_id,
            "key": b64encode(pubkey_bytes),
            "added_at": now_utc(),
            "active": True,
        }],
    }
    return out


# ---------- tier promotion ----------

def verify_sas(trust: dict, agent: str, claimed_sas: str, expected_sas: str) -> tuple[dict, bool, str]:
    """
    Operator-invoked. Confirms SAS match → promote agent UNTRUSTED → VERIFIED.

    Args:
      trust: trust.json dict.
      agent: handle to promote.
      claimed_sas: what the operator typed (after reading aloud with peer).
      expected_sas: what compute_sas_v31() returned locally.

    Returns:
      (updated_trust, success_bool, reason_string)
    """
    if claimed_sas != expected_sas:
        return trust, False, f"SAS mismatch: got {claimed_sas} expected {expected_sas}"

    out = dict(trust)
    agents = out.setdefault("agents", {})
    if agent not in agents:
        return trust, False, f"agent {agent!r} not in trust"

    entry = agents[agent]
    current = entry.get("tier", "UNTRUSTED")
    if TIER_ORDER.get(current, 0) >= TIER_ORDER["VERIFIED"]:
        return out, True, f"agent {agent!r} already at tier {current!r}"

    entry["tier"] = "VERIFIED"
    entry["tier_set_at"] = now_utc()
    entry["sas_verified"] = True
    entry["sas_verified_at"] = now_utc()
    return out, True, f"agent {agent!r} promoted UNTRUSTED → VERIFIED"


def record_reciprocation(trust: dict, agent: str) -> dict:
    """
    Increment agent's successful_reciprocations counter.
    Auto-promotes VERIFIED → ATTESTED when counter reaches ATTESTATION_THRESHOLD.

    Reciprocation = signed message from peer, decisions.jsonl-ratified.
    Caller (responder) decides what counts as a "successful" reciprocation.
    """
    out = dict(trust)
    agents = out.setdefault("agents", {})
    if agent not in agents:
        return out

    entry = agents[agent]
    entry["successful_reciprocations"] = int(entry.get("successful_reciprocations", 0)) + 1

    if entry.get("tier") == "VERIFIED" and entry["successful_reciprocations"] >= ATTESTATION_THRESHOLD:
        entry["tier"] = "ATTESTED"
        entry["tier_set_at"] = now_utc()
        entry["auto_promoted_at"] = now_utc()

    return out


def promote_to_trusted(trust: dict, agent: str) -> tuple[dict, bool, str]:
    """
    Operator-invoked manual promotion ATTESTED → TRUSTED. Bypasses auto-thresholds.
    """
    out = dict(trust)
    agents = out.setdefault("agents", {})
    if agent not in agents:
        return trust, False, f"agent {agent!r} not in trust"
    entry = agents[agent]
    current = entry.get("tier", "UNTRUSTED")
    if TIER_ORDER.get(current, 0) < TIER_ORDER["ATTESTED"]:
        return trust, False, f"agent {agent!r} at {current!r}; must be ATTESTED before TRUSTED"

    entry["tier"] = "TRUSTED"
    entry["tier_set_at"] = now_utc()
    return out, True, f"agent {agent!r} promoted to TRUSTED"


# ---------- tier-gated message acceptance ----------

def accept_kind_for_tier(kind: int, tier: str) -> tuple[bool, str]:
    """
    Decide whether to accept a message of this kind from a peer at this tier.

    Returns (accept_bool, reason_string).
    """
    if tier not in TRUST_TIERS:
        return False, f"unknown tier {tier!r}"

    allowed = TIER_KIND_ALLOWLIST.get(tier)
    if allowed == "all":
        return True, "tier allows all kinds"
    if allowed == "all_except_claim":
        if kind == 1100:
            return False, "tier VERIFIED rejects kind=1100 (claim) — promote to ATTESTED"
        return True, "tier VERIFIED accepts non-claim kinds"
    if isinstance(allowed, set):
        if kind in allowed:
            return True, f"tier {tier} allowlist match"
        kind_name = KINDS.get(kind, f"kind={kind}")
        return False, f"tier {tier} rejects {kind_name}; allowed: {sorted(allowed)}"

    return False, f"no policy for tier {tier!r}"


def get_tier(trust: Mapping, agent: str) -> str:
    """Look up agent's tier; default UNTRUSTED if unknown."""
    entry = trust.get("agents", {}).get(agent)
    if not entry:
        return "UNTRUSTED"
    return entry.get("tier", "UNTRUSTED")


# ---------- file IO ----------

def load_trust(path: Path) -> dict:
    """Load + auto-upgrade trust.json."""
    if not path.exists():
        return upgrade_trust_to_v31({})
    return upgrade_trust_to_v31(json.loads(path.read_text()))


def save_trust(trust: dict, path: Path) -> None:
    """Persist trust.json with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trust, indent=2, sort_keys=False) + "\n")


__all__ = [
    "TRUST_TIERS",
    "TIER_ORDER",
    "TIER_KIND_ALLOWLIST",
    "ATTESTATION_THRESHOLD",
    "compute_sas_v31",
    "upgrade_trust_to_v31",
    "add_agent_card_pin",
    "verify_sas",
    "record_reciprocation",
    "promote_to_trusted",
    "accept_kind_for_tier",
    "get_tier",
    "load_trust",
    "save_trust",
]
