# RECOMMENDATIONS — final deliverable (iter 20)

**Date:** 2026-05-08
**Sources:** clusters/iter-01..11; ESSENCE-v1..v4; design/L8_AGENT_LAYER.md, DESIGN-v1.md; PAIN_POINTS.md; ASSUMPTIONS.md; iter 15-19 build artifacts.
**Audience:** operator (Paul Logan), peer operator (Will Klein), future contributors, public visitors at https://a2a.laulpogan.com.

---

## Verdict on the 10 hypotheses

| H | Statement | Verdict | Evidence |
|---|---|---|---|
| H1 | Most A2A frameworks are intra-org | ✅ HOLDS strongly | LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, smolagents — all single-trust-domain. AutoGen's gRPC distributed runtime has single trust gateway. |
| H2 | Cross-org A2A pain real and unsolved | ✅ HOLDS overwhelmingly | HN top critical comments on A2A; arXiv 2505.23847; OpenAI rejecting A2A PR; ~13 cross-org issues across autogen+crewai+claude-peers; Anthropic's own products don't federate (claude-code #56353). |
| H3 | Federation patterns from non-AI dist sys are richer than current LLM agent frameworks acknowledge | ✅ HOLDS | DKIM, Matrix S2S, ActivityPub, XMPP, SSB, Nostr, Hypercore, ATproto = 30 years of battle-tested primitives being reinvented. |
| H4 | MCP is intra-process, not federation | ✅ confirmed | Anthropic's own roadmap promises remote MCP for "an entire Claude for Work organization" — single-tenant. |
| H5 | Google A2A targets gap, gap less crowded than expected | ✅ HOLDS | A2A is winning the spec war: MAF + crewAI #5147 + agentmesh AgentCard import + Microsoft AGT bridges all adopt or interop. |
| H6 | Community reinventing MQTT-for-agents | ✅ HOLDS + extends | agentmesh has full MQTT primitive set. The pattern extends to "reinventing email/Matrix/SSB/Nostr/Hypercore/ATproto primitives more broadly." |
| H7 | Missing layer is "L8: Agent" | ❌ REJECTED | Wrong framing. OSI layers are packaging boundaries; agent metadata doesn't wrap or unwrap. Better: **Agent Resource Directory (ARD)** — analog to DNS+SPF+DKIM+DMARC for agents. |
| H8 | Info-theoretic framing matters | ⚠️ PARTIAL | Channel capacity (token budget) and mutual information (state-diffs) matter for high-throughput. Deferred as optional v3.2 feature. Postel + E2E + BGP/DNS lessons more immediately actionable. |
| H9 | Substrate-substitutability matters; vendor-neutrality is the niche | ✅ HOLDS | git/Discord/Slack/email/tmux are all valid substrates. paul-willard-wire's vendor-neutrality is the durable position. |
| H10 | Vendor competitive dynamics keep cross-org A2A fragmented for years | ✅ HOLDS | OpenAI rejecting Google A2A integration PR is the canonical example. Microsoft owning AGT (governance lane) and Google owning A2A (transport lane) means no single winner. |

## Top 10 features-to-steal (ranked by leverage / cost — across all 11 research iters)

1. **Agent Card at well-known URL** (Google A2A + Matrix S2S + AGT + AP + SSB) — discovery + capability declaration in one move. Implemented iter 15.
2. **Content-addressable event-id** (Nostr NIP-01 + DKIM canonicalization) — free dedup + tamper detection. Implemented iter 17.
3. **Tiered trust + SAS verification** (claude-flow plugin + AGT + Matrix-style SAS) — defends doppelganger phishing on first contact. Implemented iter 18.
4. **DID-formatted handles** (ATproto + ANP + AGT) — interop-ready without DID-resolution complexity. Implemented iter 17.
5. **Last Will & Testament + dead-letter queue** (MQTT/agentmesh) — surfacing offline peers. **Not yet implemented; v3.2 candidate.**
6. **MQTT topic+wildcard subscription** (agentmesh) — N-party fanout without breaking bilateral. **Deferred until N≥3 demand.**
7. **DKIM SDID/AUID distinction** — separate "signing organization" from "agent identity." **Partial: our `from` field can carry DID; SDID is implicit in repo ownership.**
8. **ARC-style forwarding chain** (RFC 8617) — model for multi-hop forwarding. **Deferred until forwarding demand.**
9. **Hypercore merkle-chain integrity** — strict superset of per-line signing. **Deferred; current per-message event-id sufficient.**
10. **ATproto Lexicon-style schema files** — static validation + IDE autocomplete. **Partial: trust + agent-card schemas exist; full Lexicon adoption is overkill.**

## Top 5 anti-patterns avoided

1. **No central broker.** agentmesh's lane. Defeats bilateral simplicity. Locked OUT.
2. **No mesh gossip.** SSB/Hypercore lane. N-party not needed for friend-pair.
3. **No post-quantum signatures (ML-DSA-65).** Microsoft AGT does it because Microsoft. Bloats wire 100x. Defer until quantum is real threat.
4. **No governance / policy engine.** Microsoft AGT's lane (1448 stars, well-resourced). Don't compete.
5. **No "L8 Agent Layer" overclaim.** Reframed as Agent Resource Directory (iter 13).

## Cross-org A2A market sizing

**Verdict: niche but provably underserved.**

- **5 independent OSS implementations** of cross-org agent trust converged in 6 months
- **8 spec proposals** in active circulation (Google A2A, IBM ANP, IBM ACP, Microsoft IATP, academic ACP, Anthropic remote MCP, paul-willard-wire, AGT/agentmesh-platform)
- **6 industry-analyst "vs" articles** published 2025-2026 (Boomi, Camunda, AWS, IBM, NeosAlpha, Koyeb) — classic confused-market signal
- **OpenAI competitive rejection of A2A** confirms vendor-fragmentation lasts years
- **Anthropic's own products don't federate** — the gap exists even within single vendors
- **Friend-pair niche** (operator + 1 peer) is too small for any vendor to address; paul-willard-wire occupies it indefinitely

Market size for paul-willard-wire's exact niche (vendor-neutral, friend-pair, cryptographic): small but persistent. Few users, but each user has very high engagement (operators running their own agent infra). Better positioning: "the simplest reference implementation of an Agent Resource Directory you can run on git."

## What we'd build differently if starting fresh

Three small things, captured for future v3.2+:
1. **Adopt DID-formatted handles from day one.** We bolted them on iter 17. Earlier would've been cleaner.
2. **Canonical-serialization spec before any signed implementation.** SECURITY-NOTES.md Tier 2 #9 was deferred from v3.0; we caught up iter 17.
3. **Tiered trust before doppelganger phishing happened.** Iter 18 closed the actual incident vector. If we'd started here, the May 2026 incident would've blocked at UNTRUSTED tier.

## What we keep

The load-bearing decisions of paul-willard-wire stay:
- **Bilateral.** Two operators, two keys, one git repo. Don't N-party until forced.
- **Git as wire.** No daemon required. Replay is `git log`. Survives partitions.
- **Append-only signed JSONL.** Simple, durable, replay-safe.
- **Ed25519 per agent.** Forge-proof regardless of broker compromise.
- **Conservative defaults.** Handles ≥7-of-9 of agentmesh's open failure modes natively.
- **822 → ~1700 LOC after v3.1.** Smallest A2A wire impl studied; ~10x smaller than nearest comparable.

## Operator-decision matrix (what to do next)

After 20 iters, three paths:

| Path | Effort | Reward | Risk |
|---|---|---|---|
| **Path A — Ship v3.1 silently** | Low (commit + push v3 repo) | Validates site links; closes loop with Will. | None significant. |
| **Path B — Public announcement** | Medium (HN post, blog, twitter thread) | Visibility; might attract collaborators. | Could attract noise / unwanted attention; doppelganger-incident-redux. |
| **Path C — Shelve as research artifact** | Zero | Site stays as snapshot; build artifacts unused beyond friend-pair. | Lost momentum. |

**Recommendation: Path A.** Push v3 build artifacts to `github.com/laulpogan/inter-agent-deaddrop` so site links resolve. Wire-message Will with summary. Defer Path B (public announcement) until operator decides framing + readiness for noise.

## Build artifacts shipped (iters 15-19)

| Artifact | Path | LOC | Status |
|---|---|---|---|
| agent_card.py | inter-agent-deaddrop-v3/ | 210 | shipped, 9 tests pass |
| signing.py extended | inter-agent-deaddrop-v3/ | 415 (was 236) | shipped, 17 v3.1 tests pass |
| wire_trust.py | inter-agent-deaddrop-v3/ | 273 | shipped, 26 tests pass |
| paul.card.json | inter-agent-deaddrop-v3/_coordination/trust/ | 1133 bytes | signed, self-verifies |
| site/index.html | inter-agent-deaddrop-v3/site/ | 192 | live at https://a2a.laulpogan.com |
| site/server.py | inter-agent-deaddrop-v3/site/ | 32 | systemd-supervised |
| a2a-site.service | ~/.config/systemd/user/ | 14 | enabled, active |
| cloudflared route | ~/.cloudflared/config.yml | +2 lines | a2a.laulpogan.com → :8091 |
| **Total code (without tests)** | | **898 LOC** | |
| **Total tests** | | **575 LOC, 52 pass** | |
| **Wire-codebase total** | | **1473 LOC** | smallest A2A wire impl studied |

## Research artifacts (iters 1-13)

| Artifact | Path | Lines |
|---|---|---|
| MISSION.md (v2 expanded) | research/a2a-frameworks/ | 142 |
| ASSUMPTIONS.md | " | 99 |
| PAIN_POINTS.md | " | 168 |
| STATUS.md | " | 60 |
| 9 cluster docs (iter-01..11) | research/a2a-frameworks/clusters/ | ~1,800 lines |
| 4 essence docs (v1..v4) | research/a2a-frameworks/essence/ | ~700 lines |
| 2 design docs (L8, DESIGN-v1) | research/a2a-frameworks/design/ | ~370 lines |
| RECOMMENDATIONS.md | this file | ~200 |
| **Research total** | | ~3,500 lines, 5 primary-source files cached |

## Citations (top-level, full lists in cluster docs)

- Google A2A 1.0 spec: https://github.com/google-a2a/A2A
- IBM ANP whitepaper: https://github.com/agent-network-protocol
- IBM ACP: https://www.ibm.com/think/topics/agent-communication-protocol
- Microsoft AGT: https://github.com/microsoft/agent-governance-toolkit
- Microsoft Agent Framework (MAF): announced as AutoGen successor
- Anthropic MCP: https://modelcontextprotocol.io
- louislva/claude-peers-mcp: https://github.com/louislva/claude-peers-mcp
- ruvnet/ruflo plugin-agent-federation: https://github.com/ruvnet/ruflo/issues/1669
- HN A2A discussion: https://news.ycombinator.com/item?id=43631381
- OpenAI rejecting A2A PR: https://news.ycombinator.com/item?id=45766384
- Cross-domain Multi-agent LLM Security paper: https://arxiv.org/html/2505.23847v1
- DKIM RFC 6376: https://www.rfc-editor.org/rfc/rfc6376.txt
- Nostr NIP-01: https://github.com/nostr-protocol/nips/blob/master/01.md
- Matrix S2S: https://github.com/matrix-org/matrix-spec/blob/main/content/server-server-api.md
- ATproto: https://github.com/bluesky-social/atproto

## Pending (post iter-20 cleanup, not blocking promise)

- [ ] Operator commits + pushes v3.1 build artifacts to public `github.com/laulpogan/inter-agent-deaddrop` (or new repo)
- [ ] Operator-decision: Path A vs B vs C above
- [ ] Wire-migrate-v31 script — referenced in DESIGN-v1, not yet shipped (deferred to ops phase)
- [ ] Responder integration of tier-gating — wire_trust.py is library-ready; responder needs ~30 LOC integration to call `accept_kind_for_tier`
- [ ] Update inter-agent-deaddrop README with link to a2a.laulpogan.com

These are operational follow-ups, not research/build deliverables. Loop completes here.
