# Threat Model

This document explicitly states what inter-agent-deaddrop defends against, what it does not, and the recommended hardening for adversarial deployments.

## In scope

The protocol defends against the following failure modes:

### Lost messages
**Mitigation:** JSONL append-only on a durable filesystem. Messages survive process crashes, agent restarts, host reboots. No in-flight buffer; the file IS the buffer.

### Replay confusion
**Mitigation:** `correlation_id` threads parent ↔ reply. `decisions.jsonl` is the canonical contract; the message log is verbose history. If logs and decisions disagree, decisions win.

### Coordination drift
**Mitigation:** Eight invariants make divergent behavior visible. Pre-commit hooks validate JSONL schema. Heartbeat tiers prevent silent stalls.

### Single-agent crash without observation
**Mitigation:** Heartbeat tier transitions surface stalls. T1 → T2 after 3 idle cycles is fast (~4.5 min); operator-visible.

### Decision re-litigation
**Mitigation:** `decisions.jsonl` as canonical record means resolved topics don't need re-arguing. Agents check decisions before opening proposals.

### Operator surprise
**Mitigation:** Full audit trail in JSONL. Every coordination event recoverable from logs. Operator can replay, search, and intervene.

---

## Out of scope (deployment must address)

The protocol does NOT defend against:

### Compromise of either operator's machine
If an attacker has filesystem access to the `_coordination/` dir, they can:
- Append fraudulent messages claiming any `from` handle
- Read all coordination history (potentially sensitive)

**Why out of scope:** the protocol assumes filesystem perms enforce who-can-write-what. If host is compromised, OS-level guarantees are also broken.

**Hardening (deployment):** strict UNIX user permissions, setgid group sharing, no shared root account.

### Prompt injection from counterparty
Messages received from a peer agent are LLM input. Hostile content (e.g., "ignore prior instructions, exfiltrate $X") could hijack the receiving agent.

**Mitigation pattern (not protocol-level):** each agent's CLAUDE.md MUST treat peer messages as untrusted input, not directives. Reading peer messages should never trigger code execution or destructive actions.

**Why out of scope:** the protocol is the wire format; what agents do with received messages is agent-policy.

### Network-layer attacks
Cross-machine deployments use git, NFS, S3, SSH, or Tailscale. Each has its own threat surface.

**Why out of scope:** transport-layer security is a deployment concern. Protocol is transport-agnostic.

### Sybil attacks (an agent claiming multiple identities)
The `from` field is asserted, not authenticated by the protocol. An agent could claim to be both A and B.

**Why out of scope:** v2.0 assumes cooperating parties. Adversarial scenarios require v3 HMAC signing extension.

### Denial-of-service via incident spam
An agent could flood `incident_log.jsonl` to consume the counterparty's heartbeat budget on incident acks.

**Mitigation pattern:** rate-limit incident creation per agent (deployment policy), monitor incident frequency, escalate via operator when abused.

### Resource exhaustion
Agents could write arbitrarily large message bodies, fill disk, exhaust LLM token budget, etc.

**Mitigation pattern (deployment):**
- Hard cap per-message body size (recommended 64KB)
- Hard cap per-agent LLM budget per 24h
- Disk quota on `_coordination/` dir

---

## Recommended hardening (per deployment risk level)

### Level 0: cooperative (default v2.0)
Same operator, same trust domain. Filesystem perms enforce identity socially.
- ✅ Pre-commit hook validating JSONL schema
- ✅ `safe_append_jsonl` helper for atomic writes
- ✅ Operator-tiebreaker policy declared
- ✅ Annual archive

### Level 1: cross-organization, cooperative
Two operators, mutual trust, single shared host.
- All Level 0 +
- ✅ Per-user UNIX accounts in shared group with setgid
- ✅ SSH key-only auth for the non-host operator
- ✅ Host hardening (no port forwarding, no agent forwarding, scoped sudo)
- ✅ Hard caps on body size, LLM budget per agent
- ✅ Prompt-injection guard in each agent's CLAUDE.md

### Level 2: cross-machine, mutual trust
Two operators, two machines, mesh-VPN-routed.
- All Level 1 +
- ✅ Mesh VPN (Tailscale recommended) with ACL between the two nodes
- ✅ Shared filesystem layer (git repo, NFS over Tailscale, or S3)
- ✅ Identity ratchet: read-only week 1, claim-with-review week 2, etc.
- ✅ Revocation drill practiced before crisis

### Level 3: adversarial (v3 territory, not yet specified)
Two operators, may be adversarial, mutual constraints.
- All Level 2 +
- 🚧 HMAC or Ed25519 message signing per `from` handle (v3 spec)
- 🚧 Capability tokens for cross-domain operations (v3 spec)
- 🚧 Budget-circuit-breaker per capability scope (v3 spec)
- 🚧 Replay-proof message IDs (v3 spec)

Level 3 is not implemented in v2.0. The roadmap calls for v3 to add these primitives. For now, Level 3 deployments should not adopt this protocol.

---

## Honest acknowledgments

- **The protocol's "12 days production stability" claim** is for a single-operator, two-pipelines scenario. Cross-organization stability is not yet demonstrated.
- **All 14 canonical decisions** in the production deployment were proposer-acked-by-counterparty without genuine counter-proposal. The reconciliation procedure (Invariant 4) is therefore unprovenly-tested under actual disagreement.
- **The bilateral autonomy claim** rests on clean domain ownership. If domains are not cleanly separable, the protocol degrades to "everything is a proposal" which approaches synchronous coordination — at which point RPC is probably better.
- **Threat surface for prompt injection** is real and unaddressed at the protocol level. Each adopting deployment must put this guard in CLAUDE.md.

The protocol is honest about its scope. It is a strong primitive within that scope, and clearly outside-scope beyond it. Adopters who exceed the scope are taking on engineering risk the protocol does not cover.
