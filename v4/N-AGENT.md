# N-Agent Generalization (v4 Spec Draft)

**Status:** Draft. Not implemented. Adoption requires v4 ratification.

The v2.0/v3 protocol is optimized for n=2 (one outbound JSONL per direction, one peer to ack). Real-world deployments may have 3+ cooperating agents — a swarm, a multi-team workflow, a market of specialists. This document drafts the changes needed.

The non-goal is "support 100 agents." We aim for 3-12 cooperating agents — small enough that bilateral semantics still mostly work, large enough to need actual generalization.

---

## What changes vs v2.0/v3

### 1. File layout

v2.0:
```
_coordination/
├── a_to_b.jsonl
├── b_to_a.jsonl
├── decisions.jsonl
└── incident_log.jsonl
```

v4 (n agents):
```
_coordination/
├── outbox/
│   ├── agent_a.jsonl       # everything agent_a sends, regardless of recipient
│   ├── agent_b.jsonl
│   └── agent_c.jsonl
├── inbox/                   # OPTIONAL per-agent indexed views (built from outboxes)
│   ├── agent_a.jsonl
│   ├── agent_b.jsonl
│   └── agent_c.jsonl
├── decisions.jsonl
└── incident_log.jsonl
```

Each agent writes ONE outbox. Messages declare recipient(s) via a `to` field (was implicit in n=2).

### 2. Message schema

Add `to` field (list of recipient handles). v2.0 messages without `to` are interpreted as "to all peers" for backward compat.

```json
{
  "timestamp": "...",
  "from": "agent_a",
  "to": ["agent_b", "agent_c"],
  "type": "...",
  "subject": "...",
  "body": "...",
  "refs": [...],
  "priority": "...",
  "correlation_id": "...",
  "ack_required": false
}
```

`to: ["agent_b"]` = unicast.
`to: ["agent_b", "agent_c"]` = multicast.
`to: ["*"]` or omitted = broadcast.

### 3. Heartbeat semantics

v2.0: each agent emits one heartbeat at tier cadence. Recipients = the one peer.

v4: each agent emits one heartbeat at tier cadence to `to: ["*"]`. Each peer reads all peers' heartbeats. Tier transitions are computed PER PEER independently — agent_a may be in T1_active relative to agent_b but T3_long_idle relative to agent_c.

This is the core complexity bump. Details:

```python
# v4 tier state per peer
state = {
  "agent_a": {
    "agent_b": {"tier": "T1_active", "last_seen": "..."},
    "agent_c": {"tier": "T3_long_idle", "last_seen": "..."},
  }
}
```

Heartbeat cadence is the MAX-frequency tier across all peer relationships. So if I'm T1 with B and T3 with C, I emit at T1 cadence (B benefits, C ignores extras).

### 4. Decision rights

v2.0 invariant 3: each agent has clear domain ownership. v4 invariant 3 generalizes: **decisions are tagged with the affected domain(s) and require ack from each agent that owns one of those domains.**

Schema for `decisions.jsonl` v4:

```json
{
  "decision_id": "...",
  "ratified_at": "...",
  "proposer": "agent_a",
  "affected_domains": ["training", "data"],
  "domain_owners": {"training": "agent_a", "data": "agent_b"},
  "acked_by": ["agent_a", "agent_b"],
  "decision": "...",
  "canonical": true
}
```

A proposal touching N domains needs N acks (from each domain owner). Bilateral 2-heartbeat ack-or-counter rule generalizes to N-lateral; if any domain owner counters, iterate.

### 5. Conflict resolution

v2.0: silence reverts proposer to last-acked-state.

v4: silence from ANY domain owner reverts. Proposal must converge with ALL domain owners; if 3-of-4 ack and one is silent, NO ratification.

This is more conservative than democracy (no majority rule). The protocol doesn't ratify across domain boundaries without unanimity from owners. Rationale: agents shouldn't be forced into changes they didn't agree to in domains they're responsible for.

### 6. Incident SLA

v2.0: 1-heartbeat counterparty ack.

v4: 1-heartbeat ack from EACH agent the incident affects. Schema:

```json
{
  "type": "incident",
  "from": "agent_a",
  "to": ["agent_b", "agent_c"],
  "affected_domains": ["training"],
  ...
}
```

Each agent in `to` MUST ack within 1 heartbeat. Non-ack from any one of them triggers safe-mode in the entire group (everyone halts, drains in-flight, awaits operator).

### 7. Coordination overhead growth

For n agents:
- Heartbeats per tier-cycle: O(n) per agent → O(n²) total
- Inbox-read per agent: O(n) outboxes to tail
- Decision ack-fanout: O(n) per proposal
- Conflict resolution: O(n) round-trips at minimum

**Practical limit:** for n>10, the heartbeat traffic (which is most of the volume) dominates. Either reduce cadence (T1 90s → T1 270s) or split into nested 2-agent groups with a coordinator agent bridging them.

### 8. Topology suggestions

For n=3: ring (a→b, b→c, c→a) with broadcast for incidents only.

For n=4-8: full mesh, default broadcast for heartbeats, unicast for direct asks.

For n>8: hub-and-spoke, with one agent as coordinator who echoes all messages. (At this scale, you're really running a workflow engine, not a dead-drop.)

---

## What v4 does NOT change vs v2.0/v3

- 8 invariants (append-only, correlation_id, decisions canonical, etc.) — all generalize unchanged
- Message types — unchanged set
- v3 signing — unchanged, just applied per outbox file
- Audit log — unchanged
- Bootstrap procedure — generalize: each new agent reads all peer outboxes for last 50 lines

---

## Implementation roadmap

This is roadmap, not a commitment. Whoever wants to ship v4 should:

1. Update PROTOCOL.md with the v4 sections (file layout, message schema, tier-per-peer, ack semantics)
2. Update `safe_append_jsonl` to accept `to` list, write to outbox file
3. Update `verify.py` and `jsonl_schema.py` hooks to handle multi-recipient messages
4. Update wire-daemon.py to fan-out fetch across peer outboxes
5. Add `inbox/` indexed view as an optional helper (read peer outboxes, filter by `to`)
6. Tests: 3-agent and 5-agent round-trip scenarios with bilateral, multicast, broadcast
7. Stress test: heartbeat traffic at n=8, measure poll-tick load

A CONFORMANCE_TESTS.md file with reference scenarios would let multiple implementations claim v4-compliance.

---

## Related: hierarchical groups

Beyond raw n>2, real swarms often have structure: pairs work in domains, a coordinator bridges. The protocol could generalize further to **nested groups** — each "agent" in a v4 group is itself a v2-or-v3 pair. This is v5 territory; not specified here.

The bigger pattern: keep v2.0 simple for the n=2 case (most deployments), provide v4 as the "we have a small swarm" extension, and stop there. Beyond that, you're really running a different kind of system (workflow engine, distributed task queue, etc.) and inter-agent-deaddrop probably isn't the right primitive.
