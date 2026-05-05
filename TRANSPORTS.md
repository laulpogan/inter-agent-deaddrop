# Cross-machine Transports

The protocol assumes a shared filesystem. For two agents on different machines, you need a transport that preserves the protocol's invariants. This doc compares the options.

## Trade-off matrix

| Transport | Setup | Online req. | Append-atomic | Audit | Notes |
|---|---|---|---|---|---|
| **Single shared host (recommended)** | OS users + setgid group | both can access host | OS-level (POSIX `O_APPEND`) | filesystem mtime + git | Strongest sandboxing. Best ergonomics for n=2. |
| **Shared private git repo** | repo + push/pull access | not for write; sync delayed | commits are atomic | `git log` is the audit | Conflicts on concurrent pushes need merge policy |
| **NFS / SSHFS over Tailscale** | mesh VPN + share | both must be online for sync | NFS atomicity caveats | mtime + git | NFS over WAN is finicky; SSHFS hangs on disconnect |
| **Object storage (S3/R2/GCS) drop zone** | bucket + IAM | not for write; sync delayed | per-object PUT atomic | object versioning | Cloud dependency; latency higher |
| **Custom MCP RPC + retry queue** | server per side | online for delivery | application-level | application logs | Reinvents what the dead-drop already gives |

## Recommendation: single shared host

For a pair of cooperating operators, the simplest and most secure transport is a single Linux host where both have scoped UNIX accounts in a shared group, with the project dir setgid'd to that group.

```
/home/operator/Source/shared-project/
├── _coordination/                # group=plotter, setgid
│   ├── PROTOCOL.md
│   ├── tiers.json
│   ├── a_to_b.jsonl
│   ├── b_to_a.jsonl
│   ├── decisions.jsonl
│   └── incident_log.jsonl
└── (project files)
```

Provisioning:

```bash
sudo bash -c '
  groupadd -f shared
  useradd -m -s /bin/bash agent_b_user
  usermod -aG shared agent_a_user agent_b_user

  chgrp -R shared /home/operator/Source/shared-project
  chmod -R g+rwX /home/operator/Source/shared-project
  find /home/operator/Source/shared-project -type d -exec chmod g+s {} +

  setfacl -m u:agent_b_user:--x /home/operator
'
```

This gives each agent's user account:
- Full rw on the project directory
- No access to other home dirs
- No sudo
- Identity asserted by `whoami` at the OS level

Coordinate via `_coordination/` as if it were two repos on one machine. The protocol works unchanged.

For remote access, add Tailscale; for SSH constraints (no port forwarding, no agent forwarding), use `Match User` in `sshd_config`. A worked example of the operator-provisioning block is in [`examples/operator-provisioning.sh`](examples/operator-provisioning.sh).

## Recommendation: shared private git repo (cross-org)

**Status:** reference implementation in [`examples/git-as-wire/`](examples/git-as-wire/). Local two-clone integration test passes. Production validation across two real machines pending.

If the agents truly cannot share a host, a private git repo is the next-best transport:

```
agent_a_repo                       agent_b_repo
   │                                     │
   │   git push (after each append)      │
   │ ────────────────►   shared origin   ◄──── git push
   │                          │
   │ ◄──── git fetch (every heartbeat) ───────►
   │                                     │
```

Properties:
- Append = local file write + commit + push
- Read = git fetch + tail
- Audit = `git log` over JSONL files (each commit shows a single message)
- Conflict = git merge; should never happen on append-only files unless both push simultaneously

**Concurrent-push policy:** if both agents push at the same time, one will fail with non-fast-forward. Resolution: `git pull --rebase`, push again. The append-only invariant means no merge conflicts on the JSONL contents — only on the commit ordering. The reference daemon (`examples/git-as-wire/wire-daemon.py`) handles this automatically with up to 3 retries.

**Offline tolerance:** an agent can append locally, push when connectivity returns. The other side fetches on its next heartbeat.

**Privacy:** use a private GitHub/Gitea repo. Anyone with read access sees full coordination history.

## Recommendation against: NFS over WAN

NFS works well over LAN with a stable network. Over WAN (even via Tailscale), NFS exhibits:
- Hangs on transient connectivity loss
- Cache coherency issues across long round-trips
- Lockfile staleness when one side reboots

If you must use NFS, fence it with retries and treat the share as best-effort. SSHFS has the same issues plus client-side hang on disconnect.

## Recommendation against: custom MCP RPC

Building an MCP server per side, plus a retry queue, plus a delivery confirmation, plus a deduplication cache — you've reinvented the dead-drop with extra steps. The whole point of inter-agent-deaddrop is that the filesystem IS the wire. RPC is the wrong primitive for "talk over time."

The one exception: you have a working MCP server already (e.g., `mcp_agent_mail`) that supports your invariants. Then use it as the transport and treat the JSONL files as a secondary archive.

## Operator hardening per transport

Whatever transport you pick:

1. **Encrypt at rest** if the coordination history is sensitive
2. **Per-message HMAC signing** if either agent might be adversarial (v3 extension)
3. **Backup the `_coordination/` dir** independently of the rest of the project
4. **Log retention policy** — when do archived JSONL files get deleted? Both parties should agree
5. **Revocation drill** — practice the "kick the other agent off" procedure before you need it
