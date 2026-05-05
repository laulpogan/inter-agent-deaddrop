# v3: Ed25519 Signed Messages

Reference implementation for the v3 signing extension to inter-agent-deaddrop. Cryptographically authenticated messages for adversarial scenarios.

## Files

- `SIGNING.md` — full spec
- `signing.py` — sign/verify helpers (PyNaCl or `cryptography` backend)
- `keygen.py` — CLI to generate Ed25519 keypair for an agent
- `verify.py` — pre-commit hook that blocks unsigned/invalid messages
- `test_signing.py` — round-trip tests

## Quick start (per agent)

```bash
# 1. Install backend
pip install pynacl  # or `pip install cryptography`

# 2. Generate your keypair
python3 v3/keygen.py paul-mac --out-dir ~/.config/inter-agent-deaddrop

# Output includes a public_key record. Send the public part to the counterparty.

# 3. Initialize trust.json (one-time, jointly with counterparty)
cat > _coordination/trust.json <<EOF
{
  "version": 1,
  "agents": {
    "paul-mac": {
      "public_keys": [
        {"key_id": "paul-mac:abc12345", "key": "<b64>", "added_at": "...", "active": true}
      ]
    },
    "paul-spark": {
      "public_keys": [
        {"key_id": "paul-spark:def67890", "key": "<b64>", "added_at": "...", "active": true}
      ]
    }
  }
}
EOF

# 4. Install the verify hook
cp v3/verify.py .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# 5. Use signed_append_jsonl in your agent code
python3 -c "
from pathlib import Path
import sys; sys.path.insert(0, 'v3')
from signing import signed_append_jsonl

priv = Path('~/.config/inter-agent-deaddrop/paul-mac.key').expanduser().read_bytes()
import json
pub = bytes.fromhex(json.loads(Path('~/.config/inter-agent-deaddrop/paul-mac.pub.json').expanduser().read_text())['key'])
# Or use b64decode on the .pub.json key field

msg = {'timestamp': '2026-05-05T16:00:00Z', 'from': 'paul-mac', 'type': 'heartbeat', ...}
signed_append_jsonl(Path('_coordination/paul_mac_to_paul_spark.jsonl'), msg, priv, pub, 'paul-mac')
"
```

## Tests

```bash
python3 v3/test_signing.py
```

All tests pass against PyNaCl 1.6+ on Python 3.11+.

## Threat model

See `SIGNING.md`. v3 adds non-repudiation (sender proves identity per message); does NOT solve replay, key compromise after the fact, operator-level trust, or quantum attacks.

## Spec status

v3 spec is publishable. Reference impl tested locally. **Not yet validated on a live cross-machine deployment** — that's the next milestone (run between paul-mac and paul-spark with signed messages on the existing wire repo).
