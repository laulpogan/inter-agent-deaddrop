# Signed Messages — v3 Extension

**Status:** v3 spec, reference implementation in `v3/`. Backwards-compatible add-on to v2.0.

The v2.0 protocol identifies senders by an unsigned `from` field. This is fine when both parties trust each other and trust the underlying filesystem/git/host enforcing identity. **For adversarial scenarios, v3 adds Ed25519 message signing** so each message cryptographically proves its sender.

This document specifies the extension. Adopt it when:
- One party may not trust the other
- The wire goes through an untrusted third party (e.g., a self-hosted git server you don't fully control)
- Audit must withstand "agent X claims agent Y said this" disputes
- You want to layer non-repudiation on top of inter-agent-deaddrop

If both parties trust each other AND trust the wire, **v2.0 unsigned messages are fine** — don't pay the v3 complexity cost.

---

## Threat surface v3 closes

v2.0 unsigned message can be forged by:
- A third agent with write access to the dead-drop dir (single-host)
- A user with shell access to either machine (cross-host)
- A git committer with the right `user.name` config (git-as-wire, no signing)
- A bug in the heartbeat daemon that mis-attributes messages

v3 signed messages: forgery requires the sender's private key. Compromise of one agent's machine still compromises that agent, but cannot forge messages from the OTHER agent. **Asymmetric trust:** each agent trusts only its own private key.

---

## Spec

### Message schema additions

v2.0 message:

```json
{
  "timestamp": "...",
  "from": "...",
  "type": "...",
  "subject": "...",
  "body": "...",
  "refs": [...],
  "priority": "...",
  "correlation_id": "...",
  "ack_required": false
}
```

v3 message adds two fields:

```json
{
  ...v2 fields...,
  "public_key_id": "<agent>:<key-fingerprint>",
  "signature": "<base64-encoded Ed25519 signature>"
}
```

Both fields are REQUIRED for v3 messages. Verification: re-canonicalize the v2-shape fields (excluding `public_key_id` and `signature`), look up the public key by `public_key_id`, verify signature.

### Canonical serialization

To compute or verify a signature, serialize the v2-shape fields (everything except `public_key_id` and `signature`) using:

- JSON, with sorted keys (`sort_keys=True`)
- Compact separators (`, ` and `: ` collapsed to `,` and `:`)
- UTF-8 encoding
- No trailing newline

Reference Python:

```python
import json
def canonical(msg: dict) -> bytes:
    body = {k: v for k, v in msg.items() if k not in ("public_key_id", "signature")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

This MUST be byte-identical between sender and verifier. Any whitespace, key-ordering, or encoding difference invalidates the signature.

### Trust list

Each agent maintains `_coordination/trust.json` — the canonical list of trusted public keys for the project:

```json
{
  "version": 1,
  "agents": {
    "agent_a": {
      "public_keys": [
        {
          "key_id": "agent_a:abc12345",
          "key": "<base64-encoded Ed25519 public key, 32 bytes>",
          "added_at": "2026-05-05T15:00:00Z",
          "active": true
        }
      ]
    },
    "agent_b": {
      "public_keys": [
        {
          "key_id": "agent_b:def67890",
          "key": "...",
          "added_at": "2026-05-05T15:00:00Z",
          "active": true
        }
      ]
    }
  }
}
```

`trust.json` is itself v3-signed: every entry has a signature by the operator (or by both agents bilaterally) that authorizes adding/removing keys. Adding a key requires bilateral acks (both parties post `proposal: add_key` → `ack`).

`key_id` format: `<agent>:<first 8 hex chars of SHA256(public_key_raw)>`. Stable per keypair.

### Signing flow

Sender:

1. Build v2-shape message (all fields EXCEPT `public_key_id` and `signature`)
2. Compute canonical bytes
3. Sign with Ed25519 private key
4. Set `public_key_id = "<agent>:<fingerprint>"` and `signature = base64(sig)`
5. Append complete msg to outbound JSONL

Verifier:

1. Parse JSON line
2. Extract `public_key_id` — look up in trust.json; if absent or `active: false`, reject (`incident: untrusted_key`)
3. Extract `signature`
4. Compute canonical bytes from remaining fields
5. Verify signature; if invalid, reject (`incident: invalid_signature`)
6. Cross-check `from` field against the agent the key belongs to; mismatch → reject

### Key rotation

To rotate keys:

1. New keypair generated locally
2. Holder posts `proposal: add_key` containing the new public key + key_id, signed with the OLD key
3. Counterparty acks; both update local `trust.json` to add the new key with `active: true`
4. Holder begins signing with new key
5. After grace period (default 24h), holder posts `proposal: deactivate_key` for old key, counterparty acks
6. Both update `trust.json`: old key `active: false`, retain for verifying historical messages

### Compromise response

If your private key is compromised:

1. **Immediately** post `incident: key_compromised` signed with a new-but-unverified key
2. Counterparty halts message processing for all messages signed with compromised key (entering safe-mode)
3. Operator out-of-band proves identity (e.g., voice call, in-person)
4. Operator manually updates `trust.json`: compromised key `active: false`, new key added with `active: true`
5. Both parties replay history with new trust to determine extent of forged messages
6. Each forged message acked by both as `correction` with note

If counterparty's key is compromised: same procedure, mirrored.

---

## Reference implementation

See `v3/signing.py` (helpers), `v3/verify.py` (pre-commit hook), `v3/keygen.py` (keypair generation), and `v3/test_roundtrip.py` (tests).

```python
# Sign a message
from v3.signing import sign_message
msg = {"timestamp": "...", "from": "agent_a", ...}
signed = sign_message(msg, private_key, key_id="agent_a:abc12345")
# signed = msg + {"public_key_id": "...", "signature": "..."}

# Verify a message
from v3.signing import verify_message
ok, reason = verify_message(signed, trust_dict)
# ok=True if signature valid + key_id is active in trust list
```

Pre-commit hook usage:

```bash
cp v3/verify.py .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook validates EVERY new line in `_coordination/*.jsonl` files in the staged commit. Any signature failure blocks the commit (with `ALLOW_HOTPATH=1` override for emergencies).

---

## Compatibility with v2.0

A v3 deployment can accept v2.0-shape messages from v2.0-only peers IF the trust model permits unsigned messages from that peer. Configuration in `_coordination/config.json`:

```json
{
  "protocol_version": "v2.0",
  "v3_signing": {
    "enforce_signed": true,
    "allow_unsigned_from": []
  }
}
```

`enforce_signed: true` rejects all unsigned messages — strict v3.
`allow_unsigned_from: ["agent_a"]` permits agent_a to send v2-shape — degraded trust.

Recommend: don't mix. Either both agents are v3, or neither. Mixed-mode deployment defeats the security goal because the v2 side can be forged.

---

## What v3 does NOT solve

- **Replay attacks.** A v3 message is non-repudiable but can still be replayed. Mitigate with monotonic timestamps + recipient-side `seen_msg_ids` cache (idempotency by `correlation_id`).
- **Key compromise after the fact.** A leaked key invalidates all FUTURE messages signed with it. Old messages remain valid (the signature was correct at signing time). The audit log shows the trust transition.
- **Operator-level trust.** If you don't trust the operator who maintains `trust.json`, v3 doesn't help — the operator can add fake keys.
- **Side-channel attacks.** Timing, power analysis, etc. against the signing operation. Out of scope.
- **Quantum break.** Ed25519 is not quantum-resistant. v4 territory if/when post-quantum sigs are needed.

---

## Adoption checklist

- [ ] Both parties generate Ed25519 keypairs with `v3/keygen.py`
- [ ] Bilateral key exchange: each posts public key as `proposal: add_key` (initial bootstrap is out-of-band)
- [ ] Bilateral acks update `trust.json` on both sides
- [ ] Pre-commit hook installed: `cp v3/verify.py .git/hooks/pre-commit`
- [ ] Each agent's `safe_append_jsonl` calls replaced with `signed_append_jsonl`
- [ ] `_coordination/config.json` declares `enforce_signed: true`
- [ ] Test: send a message; verify counterparty accepts. Try unsigned; verify counterparty rejects with `incident: invalid_signature`.
- [ ] Document key rotation runbook (24h grace period, compromise response)
- [ ] Backup keypairs separately from the agent host (so a host compromise doesn't compromise the next session's keypair)
