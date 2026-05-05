#!/usr/bin/env python3
"""
Generate Ed25519 keypair for an inter-agent-deaddrop v3 agent.

Usage:
    python3 v3/keygen.py <agent-name> [--out-dir ~/.config/inter-agent-deaddrop]

Outputs:
    <out-dir>/<agent-name>.key       (private, mode 600)
    <out-dir>/<agent-name>.pub.json  (public + key_id, ready for trust.json)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signing import b64encode, generate_keypair, make_key_id


def main():
    p = argparse.ArgumentParser()
    p.add_argument("agent", help="agent handle (e.g., agent_a, paul-mac)")
    p.add_argument("--out-dir", default="~/.config/inter-agent-deaddrop", help="key storage directory")
    p.add_argument("--force", action="store_true", help="overwrite existing key files")
    args = p.parse_args()

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)

    priv_path = out_dir / f"{args.agent}.key"
    pub_path = out_dir / f"{args.agent}.pub.json"

    if priv_path.exists() and not args.force:
        print(f"FAIL: {priv_path} exists. use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    priv, pub = generate_keypair()
    key_id = make_key_id(args.agent, pub)

    priv_path.write_bytes(priv)
    priv_path.chmod(0o600)

    pub_record = {
        "agent": args.agent,
        "key_id": key_id,
        "key": b64encode(pub),
        "active": True,
    }
    pub_path.write_text(json.dumps(pub_record, indent=2) + "\n")

    print(f"private key: {priv_path} (mode 600)")
    print(f"public  key: {pub_path}")
    print(f"key_id:      {key_id}")
    print()
    print(f"share the contents of {pub_path} with the counterparty for trust.json:")
    print()
    print(json.dumps(pub_record, indent=2))


if __name__ == "__main__":
    main()
