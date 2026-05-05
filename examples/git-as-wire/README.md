# git-as-wire transport

Cross-machine inter-agent-deaddrop where the **shared filesystem is a private git repo**. Each agent commits its outbound JSONL appends locally, pushes to the shared remote; the counterparty fetches at heartbeat cadence and processes new messages.

**Why this matters:** the v2.0 protocol assumes a shared filesystem. Single-host deployments (two UNIX users + setgid group) are the strongest case but require both operators to have access to the same physical host. **git-as-wire is the cross-host, cross-org transport** — two independent operators, two independent machines, only a shared private repo as common ground.

**Status:** Validated 2026-05-05 with a real cross-machine deployment between a macOS host (paul-mac) and a Linux host (paul-spark / DGX Spark) using a private GitHub repo. Full round-trip (heartbeat → ack) completed in ~30s with daemons in `--once` mode on each side. Local two-clone integration test (`test/test-roundtrip.sh`) passes.

---

## When to use this

✅ Two operators, separate machines, neither admin of the other
✅ Already comfortable with git workflow
✅ Want auditable, signed history out of the box
✅ Want offline tolerance (queue locally, push on reconnect)
✅ Want zero hosted infrastructure (private repo on GitHub/Gitea/self-host)

❌ You actually share a host already (use single-host deploy — strictly better sandboxing)
❌ You need sub-minute coordination latency (poll cadence is the floor)
❌ You don't trust the git remote service to keep your coordination history

---

## Architecture

```
agent_a's machine                       agent_b's machine
─────────────────                       ─────────────────
local clone of wire repo                local clone of wire repo
   │                                       │
   │ append to a_to_b.jsonl                │ append to b_to_a.jsonl
   │ commit (signed) ────► git push        │ commit (signed) ────► git push
   │                          │            │                          │
   │                          ▼            │                          ▼
   │                   shared private repo (origin/main)
   │                          │            │
   │ git fetch ◄──────────────┴───── git fetch
   │ git rebase                            │ git rebase
   │ read new b_to_a.jsonl entries         │ read new a_to_b.jsonl entries
   ▼                                       ▼
heartbeat tier loop                     heartbeat tier loop
```

Each side runs a sync daemon that:

1. **Watches local `_coordination/` for changes** — when a JSONL file is appended, daemon stages + commits + pushes
2. **Polls remote at heartbeat cadence** — `git fetch + rebase` to pull peer's appends; if rebase fails on JSONL files (impossible if append-only is honored), incident
3. **Tracks read positions** — `<agent>_state.json` records last-processed line per inbound file

---

## Setup

### One-time, by the operator (or by both jointly)

1. **Create a private git repo.** GitHub recommended for branch protection ergonomics:

   ```bash
   gh repo create your-coord-wire --private
   ```

   Or self-host Gitea / GitLab — same shape.

2. **Configure branch protection on `main`:**

   - Require signed commits
   - Restrict push to allowed signing keys
   - **Block force-push** (critical — append-only invariant depends on this)
   - No PR review required (agents push directly)

3. **Bootstrap the wire repo:**

   ```bash
   git clone <repo-url> wire && cd wire
   mkdir -p _coordination/archive
   touch _coordination/{a_to_b,b_to_a,decisions,incident_log}.jsonl
   cp /path/to/inter-agent-deaddrop/PROTOCOL.md _coordination/
   cp /path/to/inter-agent-deaddrop/tiers.json _coordination/
   git add -A
   git commit -S -m "Bootstrap wire repo for inter-agent-deaddrop v2.0"
   git push origin main
   ```

   Edit `_coordination/PROTOCOL.md` to substitute the `<a>`/`<b>` placeholders with your handles and declare domain ownership.

### Per side (each operator does this on their own machine)

1. **Clone the wire repo:**

   ```bash
   git clone <repo-url> ~/coord-wire
   cd ~/coord-wire
   ```

2. **Set up commit signing** (one of):

   - SSH-key signing (recommended, simplest):
     ```bash
     git config user.name "<your-handle>"
     git config user.email "<handle>@<domain>"
     git config gpg.format ssh
     git config user.signingkey ~/.ssh/id_ed25519.pub
     git config commit.gpgsign true
     git config tag.gpgsign true
     ```
   - GPG signing (more setup):
     ```bash
     git config user.signingkey <gpg-key-id>
     git config commit.gpgsign true
     ```

3. **Install the wire daemon:**

   ```bash
   cp /path/to/inter-agent-deaddrop/examples/git-as-wire/wire-daemon.py ~/coord-wire/.wire-daemon.py
   chmod +x ~/coord-wire/.wire-daemon.py
   ```

4. **Configure your agent identity:**

   ```bash
   cat > ~/coord-wire/.wire-config.json <<EOF
   {
     "agent": "agent_a",
     "outbound_file": "_coordination/a_to_b.jsonl",
     "inbound_file": "_coordination/b_to_a.jsonl",
     "heartbeat_cadence_sec": 90,
     "remote": "origin",
     "branch": "main"
   }
   EOF
   ```

5. **Start the daemon:**

   ```bash
   # foreground for testing
   python3 ~/coord-wire/.wire-daemon.py ~/coord-wire

   # or as a systemd user unit
   cp /path/to/inter-agent-deaddrop/examples/git-as-wire/wire-daemon.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now wire-daemon
   ```

6. **Each agent's Claude session reads the inbound JSONL and writes the outbound JSONL.** The daemon takes care of git push/fetch.

---

## How appends become commits

When your Claude agent calls `safe_append_jsonl(path("_coordination/a_to_b.jsonl"), msg)`:

1. The line is appended to the local file (atomic, fcntl-locked)
2. The daemon's file-watch (or 5s polling fallback) detects the change
3. The daemon `git add` + `git commit -S` + `git push origin main`
4. Commit message format: `msg: <type> from <agent> [correlation_id=<short>]`
5. If push fails non-fast-forward: `git pull --rebase`, retry up to 3 times, then `incident_log.jsonl` entry

Counterparty side:

1. Daemon polls `git fetch + rebase` every heartbeat tick
2. New commits visible in the local clone
3. Tail `b_to_a.jsonl` from the last-read position recorded in `<agent>_state.json`

---

## Failure modes

| Mode | Behavior |
|---|---|
| **Concurrent push (both append within same tick)** | One gets fast-forward; other rebases. Append-only files = no merge conflict on content. |
| **Long offline (one side)** | Online side queues commits locally, pushes when remote reachable. Counterparty fetches + sees backlog on next heartbeat. |
| **Long offline (both sides)** | Each side queues local commits. First to come online pushes; other rebases on next attempt. |
| **Force-push attempt** | Blocked by branch protection (operator MUST configure this). Without protection, force-push violates append-only invariant. |
| **Conflict on PROTOCOL.md or decisions.jsonl** | Should not happen if domain ownership honored. If it does, daemon writes `incident: bilateral_conflict` and stops — operator resolves. |
| **Schema drift (one side ahead of protocol version)** | First message rejected by recipient's schema validator → `incident: schema_drift` → halt. |
| **Remote unavailable** | Daemon retries with exponential backoff; tracks staleness; incident if staleness > 1 hour. |
| **Signing key compromise** | Operator rotates signing key in branch protection settings; counterparty must update their trusted-keys list. |

---

## Honest scope

**What this gives you:**
- Cross-host, cross-org transport with no shared infra
- Cryptographically signed identity (commit signatures)
- Full audit log (`git log` over JSONL files)
- Offline tolerance per side
- Append-only invariant enforced by hook + branch protection
- Free / cheap (private repo on GitHub or self-hosted Gitea)

**What this does NOT give you:**
- Sub-minute coordination latency (poll cadence is the floor — minimum 30s at T0)
- Hard real-time mutual exclusion (file leases would still need an upper layer; consider mcp_agent_mail in addition)
- Privacy from the git host (GitHub admins can theoretically read your coord; self-host if this matters)
- Resistance to a malicious peer with valid signing keys (signatures prove "from"; not "honest")

**Trust model:** cooperative. v3 HMAC-on-message-content extension would address adversarial scenarios; not implemented yet.

---

## Comparison to other transports

| Property | git-as-wire | Single shared host | mcp_agent_mail | NFS over Tailscale |
|---|---|---|---|---|
| Cross-org friendly | ✅ | ❌ (one operator's host) | ❌ (single server) | ⚠️ |
| Offline tolerance | ✅ (per-side queue) | N/A (shared FS) | ❌ (server must be up) | ❌ |
| Cryptographic identity | ✅ (signed commits) | ⚠️ (UNIX uid only) | ⚠️ (bearer token) | ⚠️ |
| Audit log | ✅ (git log) | mtime + git | ⚠️ (verbose, see #156) | mtime |
| Setup complexity | medium (signing + branch protection) | high (sudo + UNIX provisioning) | medium (server + tokens) | high (NFS over WAN) |
| Latency | poll-bound (~90s default) | filesystem (~ms) | RPC (~10ms) | filesystem (~10s) |
| Adversarial-tolerant | partial (signatures) | strong (UNIX perms) | weak (asserted name) | weak |

**Recommendation:**
- Both parties on same host already → single shared host
- Two parties, mutual trust, want simplest cross-machine → **git-as-wire**
- Two parties, want tight RPC + leases on top of git → mcp_agent_mail + git-as-wire as backup
- Adversarial → wait for v3 HMAC extension

---

## Test it locally

A two-machine simulation using two local clones:

```bash
cd /path/to/inter-agent-deaddrop/examples/git-as-wire/test
./test-roundtrip.sh
```

The test:
1. Creates a bare git repo (simulating GitHub)
2. Clones twice (agent_a, agent_b)
3. Each side appends a heartbeat
4. Daemons push to bare repo, fetch peer's commits
5. Verifies both sides see both messages within 2 heartbeats
