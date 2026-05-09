"""
Tests for agent_card.py — DESIGN-v1 build #1.

Run: cd /home/admin/Source/inter-agent-deaddrop-v3 && python -m pytest tests/test_agent_card.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_card import (
    CARD_SCHEMA_VERSION,
    build_agent_card,
    compute_sas,
    did_for,
    load_card_file,
    sign_agent_card,
    verify_agent_card,
    write_card_file,
)
from signing import generate_keypair


def test_did_for_bare():
    assert did_for("paul") == "did:wire:paul"


def test_did_for_already_did():
    assert did_for("did:wire:paul") == "did:wire:paul"


def test_build_card_defaults():
    priv, pub = generate_keypair()
    card = build_agent_card("paul", pub)
    assert card["schema_version"] == CARD_SCHEMA_VERSION
    assert card["did"] == "did:wire:paul"
    assert card["name"] == "Paul"
    assert "ed25519:paul:" in next(iter(card["verify_keys"].keys()))
    assert card["trust_tier_offered"] == "ATTESTED"
    assert card["policies"]["max_message_body_kb"] == 64
    assert "signature" not in card  # unsigned at this point


def test_sign_and_verify_card():
    priv, pub = generate_keypair()
    card = build_agent_card("paul", pub)
    signed = sign_agent_card(card, priv)
    assert "signature" in signed
    ok, reason = verify_agent_card(signed)
    assert ok, f"verify failed: {reason}"


def test_verify_fails_on_tampered_card():
    priv, pub = generate_keypair()
    card = build_agent_card("paul", pub)
    signed = sign_agent_card(card, priv)
    signed["name"] = "EvilPaul"  # tamper
    ok, reason = verify_agent_card(signed)
    assert not ok
    assert "matched" in reason or "verif" in reason.lower()


def test_verify_fails_on_wrong_key():
    priv1, pub1 = generate_keypair()
    priv2, pub2 = generate_keypair()
    card = build_agent_card("paul", pub1)
    # Sign with priv2 instead of priv1 — sig won't verify against pub1 in card
    signed = sign_agent_card(card, priv2)
    ok, _ = verify_agent_card(signed)
    assert not ok


def test_sas_bilateral_symmetry():
    """SAS over (a, b) must equal SAS over (b, a)."""
    _, pub_a = generate_keypair()
    _, pub_b = generate_keypair()
    sas_ab = compute_sas(pub_a, pub_b)
    sas_ba = compute_sas(pub_b, pub_a)
    assert sas_ab == sas_ba
    assert len(sas_ab) == 6
    assert sas_ab.isdigit()


def test_sas_different_for_different_pairs():
    _, a = generate_keypair()
    _, b = generate_keypair()
    _, c = generate_keypair()
    assert compute_sas(a, b) != compute_sas(a, c)
    assert compute_sas(a, b) != compute_sas(b, c)


def test_write_and_load_card_roundtrip(tmp_path):
    priv, pub = generate_keypair()
    card = build_agent_card("paul", pub, host="test-host", agent_card_url="https://example.com/paul.card.json")
    signed = sign_agent_card(card, priv)
    p = tmp_path / "paul.card.json"
    write_card_file(signed, p)
    loaded = load_card_file(p)
    assert loaded == signed
    ok, reason = verify_agent_card(loaded)
    assert ok, reason
