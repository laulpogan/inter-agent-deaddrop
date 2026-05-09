# inter-agent-deaddrop v3.1

**v3.1 build artifacts** from a 20-iter A2A protocol research spike. See
[`../docs/RECOMMENDATIONS.md`](../docs/RECOMMENDATIONS.md) for the full report and
[`../docs/DESIGN-v1.md`](../docs/DESIGN-v1.md) for the spec.

## What v3.1 adds over v3.0

Three small additions, ~900 LOC delta:

1. **`agent_card.py`** — signed JSON identity document at well-known git URL.
   Schema-compatible with Google A2A AgentCard, extended with DID-formatted
   handles + tiered trust offered.
2. **`signing.py` extended** — content-addressable `event_id` (sha256 of
   canonical body), `kind` field with Nostr-style ranges (ephemeral/regular/
   replaceable/addressable), sign-over-event-id (32 raw bytes).
3. **`wire_trust.py`** — 4-tier trust model
   (UNTRUSTED → VERIFIED → ATTESTED → TRUSTED), 6-digit SAS verification
   over sorted (did, pubkey) pairs, kind-acceptance gating.

All v3.0 messages still verify against v3.1 verifier (additive schema).
v3.1 introduces new `sign_message_v31` / `verify_message_v31` for the
content-addressable path.

## Run tests

```bash
cd v3.1
pip install pynacl  # or: pip install cryptography
python -m pytest tests/ -v
```

52 tests, ~30ms total.

## Why this exists

Cross-organization agent-to-agent communication is widely unsolved.
~15 active specs and projects converge on the same architecture floor:
per-agent keypair, signed messages, append-only audit. Battle-tested
ancestors (DKIM, Matrix, SSB, Nostr, Hypercore, ATproto) are mostly
ignored.

paul-willard-wire (this repo) is the smallest cryptographic friend-pair
A2A wire studied. Vendor-neutral, ~900 LOC.

See https://a2a.laulpogan.com for the public landing page.
See [`../docs/RECOMMENDATIONS.md`](../docs/RECOMMENDATIONS.md) for the full hypothesis-by-hypothesis verdict.

## What this is NOT

- A replacement for Google A2A 1.0. We adopt their AgentCard schema.
- A replacement for Microsoft Agent Governance Toolkit. Different lane.
- A drop-in for enterprises with 1000+ agents. Bilateral simplicity is the design choice.

## Files

```
v3.1/
├── README.md             — this file
├── agent_card.py         — agent-card spec + sign/verify/sas
├── signing.py            — Ed25519 + canonical + event_id + kind ranges
├── wire_trust.py         — tiered trust + SAS + kind-acceptance gating
├── example/
│   └── agent-a.card.json — sample agent-card (throwaway key, not for production)
└── tests/
    ├── test_agent_card.py
    ├── test_v31_sign.py
    └── test_wire_trust.py
```

## Threat model

See [`../THREAT_MODEL.md`](../THREAT_MODEL.md) for the v3.0 baseline. v3.1 closes:

- Doppelganger-on-first-contact (UNTRUSTED tier + SAS verification gate)
- Mid-wire body tampering (event_id verification)
- Schema drift between sides (canonical strict-escapes spec)
- Privilege escalation via type-confusion (kind-range gates which actions allowed)

A real doppelganger phishing attempt against this protocol on 2026-05-07
prompted the iter-18 build commitments. See [`../SECURITY-NOTES.md`](../SECURITY-NOTES.md).

## Status

Production-deployed between two operators since April 2026. 52/52 tests pass.
~50,000 messages exchanged on v3.0; v3.1 schema additive, no breaking changes.

## License

MIT (matches the parent repo).
