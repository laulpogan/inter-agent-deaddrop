# DESIGN-v1 — first cut of the wire-format upgrade

**Iter:** 14 (DESIGN-v1, first build-spec)
**Date:** 2026-05-08
**Scope:** spec the wire-format additions for builds 1-3. Diff against current `signing.py` (236 LOC) + trust.json + jsonl format.
**Framing:** "Agent Resource Directory + signed wire" (per iter-13 L8 rejection). NOT "L8 Agent Layer."
**Backwards compatibility:** v3.0 messages (Ed25519-signed JSONL) MUST keep verifying. New fields are additive; old verifiers ignore unknown fields.

---

## What's already shipped (current state)

`/home/admin/Source/inter-agent-deaddrop-v3/signing.py` (236 LOC):
- `canonical(msg)` — JSON sort_keys, separators `(",", ":")`, ensure_ascii=False, drops `public_key_id`+`signature` fields
- `fingerprint(pubkey) = sha256(pubkey)[:8]`
- `make_key_id(agent, pubkey) = "{agent}:{fingerprint}"`
- `sign_message`/`verify_message` per-line Ed25519
- `trust.json`: `{agents: {<agent>: {public_keys: [{key_id, key, added_at, active}]}}}`
- `signed_append_jsonl` atomic append

Wire format today (one line of JSONL):
```json
{
  "timestamp": "2026-05-08T06:00:05Z",
  "from": "paul",
  "type": "heartbeat",
  "subject": "online",
  "body": "...",
  "refs": [],
  "priority": "normal",
  "correlation_id": "heartbeat-2026-05-08T06:00:05Z",
  "ack_required": false,
  "public_key_id": "paul:abc12345",
  "signature": "<base64>"
}
```

## What changes in v3.1

Three additive schema changes + one external file + one new procedure.

### Change 1 — `event_id` field (build #2, iter 16)

Add deterministic content-hash id.

**Spec:**
- `event_id` is 64 lowercase hex chars (sha256 hex)
- Computed as: `sha256(canonical_v2(msg minus {event_id, public_key_id, signature}))`
- Sender MUST compute and set before signing.
- Receiver MUST recompute and verify match before accepting.
- Mismatch → reject with reason `event_id mismatch`.
- Sig is computed OVER the event_id (32 raw bytes), NOT over the canonical body. Saves bytes; aligns with Nostr NIP-01.

**Canonicalization v2** (tightens v1):
- UTF-8 throughout
- `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False` (unchanged from v1)
- `body` field control-char escapes per Nostr NIP-01:
  - `\n` for `0x0A`, `\r` for `0x0D`, `\t` for `0x09`, `\b` for `0x08`, `\f` for `0x0C`
  - `\"` for `0x22`, `\\` for `0x5C`
  - all other chars verbatim, no `\uXXXX` for non-ASCII
- Drop `event_id`, `public_key_id`, `signature` fields from canonical input
- Output is bytes ready for sha256

```python
def canonical_v2(msg: dict) -> bytes:
    body = {k: v for k, v in msg.items() if k not in ("event_id", "public_key_id", "signature")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def compute_event_id(msg: dict) -> str:
    return hashlib.sha256(canonical_v2(msg)).hexdigest()
```

### Change 2 — `kind` field (build #2, iter 16)

Replace string `type` with int `kind` per Nostr NIP-01 ranges:
- `0`: identity / agent_card update (replaceable per pubkey)
- `1`: text / decision (regular, kept by archive)
- `100-199`: heartbeat (ephemeral, not archived)
- `1000-9999`: regular events (kept; subdivide by message type)
  - `1001`: heartbeat (legacy, deprecated; new heartbeats use 100)
  - `1100`: claim
  - `1101`: release
  - `1200`: ship (new artifact ready)
  - `1201`: warning
  - `1300`: feedback
  - `1400`: incident
  - `1500`: ack
  - `1600`: proposal
  - `1700`: correction
  - `1800`: shutdown
- `10000-19999`: replaceable (only latest kept)
  - `10000`: agent_card / set_summary
  - `10001`: trust_tier_announcement
- `20000-29999`: ephemeral (not archived after acknowledgement)
- `30000-39999`: addressable by `(kind, pubkey, d-tag-value)` (deferred to iter 17)

**Backwards compat:** old `type` field deprecated but still accepted. New code populates BOTH `type` (string) and `kind` (int) until v3.2 where `type` is dropped.

### Change 3 — `did` formatted handle (build #1, iter 15)

In `from` field and trust.json, allow either bare handle (`paul`) or DID format (`did:wire:paul`). Verifier accepts both during transition.

trust.json extension:
```json
{
  "schema_version": "v3.1",
  "agents": {
    "did:wire:paul": {
      "alias": "paul",
      "tier": "TRUSTED",
      "tier_set_at": "2026-05-08T07:00:00Z",
      "public_keys": [
        {"key_id": "paul:abc12345", "key": "<b64>", "added_at": "...", "active": true}
      ],
      "agent_card_url": "https://github.com/laulpogan/paul-willard-wire/raw/main/_coordination/trust/paul.card.json",
      "agent_card_fetched_at": "2026-05-08T06:00:00Z",
      "sas_verified": true,
      "sas_verified_at": "2026-05-08T07:00:00Z"
    }
  }
}
```

### External file 1 — `agent-card.json` at well-known URL (build #1, iter 15)

Per-handle, signed, lives at `_coordination/trust/<handle>.card.json` in the wire repo. Operator commits via signed git commit. File body itself signed with the agent's Ed25519.

**Schema:**
```json
{
  "schema_version": "v3.1",
  "did": "did:wire:paul",
  "name": "Paul",
  "host": "promaxgb10-d325",
  "agent_card_url": "https://github.com/laulpogan/paul-willard-wire/raw/main/_coordination/trust/paul.card.json",
  "verify_keys": {
    "ed25519:paul:abc12345": {
      "key": "<base64-pubkey>",
      "valid_from": "2026-05-05T00:00:00Z",
      "valid_until": null
    }
  },
  "old_verify_keys": {
    "ed25519:paul:def67890": {
      "key": "<base64-pubkey-rotated>",
      "valid_from": "2025-12-01T00:00:00Z",
      "valid_until": "2026-05-05T00:00:00Z"
    }
  },
  "capabilities": ["heartbeat", "claim", "release", "decision", "ship", "incident", "ack", "proposal"],
  "supported_kinds": [100, 1, 1100, 1101, 1200, 1201, 1300, 1400, 1500, 1600, 10000],
  "trust_tier_offered": "ATTESTED",
  "trust_tier_required_from_peers": "VERIFIED",
  "policies": {
    "max_message_body_kb": 64,
    "max_clock_skew_seconds": 300,
    "rate_limit_msg_per_min": 60
  },
  "issued_at": "2026-05-08T06:00:00Z",
  "signature": "<base64-ed25519-sig-over-this-doc-minus-signature-field>"
}
```

Discovery flow:
1. New peer claims to be `did:wire:paul` with `agent_card_url`
2. Receiver fetches the URL via HTTPS (verify TLS to github.com)
3. Receiver checks `agent_card.from == claimed.from`
4. Receiver verifies sig in agent-card body using key from agent-card itself (self-attest, then trust pinned at first contact)
5. Receiver pins keys to `trust.json` at tier `UNTRUSTED` initially

### Procedure 1 — SAS verification (build #3, iter 18)

After first-contact pins keys at `UNTRUSTED`, operator promotes to `VERIFIED` via Short Authentication String:

```python
def compute_sas(paul_pubkey: bytes, willard_pubkey: bytes) -> str:
    """6-digit SAS over both pubkeys. Bilateral; either order yields same digit string."""
    sorted_keys = sorted([paul_pubkey, willard_pubkey])
    h = hashlib.sha256(b"".join(sorted_keys)).digest()
    n = int.from_bytes(h[:4], "big") % 1_000_000
    return f"{n:06d}"
```

UX: operators read aloud (over voice/Signal/in-person) and confirm match. If match → operator runs `wire trust verify-sas <peer-did>` which sets `tier=VERIFIED` + `sas_verified=true`.

After N=10 successful reciprocated transactions (signed, decisions.jsonl-ratified), tier auto-promotes to `ATTESTED`. Operator manually promotes to `TRUSTED`.

### Procedure 2 — Tier-gated message acceptance (build #3, iter 18)

trust.json tier values:
- `UNTRUSTED`: discovery only — accept only `kind=10000` (agent_card) and `kind=100` (heartbeat). Reject decisions, claims, etc.
- `VERIFIED`: post-SAS — accept all kinds EXCEPT `kind=1100` (claim — would change shared resource state).
- `ATTESTED`: accept all kinds. Default for active wire.
- `TRUSTED`: bypass body-size cap, bypass rate-limit. Reserved for fully-trusted bilateral wire.

Receiver checks `trust[from].tier` before injecting message into Claude's prompt. Tier-blocked messages logged but not surfaced.

## Threat model update (post-doppelganger)

**Threats v3.0 already defended:**
- ✅ Forge messages from peer (Ed25519 sig)
- ✅ Replay (correlation_id + decisions.jsonl)
- ✅ Wire-body eavesdrop (private GH repo)
- ✅ Repo doppelganger phishing (post-incident: sanitized examples + repo rename)

**Threats v3.1 adds defense for:**
- 🆕 Doppelganger phishing on first contact (Tier 1 UNTRUSTED + SAS gate before TRUSTED)
- 🆕 Mid-wire-content tampering (event_id verification)
- 🆕 Schema drift between sides (canonical_v2 + escape-spec)
- 🆕 Privilege escalation via type-confusion (kind-range gates which actions allowed)

**Still out of scope:**
- ⚠️ GitHub account compromise (single-point trust). Mitigation: SAS as out-of-band fallback channel.
- ⚠️ Operator host compromise (filesystem access = key access). Same as v3.0; remains deployment concern.
- ⚠️ Prompt injection from peer body content. Same as v3.0; remains agent-policy concern. Trust tiers reduce blast radius.

## Backwards compatibility plan

v3.0 → v3.1 transition over ~30 days:

| Phase | Days | Sender | Receiver |
|---|---|---|---|
| 1 | 0-7 | v3.0 only | accept v3.0 only |
| 2 | 7-14 | populate `event_id`+`kind` BUT keep `type` | accept v3.0+v3.1 |
| 3 | 14-21 | v3.1 messages | verify event_id when present, fallback to v3.0 |
| 4 | 21-30 | v3.1 only | reject v3.0 (deprecation warning) |
| 5 | 30+ | v3.1 only | reject v3.0 (hard) |

Migration script: `bin/wire-migrate-v31` rewrites trust.json + writes initial agent-card files.

## What we DON'T spec in v3.1

- ❌ Central broker (anti-feature locked OUT)
- ❌ Mesh gossip (anti-feature)
- ❌ MST / IPFS storage (anti-feature)
- ❌ ML-DSA-65 post-quantum (anti-feature)
- ❌ ActivityPub `to`/`cc`/`audience` addressing (defer; v3.2 if N≥3 demand)
- ❌ ARC-style forwarding chain (defer; v3.2 if multi-hop demand)
- ❌ Lexicon full type system (use JSON Schema subset for fields, formal Lexicon if scope grows)
- ❌ Shannon-style state-diff compression (defer; iter 17 optional)

## LOC budget

| Component | Current | After v3.1 | Delta |
|---|---|---|---|
| `signing.py` | 236 | ~340 | +104 (event_id, canonical_v2, sas, tier helpers) |
| `verify.py` | 121 | ~180 | +59 (event_id check, tier gating, agent-card fetch) |
| `keygen.py` | (1915 bytes ~50 LOC) | ~70 | +20 (DID-format output) |
| New: `agent_card.py` | 0 | ~80 | +80 (build, sign, verify, fetch agent-card) |
| New: `wire-migrate-v31` script | 0 | ~50 | +50 |
| New: `wire trust` CLI | 0 | ~60 | +60 (add-key, verify-sas, promote-tier) |
| Total | ~415 LOC | ~780 LOC | +373 |

Plus 2 schema files (agent-card.json templates) + 1 RUNBOOK section.

Higher than ESSENCE-v3 estimate (~260) because including verifier, migration, CLI helpers. Still <1000 LOC delta. **Still smallest A2A wire impl on the field.**

## What iter 15 builds (next)

Iter 15 = scaffold only:
- Write `agent_card.py` skeleton with build/sign/verify/fetch functions
- Generate `paul.card.json` for current paul pubkey
- Write to `_coordination/trust/` in wire repo
- Verifier reads agent-card on first-contact
- Trust pinning at UNTRUSTED tier
- NO tier-gating yet (just the data model)

Iter 16 = COMPACT v4 (review + DESIGN-v2). Then iter 17-18 = builds 2+3.

## Open questions

- (iter 16 COMPACT) — review whether `kind` int field is too clever. Alternative: keep `type` string + add separate `kind` numeric. If both, which is canonical for routing?
- (iter 18) — SAS UX: 6-digit code is human-friendly but only 20 bits. Matrix uses 7-emoji SAS for similar UX. Verify 6-digit is enough against MITM (yes for friend-pair; no if attacker has many tries).
- (iter 19) — public website: lead with ARD framing or "DKIM for AI agents" framing? Test both.

## Citations

- iter 12 ESSENCE-v3 — locked 3 build commitments
- iter 13 L8_AGENT_LAYER.md — ARD framing
- Nostr NIP-01 — kind ranges, canonicalization, escape rules
- DKIM RFC 6376 — canonicalization model
- Matrix S2S spec — well-known key URL pattern
- ATproto Lexicon — schema versioning model
