"""
Tests for wire_trust.py — DESIGN-v1 build #3.

Run: cd /home/admin/Source/inter-agent-deaddrop-v3 && python -m pytest tests/test_wire_trust.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signing import generate_keypair, make_key_id
from wire_trust import (
    ATTESTATION_THRESHOLD,
    TIER_ORDER,
    TRUST_TIERS,
    accept_kind_for_tier,
    add_agent_card_pin,
    compute_sas_v31,
    get_tier,
    load_trust,
    promote_to_trusted,
    record_reciprocation,
    save_trust,
    upgrade_trust_to_v31,
    verify_sas,
)


# ---------- SAS ----------

def test_sas_v31_bilateral_symmetry():
    _, pa = generate_keypair()
    _, pb = generate_keypair()
    sas_ab = compute_sas_v31(("did:wire:paul", pa), ("did:wire:willard", pb))
    sas_ba = compute_sas_v31(("did:wire:willard", pb), ("did:wire:paul", pa))
    assert sas_ab == sas_ba
    assert len(sas_ab) == 6
    assert sas_ab.isdigit()


def test_sas_v31_differs_for_different_handles_same_keys():
    _, pa = generate_keypair()
    _, pb = generate_keypair()
    sas_paul = compute_sas_v31(("did:wire:paul", pa), ("did:wire:willard", pb))
    sas_eve = compute_sas_v31(("did:wire:eve", pa), ("did:wire:willard", pb))
    # Different DIDs → different SAS even if pubkeys identical
    assert sas_paul != sas_eve


def test_sas_v31_differs_for_different_keys():
    _, p1 = generate_keypair()
    _, p2 = generate_keypair()
    _, p3 = generate_keypair()
    sas_12 = compute_sas_v31(("did:wire:paul", p1), ("did:wire:willard", p2))
    sas_13 = compute_sas_v31(("did:wire:paul", p1), ("did:wire:willard", p3))
    assert sas_12 != sas_13


# ---------- schema upgrade ----------

def test_upgrade_v3_to_v31_adds_tier():
    v3 = {"version": 1, "agents": {"paul": {"public_keys": [{"key_id": "paul:abc", "key": "k", "active": True}]}}}
    v31 = upgrade_trust_to_v31(v3)
    assert v31["schema_version"] == "v3.1"
    assert v31["agents"]["paul"]["tier"] == "ATTESTED"  # legacy agents default to ATTESTED
    assert v31["agents"]["paul"]["sas_verified"] is False
    assert v31["agents"]["paul"]["successful_reciprocations"] == 0


def test_upgrade_idempotent():
    v3 = {"version": 1, "agents": {"paul": {"public_keys": []}}}
    v31_a = upgrade_trust_to_v31(v3)
    v31_b = upgrade_trust_to_v31(v31_a)
    assert v31_a == v31_b


# ---------- agent-card pin ----------

def test_add_agent_card_pin_enters_at_untrusted():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(
        trust, "willard-spark", pub,
        key_id="willard-spark:abc",
        agent_card_url="https://example.com/willard.card.json",
    )
    assert trust["agents"]["willard-spark"]["tier"] == "UNTRUSTED"
    assert trust["agents"]["willard-spark"]["sas_verified"] is False


def test_add_agent_card_pin_existing_agent_keeps_tier():
    """Adding a new key to an existing agent must NOT downgrade their tier."""
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    trust = {"version": 1, "agents": {"paul": {"public_keys": [{"key_id": "paul:abc", "key": "k", "active": True}]}}}
    trust = upgrade_trust_to_v31(trust)
    assert trust["agents"]["paul"]["tier"] == "ATTESTED"

    trust = add_agent_card_pin(trust, "paul", pub2, "paul:def", "https://example.com")
    # Existing tier preserved
    assert trust["agents"]["paul"]["tier"] == "ATTESTED"
    # New key added
    assert len(trust["agents"]["paul"]["public_keys"]) == 2


# ---------- SAS verification ----------

def test_verify_sas_promotes_untrusted_to_verified():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")
    assert trust["agents"]["willard"]["tier"] == "UNTRUSTED"

    trust, ok, reason = verify_sas(trust, "willard", "123456", "123456")
    assert ok, reason
    assert trust["agents"]["willard"]["tier"] == "VERIFIED"
    assert trust["agents"]["willard"]["sas_verified"] is True


def test_verify_sas_rejects_mismatch():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")

    trust, ok, reason = verify_sas(trust, "willard", "123456", "999999")
    assert not ok
    assert "mismatch" in reason
    assert trust["agents"]["willard"]["tier"] == "UNTRUSTED"


def test_verify_sas_idempotent_on_already_verified():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")
    trust, _, _ = verify_sas(trust, "willard", "123", "123")

    trust2, ok, _ = verify_sas(trust, "willard", "123", "123")
    assert ok
    assert trust2["agents"]["willard"]["tier"] == "VERIFIED"


# ---------- reciprocation auto-promotion ----------

def test_record_reciprocation_increments():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")
    trust, _, _ = verify_sas(trust, "willard", "x", "x")

    for _ in range(3):
        trust = record_reciprocation(trust, "willard")
    assert trust["agents"]["willard"]["successful_reciprocations"] == 3
    assert trust["agents"]["willard"]["tier"] == "VERIFIED"


def test_record_reciprocation_auto_promotes_at_threshold():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")
    trust, _, _ = verify_sas(trust, "willard", "x", "x")

    for _ in range(ATTESTATION_THRESHOLD):
        trust = record_reciprocation(trust, "willard")
    assert trust["agents"]["willard"]["tier"] == "ATTESTED"
    assert "auto_promoted_at" in trust["agents"]["willard"]


def test_record_reciprocation_no_promotion_from_untrusted():
    """UNTRUSTED → ATTESTED requires SAS verification first."""
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")

    for _ in range(ATTESTATION_THRESHOLD * 2):
        trust = record_reciprocation(trust, "willard")
    assert trust["agents"]["willard"]["tier"] == "UNTRUSTED"


# ---------- manual promotion to TRUSTED ----------

def test_promote_to_trusted_from_attested():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({"version": 1, "agents": {"paul": {"public_keys": []}}})
    # Already ATTESTED via legacy migration

    trust2, ok, reason = promote_to_trusted(trust, "paul")
    assert ok, reason
    assert trust2["agents"]["paul"]["tier"] == "TRUSTED"


def test_promote_to_trusted_blocked_from_verified():
    _, pub = generate_keypair()
    trust = upgrade_trust_to_v31({})
    trust = add_agent_card_pin(trust, "willard", pub, "willard:abc", "https://example.com")
    trust, _, _ = verify_sas(trust, "willard", "x", "x")
    # tier is now VERIFIED

    trust2, ok, reason = promote_to_trusted(trust, "willard")
    assert not ok
    assert "ATTESTED" in reason


# ---------- kind-acceptance gating ----------

def test_untrusted_accepts_only_discovery_kinds():
    ok, _ = accept_kind_for_tier(10000, "UNTRUSTED")  # agent_card
    assert ok
    ok, _ = accept_kind_for_tier(100, "UNTRUSTED")  # heartbeat
    assert ok
    ok, _ = accept_kind_for_tier(10001, "UNTRUSTED")  # trust_tier_announcement
    assert ok


def test_untrusted_rejects_decisions_and_claims():
    ok, _ = accept_kind_for_tier(1, "UNTRUSTED")  # decision
    assert not ok
    ok, _ = accept_kind_for_tier(1100, "UNTRUSTED")  # claim
    assert not ok
    ok, _ = accept_kind_for_tier(1200, "UNTRUSTED")  # ship
    assert not ok


def test_verified_rejects_only_claim():
    ok, _ = accept_kind_for_tier(1100, "VERIFIED")  # claim — must be ATTESTED
    assert not ok
    ok, _ = accept_kind_for_tier(1, "VERIFIED")  # decision OK
    assert ok
    ok, _ = accept_kind_for_tier(1200, "VERIFIED")  # ship OK
    assert ok
    ok, _ = accept_kind_for_tier(1400, "VERIFIED")  # incident OK
    assert ok


def test_attested_accepts_all_kinds():
    for kind in (100, 1, 1100, 1200, 1300, 1400, 1500, 1600, 10000):
        ok, _ = accept_kind_for_tier(kind, "ATTESTED")
        assert ok, f"ATTESTED should accept kind={kind}"


def test_trusted_accepts_all_kinds():
    for kind in (100, 1, 1100, 1200):
        ok, _ = accept_kind_for_tier(kind, "TRUSTED")
        assert ok


def test_unknown_tier_rejects():
    ok, reason = accept_kind_for_tier(1, "WHATEVER")
    assert not ok
    assert "unknown tier" in reason


# ---------- get_tier ----------

def test_get_tier_unknown_agent_defaults_untrusted():
    trust = {"agents": {}}
    assert get_tier(trust, "stranger") == "UNTRUSTED"


def test_get_tier_known_agent():
    trust = {"agents": {"paul": {"tier": "TRUSTED"}}}
    assert get_tier(trust, "paul") == "TRUSTED"


# ---------- file IO ----------

def test_load_save_trust_roundtrip(tmp_path):
    p = tmp_path / "trust.json"
    trust = upgrade_trust_to_v31({"version": 1, "agents": {"paul": {"public_keys": []}}})
    save_trust(trust, p)
    loaded = load_trust(p)
    assert loaded == trust


def test_load_trust_missing_file_returns_empty_v31(tmp_path):
    p = tmp_path / "nonexistent.json"
    trust = load_trust(p)
    assert trust["schema_version"] == "v3.1"
    assert trust.get("agents", {}) == {}


# ---------- tier ordering ----------

def test_tier_ordering():
    assert TIER_ORDER["UNTRUSTED"] < TIER_ORDER["VERIFIED"]
    assert TIER_ORDER["VERIFIED"] < TIER_ORDER["ATTESTED"]
    assert TIER_ORDER["ATTESTED"] < TIER_ORDER["TRUSTED"]
    assert len(TRUST_TIERS) == 4
