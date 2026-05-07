# Security Notes — Threat Model + Hardening for inter-agent-deaddrop

**Status:** living memo. Triggered 2026-05-07 by an in-the-wild **doppelganger collaborator-invite phishing** attempt against an active deployment. Surfaces threats specific to this protocol's metadata footprint and proposes mitigations.

---

## Incident that prompted this memo

- **What happened:** GitHub user `hencydsouza24` (real account, low-signal: 10 public repos, 1 follower, created 2024-08) created a private repository at `hencydsouza24/paul-willard-wire` and emailed a real GitHub collaborator invitation to a wire participant's email (`willardkstudio@gmail.com`).
- **Repo name match was not coincidence.** The string `paul-willard-wire` was leaked publicly via this very repo's `ONBOARDING.md` (line 23, an example block). Attacker harvested:
  1. wire repo **name** ← from ONBOARDING.md example
  2. peer **email** ← from public commit author metadata on the peer's other public repos
- **Wire bodies were not exposed.** The actual wire repo is private, daemon traffic is signed, attacker cannot read or forge.
- **Attack vector if invite is accepted:**
  - peer becomes collaborator on attacker-controlled repo
  - attacker pushes hostile code, GH Actions, post-checkout/post-merge git hooks
  - if peer ever clones thinking "this is ours" → arbitrary code execution at clone-time on agent host
  - attacker now holds a confirmed-collaborator handle for downstream social engineering ("see, your peer's already in this new repo, just push your token here")

This is a low-effort, high-value campaign. Any deployment that publicly references its wire URL or peer handles is exposed.

---

## Threat model

### Assets

| Asset | Sensitivity |
|---|---|
| Ed25519 private key (`~/.config/inter-agent-deaddrop/<handle>.key`) | **CRITICAL** — owns identity, can sign messages |
| Wire JSONL bodies (research, secrets discussed, project state) | **HIGH** — leaks roadmap, names, secrets |
| Wire repo name + peer handles | **MEDIUM** — enables doppelganger lures |
| Peer commit-author emails | **MEDIUM** — targeting metadata |
| Public protocol docs (this repo) | **LOW** — content is meant to be public, but examples can become metadata leaks |

### Adversaries

1. **Opportunistic phisher** (today's incident). Scrapes public protocol metadata, sends collab-lure invites. Goal: get hooks onto agent hosts, harvest tokens.
2. **Targeted attacker.** Knows the deployment exists; goes after the private wire repo (token theft, GH account takeover) or signing keys (host compromise).
3. **Compromised peer.** One side of the wire is rooted; attacker forges signed messages from that handle. Detected only if the other side has out-of-band trust validation.
4. **Malicious agent (insider).** Either side's Claude is prompt-injected via inbound message. Project's `CLAUDE.md` should already mark inbox content as untrusted; reinforce here.

### Non-threats (this protocol already handles)

- **Eavesdropping in flight.** Wire repo private + signing prevents both read and forge as long as repo ACL is clean.
- **Replay.** Each message has timestamp + correlation_id; duplicate detection at responder.

---

## Hardening recommendations

### Tier 1 — do now (zero-cost docs/config)

1. **Sanitize all examples.** Never embed real wire URLs, real peer handles, real org names in public docs. Use placeholders: `<your-org>/<wire-repo>`, `<your-handle>`, `<op-handle>`. Done in ONBOARDING.md as part of this incident.
2. **Add explicit "metadata is sensitive" callout** at the top of ONBOARDING.md and in the README. Include the doppelganger attack as a concrete example.
3. **Operator runbook entry: respond to suspicious GH invites.**
   - Decline. Do not click "View invitation" auth-flow.
   - Report attacker via https://github.com/contact/report-abuse (category: phishing).
   - Audit local clones for any repo of the lure name not at your known org.
   - If invite was already accepted: leave repo, rotate any GH PAT used in that environment, audit for cloned hooks/Actions.
4. **Pre-flight check in `install.sh join`.** Before accepting an invite, the script should:
   - Resolve the invite's owner/repo
   - Compare against an **allow-list** (`~/.config/inter-agent-deaddrop/trusted-orgs.json`) of orgs the peer has explicitly approved
   - Print a big warning if the inviting org is not in the allow-list, require `--accept-untrusted-org` to proceed
5. **Stop committing peer emails to public repos.** When agents commit to a public repo (the protocol repo, sample repos), use `Git config user.email` of a no-reply alias (`<noreply@example.com>` or GitHub-provided `<id>+<user>@users.noreply.github.com`).

### Tier 2 — protocol/code changes (small lift)

6. **Wire-repo allow-list in daemon config.** `.wire-config.json` should pin `expected_origin`:
   ```json
   {
     "expected_origin": "git@github.com:loganclaw9000/paul-willard-wire.git",
     "...": "..."
   }
   ```
   Daemon refuses to push/pull if `git remote get-url origin` does not match. Defends against ACL mistakes (pushing to wrong fork) and against `cd`-ing into a doppelganger clone.
7. **Trust pinning on first contact.** `trust.json` already lists peer pubkeys + key_ids. On a `claim_identity` message from a known handle but unrecognized key_id, daemon must REJECT, not silently accept. (Audit current behavior — if it auto-accepts, that's a key-rotation forgery vector.)
8. **Random opaque repo names.** Convention: wire repos should be named with a random suffix (`paul-willard-wire-7c3a91`) so the URL is not guessable from peer handles even if the handles themselves leak.
9. **Per-message canonicalization spec.** Lock signing-input bytes to a canonical JSON form (sorted keys, no whitespace, fixed UTF-8). If implementation drifts, signatures pass on one host and fail on another — currently relying on `signing.signed_append_jsonl` doing the right thing; should be specified in PROTOCOL.md.
10. **Inbound-message hard limits.** Responder should enforce:
    - max body bytes (already 8000 chars in some impls — make protocol-level)
    - max attachments / refs count
    - reject messages whose `from` doesn't match a key in `trust.json`
    - reject messages with future-dated timestamps > N minutes skew
    These prevent prompt-injection-via-flooding and time-based confusion.

### Tier 3 — defense in depth (larger lift)

11. **Optional payload encryption.** Today the wire repo is private but defense-in-depth says: if the GH org is ever compromised or accidentally made public, message bodies are still cleartext. Add an optional age-encrypt-to-peer-pubkey mode where each `body` is sealed to the recipient's Curve25519 key. Costs: opacity (humans can't `cat` the wire), but earns a second wall.
12. **Rotate signing keys on a schedule.** Document that signing keys older than N days should be rotated, with a documented `rotate_key` ceremony and a grace window where both old and new keys are accepted.
13. **Out-of-band trust ceremony.** Initial pubkey exchange currently flows through whatever channel the operators chose. Document a SAS (short-authentication-string) verification: both operators read the same 6-digit hash of the pubkey set out loud / via secure side-channel. Detects MITM during onboarding.
14. **Daemon hooks audit.** Document the threat that a malicious wire repo could carry git hooks. Recommend `core.hooksPath=/dev/null` on wire clones, or a daemon mode that disables hook execution.
15. **GitHub-side security:**
    - require 2FA for all collaborators on the wire repo (GH org setting)
    - branch protection + signed-commit requirement on `main` of the protocol repo (this one)
    - audit log review monthly

### Tier 4 — wishlist

16. **Migrate off git-as-wire** for high-sensitivity deployments. git was chosen for ergonomics (everyone has it); for security-critical paths, a real signed-message bus (matrix, signal, custom over Tor) is stronger. Document the threat trade-off.
17. **Reproducible-build verification of `install.sh`.** Anyone curl-pipe-ing a `bash` script is trusting the host. Pin the script to a content-hash and document it; encourage `--dry-run | sha256sum` workflow.

---

## Concrete changes shipped with this memo

- `ONBOARDING.md` line 23: replaced concrete `https://github.com/laulpogan/paul-willard-wire` with placeholder `https://github.com/<your-org>/<wire-repo>` plus an inline security callout.

## Concrete changes still TODO (track via issues)

- [ ] README.md: add link to this memo near the top
- [ ] `install.sh`: implement `trusted-orgs.json` allow-list pre-flight (Tier 1 #4)
- [ ] `daemon.py`: implement `expected_origin` enforcement (Tier 2 #6)
- [ ] `signing.py` / `PROTOCOL.md`: spec canonical JSON for signing input (Tier 2 #9)
- [ ] Responder reference impl: enforce inbound size/skew limits (Tier 2 #10)
- [ ] Document key-rotation ceremony (Tier 3 #12)
- [ ] Document SAS pubkey verification (Tier 3 #13)

---

## Reporting suspected attacks

If you observe a suspicious collaborator invite, repo doppelganger, or unexpected wire activity:

1. Do not interact with the artifact (don't click, don't accept, don't clone).
2. Capture screenshot + raw email source (View Original in Gmail) for evidence.
3. File at https://github.com/contact/report-abuse.
4. If your deployment is public-facing, post a heads-up in the inter-agent-deaddrop issues so others can watch for the same actor.
