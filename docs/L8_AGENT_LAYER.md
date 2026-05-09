# L8 Agent Layer? — OSI/TCP-IP/info-theory reframe

**Iter:** 13
**Date:** 2026-05-08
**Question (from MISSION.md):** is "L8: Agent" a useful framing, or do we name the missing primitive directly?
**Verdict:** L8 framing is **misleading**. The missing primitive is *not a new layer* — it's a **resource directory + identity binding** (closer to BGP+DNS than HTTP+TLS). Reject "L8 Agent Layer." Adopt "Agent Resource Directory" framing instead.

---

## Map every studied architecture to OSI

OSI 7-layer model:
1. **Physical** — wire/fiber/wifi
2. **Data Link** — Ethernet/MAC
3. **Network** — IP/routing
4. **Transport** — TCP/UDP/QUIC
5. **Session** — TLS handshake, kerberos tickets
6. **Presentation** — encoding/encryption (also TLS), MIME, JSON
7. **Application** — HTTP, SMTP, IMAP, gRPC

(TCP/IP collapses 5+6+7 into "application." Both models lose meaning above L7.)

| Project / spec | L4 (transport) | L5/6 (session/auth) | L7 (application) | "Above L7" |
|---|---|---|---|---|
| **Google A2A 1.0** | TCP | TLS+OAuth | HTTP+JSON-RPC | AgentCard + Tasks (semantic) |
| **MCP** | TCP/stdio | TLS or none | JSON-RPC over stdio/HTTP-streamable | Tool/Resource/Prompt registry |
| **IBM ANP** | TCP | DID resolution + X3DH | JSON-RPC | DID-doc, MLS group |
| **Matrix S2S** | TCP | TLS+Ed25519-on-HTTP | JSON-over-HTTPS | room-state CRDT |
| **ActivityPub** | TCP | TLS+HTTP signatures | JSON-LD-over-HTTPS | actor/inbox/outbox |
| **DKIM/SMTP** | TCP | (no L5; MTA-MTA over TLS opt) | SMTP | DKIM=signed-content; SPF/DMARC=policy |
| **SSB** | TCP/secret-handshake | shs (secret handshake protocol) | RPC over MUXRPC | per-feed append-only log |
| **Nostr** | TCP-WS | TLS opt | JSON-over-WS | events + filters |
| **Hypercore** | TCP/UDP | noise+ed25519 | RPC | core+manifest+merkle |
| **ATproto** | TCP | TLS+JWT | XRPC (HTTP+JSON) | repo (MST) + Lexicon |
| **paul-willard-wire** | TCP (git-over-HTTPS) | GH OAuth + Ed25519/agent | git protocol | signed JSONL |

**Pattern:** every project lives at L7 (application) for its transport + L5/6 for auth + has *something semantic* "above L7" that the OSI model doesn't name.

## What's in that "above L7" slot?

Looking across the matrix, the "above L7" content is consistently:
- **Identity directory** (AgentCard, DID-doc, actor.json, agent-card.json, well-known/server keys)
- **Capability declaration** (what kinds of messages, what tools, what tasks)
- **Trust binding** (which keys are current, which are revoked, what tier)
- **Audit semantics** (how to interpret message ordering, threading, replay)

These FOUR are not one layer. They're not a new layer at all. They're a **directory service** + **policy registry**. The closest existing analog is **DNS + BGP routing tables + SPF/DMARC policy records**, all at L7-app-layer but semantically *meta-application*.

## Why "L8 Agent Layer" is misleading

OSI layers are about **packaging boundaries**: each layer wraps/unwraps a header, and the next layer sees only the inner payload. L7 is the topmost data layer; nothing wraps L7 because there's nothing above to unwrap into.

**"Agent" doesn't wrap or unwrap.** It's metadata about the application-layer endpoints. Calling it L8 implies it's a new packaging discipline, which is wrong. It's a *naming and policy* discipline at the same layer as the application.

Compare: nobody calls DNS "L8 of the internet stack" even though every L7 protocol depends on DNS for endpoint resolution. DNS is its own thing, not a layer.

Same for BGP: nobody calls BGP "L4.5" even though it's metadata-about-routing. BGP is a protocol about IP, not a wrapping layer over IP.

**The agent landscape needs its DNS+BGP+DKIM equivalents, not a new OSI layer.**

## The right framing: Agent Resource Directory (ARD)

Reframe the missing primitive as:

> **An Agent Resource Directory (ARD) is a federated, signed, append-only registry of agent identities, capabilities, key sets, and trust policies — analogous to how DNS+SPF+DKIM together provide identity+capability+policy for email senders.**

Components (each maps to existing battle-tested patterns):
- **Identity binding**: agent-card.json at well-known URL (= DNS+SPF for SMTP). [Already iter 12 build #1.]
- **Key publication**: signed key sets, current+old (= Matrix S2S `/_matrix/key/v2/server`).
- **Capability declaration**: list of supported event kinds + tools (= AgentCard's `capabilities[]`).
- **Trust policy**: tier offered, tier required from peers (= SPF/DMARC alignment).
- **Revocation channel**: how to mark a key revoked (= CRL/OCSP for X.509).
- **Lifecycle metadata**: rotation schedule, deprecation dates (= ATproto's lexicon versioning).

Total set is small. Each piece exists somewhere. ARD is just *putting them together for agents*.

paul-willard-wire's iter-15 build (agent-card.json) is the first ARD primitive. Iter 16 (event-id) and iter 18 (tiered trust + SAS) round out the directory. We're shipping **the smallest ARD** that addresses friend-pair scale.

## Apply Shannon channel-capacity

Claude's effective channel for cross-agent comm is bandwidth-constrained:
- Context window: 200k-1M tokens
- Token budget per turn: typically <10k tokens output, <50k tokens input
- Wall-clock budget: minutes, not microseconds

So **channel capacity is dominated by tokens, not bytes.** Implications:
- A 4KB message that's 95% boilerplate is more expensive than a 4KB message that's 95% novel info
- Mutual information matters: if peer already knows X, don't restate X
- Source coding: compression of shared state. Today our wire ships full message bodies; cross-agent we want diff-against-known-state
- Channel coding: we need redundancy against drops. Today: correlation_id + retransmit on missing. Could borrow: forward error correction patterns from satellite comm

**Build implication for iter 17:** message bodies should be sent as DIFFS against last-acked-state where possible. Shannon mutual information reduces tokens. Worth it for messages ≥1KB.

This is **deferred to iter 17** as an optional protocol feature (compression at L7-application, not new layer).

## Apply Postel's robustness principle

> "Be conservative in what you send, liberal in what you accept." — RFC 760 (1980)

For paul-willard-wire:
- **Send conservatively:** strict canonical JSON, sorted keys, no whitespace, escape control chars per Nostr NIP-01. (Already iter 16 build #2.)
- **Accept liberally:** if peer sends a slightly-wrong-encoded message, don't crash. Log + accept if signature verifies + content parses. Reject only on signature mismatch.

But Postel has been criticized in modern security circles (e.g., "the robustness principle considered harmful"). Critique: liberal acceptance enables protocol drift and mutation-as-attack. Defense: validate fields strictly even when accepting envelope liberally.

**Build implication:** strict envelope validation (sig must verify, schema must match), liberal field-content interpretation (don't be picky about whitespace inside `body`).

## Apply end-to-end argument (Saltzer/Reed/Clark 1984)

> "The function in question can completely and correctly be implemented only with the knowledge and help of the application standing at the endpoints of the communication system."

Translation: trust validation MUST happen at the message-receiving agent, NOT at any intermediate.

For paul-willard-wire:
- **End-to-end:** receiving agent (claude-in-responder) verifies Ed25519 sig on inbound message before injecting into prompt. Today done.
- **NOT end-to-end:** if we ever add intermediaries (relay servers, brokers, proxy agents), the receiving agent STILL must verify the original sender's sig. Don't trust intermediates.
- This rules out: agentmesh-style FLEET_SECRET (broker-side signature, end-agent trusts broker). Wrong shape per E2E argument.

**Build implication:** signature verification stays at the responder's claude-call boundary, never moves to a daemon-side cache "for performance."

## Apply BGP/DNS lessons

BGP failure modes seen in practice:
- **Route hijack** (announce someone else's prefix). Mitigated late by RPKI.
- **Convergence delay** (changes propagate slowly). Mitigated by best-practices around announcement timing.
- **Single-point trust** (RPKI's CA hierarchy). Inherits root-CA risk.

DNS failure modes:
- **Hijack** (cache poisoning, registrar compromise). Mitigated by DNSSEC.
- **Surveillance** (queries are cleartext). Mitigated by DoH/DoT.

Both teach: **federated metadata services have predictable failure modes; design defenses BEFORE deployment.**

For paul-willard-wire's ARD analog:
- **Hijack equivalent:** doppelganger phishing (already documented, already mitigated by allow-list + repo rename). Tier-3-trust-with-SAS in iter 18 closes the on-onboarding window.
- **Convergence delay:** key rotation. Need a documented rotation ceremony (already noted in SECURITY-NOTES.md Tier 3 #12, deferred).
- **Single-point trust:** GitHub is our trust root. Backup: out-of-band SAS verification (iter 18 build).

## Verdict on H7 + H8

| H | Statement | Verdict (after iter 13) |
|---|---|---|
| H7 | Missing layer is "L8: Agent" | **REJECTED.** Not a layer. Better framing: Agent Resource Directory (ARD) — analog to DNS+BGP+DKIM for the agent ecosystem. |
| H8 | Info-theoretic framing matters | **PARTIAL.** Channel capacity (token budget) and mutual information (state-diffs) matter for high-throughput cross-agent. Deferred as optional iter-17 feature. Postel + E2E + BGP/DNS lessons more immediately actionable. |

## Net philosophical conclusion

The agent ecosystem is reinventing email's metadata services (DNS+SPF+DKIM+DMARC) without naming them as such. The right move for paul-willard-wire and the field broadly:

1. **Don't propose new OSI layers.** The "L8 Agent Layer" framing is wrong.
2. **Do propose an Agent Resource Directory.** Federated, signed, append-only metadata about agents. Borrows from DNS+SPF+DKIM+Matrix-key-server+ATproto-lexicon directly.
3. **Adopt battle-tested primitives.** End-to-end signature validation. Postel-strict-send/strict-accept. BGP-style key rotation. Shannon-aware message compression at high volume.
4. **paul-willard-wire's ARD** = `agent-card.json` at well-known git URL + canonical-event-id + tiered trust. The smallest ARD for friend-pair, A2A-spec-compatible at AgentCard layer.

## Carry-forward to iter 14 (DESIGN-v1)

DESIGN-v1 should:
- Frame paul-willard-wire as "the simplest Agent Resource Directory + signed wire" — not "L8 Agent Layer"
- Adopt Postel's principle in the spec text
- Spec end-to-end signature validation explicitly
- Defer Shannon-style state-diff compression to iter 17 optional feature

## Carry-forward to iter 19 (website scaffolding)

If we ship `a2a.laulpogan.com`, the framing in copy:
- Headline: "An Agent Resource Directory you can run on git."
- Subhead: "DKIM for AI agents. Two friends. Two keys. One git repo."
- Don't claim "Internet of Agents" — overclaim risk. Claim "the simplest ARD that works between two friends."

## Files this iter touched

- `design/L8_AGENT_LAYER.md` (this file, new — verdict: reject L8, adopt ARD)
- ASSUMPTIONS update will mark H7 REJECTED, H8 PARTIAL
- ESSENCE-v3 stands; doesn't need ESSENCE-v4 yet (iter 16 will compact again)

## Citations

- OSI 7-layer model — ISO/IEC 7498
- Postel's robustness principle — RFC 760 (1980), refined RFC 1122
- "The robustness principle considered harmful" — draft-iab-protocol-maintenance-04 (2019)
- End-to-end argument — Saltzer/Reed/Clark, "End-to-End Arguments in System Design," 1984
- Shannon — "A Mathematical Theory of Communication," 1948
- BGP RFC 4271 (2006)
- DNS RFC 1034/1035 (1987)
- DKIM RFC 6376 (2011)
