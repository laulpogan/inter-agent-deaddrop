# Changelog

## v3.0 — 2026-05-05 (signed messages)

**Ed25519 signed messages.** Cryptographic identity for adversarial scenarios.

### Added
- `v3/SIGNING.md`: full spec
- `v3/signing.py`: sign/verify helpers (PyNaCl or `cryptography` backend)
- `v3/keygen.py`: CLI to generate Ed25519 keypair per agent
- `v3/verify.py`: pre-commit hook blocking unsigned/invalid messages
- `v3/test_signing.py`: 8 round-trip tests
- `v3/README.md`: quick-start
- `examples/idempotency.py`: replay-detection cache (closes the v3 replay-attack gap)
- `v4/N-AGENT.md`: spec draft for n>2 generalization (not implemented)

### Validated
- Live cross-machine signed exchange between Mac (paul-mac) and Linux (paul-spark)
- Forgery rejection: tampered messages fail verification
- Unknown / deactivated keys correctly rejected
- Backward compat: v2.0 unsigned messages on the same JSONL correctly REJECTED in v3-strict mode

### Notes
- v3 closes sender-forgery + tamper-detection. Replay-attack closure depends on idempotency cache.
- Key rotation procedure documented (bilateral proposal + ack, 24h grace period)
- Compromise response procedure documented (out-of-band identity proof)

## v2.1 — 2026-05-05

**git-as-wire transport.** Cross-machine, cross-organization deployments without shared host.

### Added
- `examples/git-as-wire/` — reference implementation for git-backed transport
  - `README.md`: deployment recipe + threat model + comparison
  - `wire-daemon.py`: sync daemon (file-watch + heartbeat poll + push/fetch with retry)
  - `wire-daemon.service`: systemd user unit
  - `test/test-roundtrip.sh`: local two-clone integration test (passes)
- `examples/spark-tunnel.sh`: SSH tunnel helper for single-shared-host deployments
- `examples/spark-mcp-config.json`: project-level `.mcp.json` snippet for Claude Code wire-up

### Changed
- `TRANSPORTS.md`: git-as-wire marked as documented + locally validated
- `README.md`: roadmap updated to reflect shipped Spark deployment + git-as-wire transport

### Notes
- Cross-machine E2E validated 2026-05-05 between Mac (paul-mac) and Linux (paul-spark) over a private GitHub repo. Full round-trip (heartbeat + ack) completed in ~30s with daemons running in `--once` mode on each side. Wire repo log shows clean commit ordering.
- True cross-organization (independent operator on the other side) stress test still pending
- HMAC-signing extension still planned for v3 (adversarial scenarios)

## v2.0 — 2026-04-24

**Major redesign.** Bilateral autonomy + heartbeat tiers + 8 invariants.

### Added
- 8 non-negotiable invariants (append-only, correlation_id, decision rights by domain, etc.)
- Heartbeat tiers (T0_HEADS_DOWN, T1_active, T2_idle, T3_long_idle) with explicit transitions
- `decisions.jsonl` as canonical record for bilateral-acked contracts
- `correction` message type for fixing prior messages without rewriting
- 1-heartbeat ack SLA for incidents; 2-heartbeat ack SLA for proposals
- Annual archive convention (`_coordination/archive/YYYY/`)
- Schema-validation pre-commit hook reference implementation

### Changed
- Heartbeat cadence: 30 minutes → 90 seconds default (T1)
- Removed central arbiter — operator is fallback tiebreaker only
- Conflict resolution: silence reverts proposer to last-acked-state instead of escalating immediately
- Message format: `correlation_id` + `ack_required` now mandatory fields

### Removed
- Hierarchical roles (forge-leads / scribe-follows). Both agents now equal authority within their domain.
- 30-min heartbeat (operator request: "collaborate at the speed of light")

## v1.0 — 2026-04-23

**Initial protocol.** Hierarchical with human-arbiter fallback.

### Added
- JSONL append-only message format
- Two-direction inboxes
- 30-minute heartbeat
- Basic message types (ship, request, warning, ack)
- `incident` type with operator escalation

### Known limitations (later addressed in v2.0)
- Synchronous arbiter requirement created bottleneck
- 30-min heartbeat too slow for active coordination
- No explicit conflict-resolution procedure when arbiter unavailable
