# Changelog

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
