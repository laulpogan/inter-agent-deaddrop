#!/usr/bin/env python3
"""
Pre-commit hook: verify v3 signatures on every new line in _coordination/*.jsonl.

Looks up trust list at _coordination/trust.json. Blocks the commit if any line
fails signature verification. Override with ALLOW_HOTPATH=1 (emergency only).

Install:
    cp v3/verify.py .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit

Or compose with the v2 schema validator:
    .git/hooks/pre-commit calls both verify.py and jsonl_schema.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signing import verify_message


def staged_jsonl_files() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        p = Path(line)
        if p.match("_coordination/*.jsonl") or p.match("_coordination/archive/*/*.jsonl"):
            paths.append(p)
    return paths


def staged_added_lines(path: Path) -> list[tuple[int, str]]:
    """Return [(line_no, line)] for lines added in the staged diff."""
    result = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = []
    line_no = 0
    for raw in result.stdout.splitlines():
        if raw.startswith("@@"):
            # @@ -a,b +c,d @@   -> c is the new file's starting line
            try:
                _, _, new = raw.split(" ", 3)[:3]
                line_no = int(new.lstrip("+").split(",")[0]) - 1
            except (ValueError, IndexError):
                continue
        elif raw.startswith("+++") or raw.startswith("---"):
            continue
        elif raw.startswith("+"):
            line_no += 1
            lines.append((line_no, raw[1:]))
        elif raw.startswith(" "):
            line_no += 1
    return lines


def load_trust(repo_root: Path) -> dict:
    trust_path = repo_root / "_coordination" / "trust.json"
    if not trust_path.exists():
        return {}
    return json.loads(trust_path.read_text())


def main() -> int:
    if os.environ.get("ALLOW_HOTPATH") == "1":
        print("WARN: pre-commit hook bypassed via ALLOW_HOTPATH=1", file=sys.stderr)
        return 0

    repo = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True
    ).stdout.strip())
    trust = load_trust(repo)
    if not trust:
        print("WARN: _coordination/trust.json missing — skipping signature verification", file=sys.stderr)
        return 0

    files = staged_jsonl_files()
    errors: list[str] = []

    for f in files:
        for line_no, raw in staged_added_lines(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"{f}:{line_no}: invalid JSON: {e}")
                continue

            ok, reason = verify_message(msg, trust)
            if not ok:
                errors.append(f"{f}:{line_no}: signature invalid: {reason}")

    if errors:
        print("v3 signature verification failures:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print("\nCommit blocked. Fix above OR set ALLOW_HOTPATH=1 for emergency override.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
