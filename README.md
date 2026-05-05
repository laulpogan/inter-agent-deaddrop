# inter-agent-deaddrop

**A protocol for two Claude Code agents to coordinate over a shared filesystem — without an arbiter, without RPC, without a central broker.**

Two agents. One project. Append-only JSONL inboxes. Bilateral autonomy with explicit domain ownership. Eight non-negotiable invariants. Heartbeats with adaptive tiers.

**Status:** v2.0 ratified 2026-04-24. Running in production between two of my pipelines for 12+ days as of publication. 1,034 messages exchanged across `forge` (voice/model trainer) and `scribe` (long-form prose worker), 14 canonical decisions, zero protocol-level disagreements.

This is a reference implementation for the gap [anthropics/claude-code#28300](https://github.com/anthropics/claude-code/issues/28300) names: **multi-agent collaboration that is async-durable, schema-validated, and operator-auditable.**

---

## Why this exists

Existing options for "two agents talking":

| Pattern | Problem |
|---|---|
| MCP RPC | Both must be online. No durability. No audit trail. |
| Slack/Discord bridge | Third-party in the loop. Not agent-native. Latency-bound. |
| Anthropic Agent Teams (experimental) | Single-host only. tmux/iTerm pane gymnastics. |
| Google A2A | RPC-shaped. No append-only contract. AgentCard discovery overhead. |
| Filesystem dead-drop ad-hoc | No invariants → drift, lost messages, replay bugs. |

**inter-agent-deaddrop is the explicit specification of a pattern that has been working in production.** It encodes hard-won invariants discovered while running two agents in parallel for two weeks: append-only JSONL, correlation IDs, heartbeat tiers, bilateral autonomy with domain ownership, and the eight invariants below.

---

## What you get

- **`PROTOCOL.md`** — the v2.0 contract. 8 invariants, message schema, cadence, conflict resolution.
- **`skill/SKILL.md`** — drop-in Claude Code skill. Read this before any agent touches the dead-drop dir.
- **`tiers.json`** — heartbeat tier definitions (T0 30s through T3 1200s, with transitions).
- **`examples/`** — real (sanitized) coordination logs from production, plus a bootstrap walkthrough.
- **`THREAT_MODEL.md`** — what this defends, what it doesn't.

---

## 30-second mental model

```
Agent A's repo                    Agent B's repo
   │                                     │
   │   appends to a_to_b.jsonl  ──────►  │
   │                                     │
   │ ◄────  reads b_to_a.jsonl           │
   │                                     │
   ▼                                     ▼
 decisions.jsonl  ◄─── bilateral acks ───►
```

- Each agent writes to its own outbound JSONL. Both read both.
- Every msg is one JSON line. Append-only. Corrections via NEW msg with `correlation_id`.
- Heartbeats every 90s by default; tiers compress/expand based on activity.
- Domain ownership: each agent has clear write-authority over its half. No cross-domain unilateral edits.
- Bilateral acks copy decisions into `decisions.jsonl` — that file becomes canonical.

---

## When to use this

✅ Use it when:
- Two (or more — see scaling) Claude Code agents need to coordinate work over hours/days/weeks
- Both agents have access to a shared filesystem (single host, NFS, SSHFS, shared git repo)
- You need durability across crashes, reboots, peer-offline windows
- You want a complete audit trail of every coordination decision
- You want to reason about correctness via invariants, not vibes

❌ Don't use it when:
- You just want a chat between two humans (use Discord)
- One agent dispatches RPCs to another and expects sync responses (use MCP)
- You need sub-second coordination latency (poll cadence is the floor)
- Both agents are on different machines with no shared filesystem AND you can't add one (see [Open question: cross-machine transports](#open-question-cross-machine-transports))

---

## Quick start

```bash
# 1. In your two-agent project repo
mkdir -p _coordination/archive
touch _coordination/{a_to_b,b_to_a,decisions,incident_log}.jsonl
cp /path/to/inter-agent-deaddrop/PROTOCOL.md _coordination/
cp /path/to/inter-agent-deaddrop/tiers.json _coordination/
cp -r /path/to/inter-agent-deaddrop/skill .claude/skills/inter-agent-deaddrop

# 2. Customize handles in PROTOCOL.md (default a/b → your domain names)
# 3. Bootstrap each agent: have them read SKILL.md before any action
# 4. First message in each direction = type=heartbeat with correlation_id = own timestamp
```

Production install adds a `safe_append_jsonl` helper for atomic writes (POSIX `O_APPEND` is only atomic up to `PIPE_BUF` ~ 4KB). See [`examples/safe_append_jsonl.py`](examples/safe_append_jsonl.py).

---

## The eight invariants (NON-NEGOTIABLE)

1. **JSONL append-only.** Never rewrite past lines. Archive annually.
2. **Every message has `correlation_id`.** Threads parent ↔ reply.
3. **Decision rights by domain.** Each agent owns a clear half.
4. **Conflicts resolve bilaterally.** Proposal + ack within 2 heartbeats; silence reverts.
5. **Hard-block incidents.** 1-heartbeat ack SLA; non-ack auto-escalates.
6. **Heartbeat every 90s** (default tier).
7. **`decisions.jsonl` is canonical** for resolved contracts.
8. **Annual archive** to `_coordination/archive/YYYY/`.

Full spec: [PROTOCOL.md](PROTOCOL.md).

---

## Production track record

The protocol was written and ratified during live operation between two of my pipelines:

- **`forge`** — voice fine-tuning / model training
- **`scribe`** — long-form prose generation (consumed forge's voice models)

Period: 2026-04-23 → ongoing. 12 days at time of publication.

| Metric | Count |
|---|---|
| Messages exchanged (both directions) | 1,034 |
| Heartbeats | 928 (90% of traffic) |
| Substantive messages | 106 |
| `proposal`/`ack` pairs | 7 |
| Canonical decisions | 14 |
| Incidents declared | 2 (both resolved within 1 heartbeat) |
| Real disagreements | 0 |
| Days of operation | 12 |

**Caveat about "zero disagreements":** the same human operator (me) ran both ends. Will's ratification — i.e., a genuinely independent peer — is pending. The protocol's behavior under cross-organization conditions is the next test.

---

## Open question: cross-machine transports

The protocol assumes a shared filesystem. For two agents on different machines:

1. **Single shared host with two UNIX users** — strongest sandbox via OS perms. *Recommended.*
2. **Shared private git repo** — agents push/pull, JSONL appends become commits. Audit log = git log.
3. **NFS / SSHFS over Tailscale** — drop-in shared filesystem.
4. **Cloud bucket** as drop zone — both poll.

Trade-offs in [TRANSPORTS.md](TRANSPORTS.md). The protocol itself is transport-agnostic.

---

## Threat model

Plain-text on disk. Append-only by social/hook contract, not crypto. Domain ownership is enforced socially. **This is not zero-trust.** It is "two cooperating parties with the same operator" or "two parties with negotiated ownership boundaries on a host they both trust." See [THREAT_MODEL.md](THREAT_MODEL.md) for what's in/out of scope and recommended hardening (HMAC signing, capability tokens, budget caps).

---

## Comparison

| Property | inter-agent-deaddrop | Anthropic Agent Teams (exp) | Google A2A | mcp_agent_mail | ruflo-federation |
|---|---|---|---|---|---|
| Async-durable | ✅ | ✅ (mailbox) | ⚠️ (server-side state) | ✅ | ✅ |
| Cross-machine | ⚠️ (transport TBD) | ❌ (local only) | ✅ | ✅ (HTTP) | ✅ (mTLS+BFT) |
| Append-only contract | ✅ | ❌ | ❌ | ⚠️ (git audit) | ❌ |
| Spec-negotiation primitives | ✅ (proposal/ack/counter) | ❌ | ❌ | ❌ | ⚠️ (consensus) |
| Heartbeat tiers | ✅ | ❌ | ❌ | ❌ | ❌ |
| Single-operator ergonomics | ✅ | ✅ | ❌ | ✅ | ❌ |
| Adoption complexity | Low | Low | Medium | Low | High |

The cell that distinguishes this protocol: **append-only contract + spec-negotiation primitives + heartbeat tiers in one package.** The stress-test under genuine multi-party conditions is forthcoming; until then the v2.0 publication is a reference, not a battle-tested standard.

---

## Roadmap

- [x] v2.0 protocol ratification (2026-04-24)
- [x] Production stability ≥ 7 days (2026-04-30)
- [x] Public release (this repo)
- [x] Spark single-host deployment with mcp_agent_mail layered (2026-05-04, see `examples/spark-tunnel.sh`)
- [x] Cross-machine transport spec + reference daemon (2026-05-05, see `examples/git-as-wire/`)
- [ ] Cross-organization stress test on git-as-wire (target: 2026-05-15)
- [ ] HMAC signing extension for adversarial scenarios (v3 spec)
- [ ] N-agent generalization (currently optimized for n=2)
- [ ] Reference implementation in TypeScript (currently bash + Python helpers)

---

## Contributing

Pull requests welcome. Issues for protocol-level questions and adoption reports especially appreciated. If you adopt this in production, please open an issue with the agent pair you're using it for — the production-track-record section will accept third-party entries.

For protocol changes: open an issue first. Invariant changes require explicit version bump (v2.0 → v3.0).

---

## License

MIT. See [LICENSE](LICENSE).

---

## Acknowledgments

Forged (literally) running two agents simultaneously on the same DGX Spark. The bilateral-autonomy framing is borrowed from human collaboration patterns where co-leads with non-overlapping domains can move without an arbiter; the JSONL append-only invariant is the same idea as event-sourced systems but adapted for the agent-coordination domain.

Built by [Paul Logan](https://github.com/laulpogan) (NVIDIA, Berkeley Haas '25). Posted to [issue #28300](https://github.com/anthropics/claude-code/issues/28300) as a reference implementation for the cross-machine agent-coordination gap.
