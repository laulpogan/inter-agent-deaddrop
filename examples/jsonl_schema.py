"""
JSONL schema validator — runs as pre-commit hook.

Validates every line in `_coordination/*.jsonl` against the inter-agent-deaddrop
v2.0 schema. Blocks commits that violate the eight invariants.

Override (emergency only):
    ALLOW_HOTPATH=1 git commit ...

Install as a pre-commit hook:
    cp examples/jsonl_schema.py .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

VALID_TYPES = {
    "ship",
    "request",
    "warning",
    "feedback",
    "incident",
    "ack",
    "proposal",
    "heartbeat",
    "correction",
    "shutdown",
}

REQUIRED_FIELDS = {"timestamp", "from", "type", "subject", "body", "correlation_id"}


def validate_line(line_no: int, line: str, path: Path) -> list[str]:
    errors: list[str] = []
    line = line.strip()
    if not line:
        return errors  # blank line ok

    try:
        rec = json.loads(line)
    except json.JSONDecodeError as e:
        return [f"{path}:{line_no}: invalid JSON: {e}"]

    if not isinstance(rec, dict):
        return [f"{path}:{line_no}: not an object"]

    missing = REQUIRED_FIELDS - rec.keys()
    if missing:
        errors.append(f"{path}:{line_no}: missing required fields: {sorted(missing)}")

    msg_type = rec.get("type")
    if msg_type not in VALID_TYPES:
        errors.append(f"{path}:{line_no}: invalid type {msg_type!r}")

    if msg_type == "proposal" and not rec.get("ack_required"):
        errors.append(f"{path}:{line_no}: proposal must have ack_required=true")

    if msg_type == "ack":
        # ack must reference a parent — correlation_id != own timestamp
        if rec.get("correlation_id") == rec.get("timestamp"):
            errors.append(
                f"{path}:{line_no}: ack must point at parent, not self "
                f"(correlation_id == timestamp)"
            )

    return errors


def staged_jsonl_files() -> list[Path]:
    """Return JSONL files in `_coordination/` that are staged for commit."""
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


def is_rewrite_attempt(path: Path) -> bool:
    """
    Detect if the staged change rewrites past lines (non-append).

    True if any line beyond the prior version is REMOVED or MODIFIED.
    The append-only invariant allows only ADDITIONS at the end of file.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    diff = result.stdout
    # Any line starting with `-` (removed) other than the file header indicates
    # a rewrite. Hunk headers `@@ ... @@` and `--- a/file` are diff metadata.
    for line in diff.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("-"):
            return True
    return False


def main() -> int:
    if os.environ.get("ALLOW_HOTPATH") == "1":
        print("WARN: pre-commit hook bypassed via ALLOW_HOTPATH=1", file=sys.stderr)
        return 0

    files = staged_jsonl_files()
    errors: list[str] = []

    for f in files:
        if is_rewrite_attempt(f):
            errors.append(f"{f}: append-only invariant violated (line removed or modified)")
            continue

        with f.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                errors.extend(validate_line(i, line, f))

    if errors:
        print("inter-agent-deaddrop schema violations:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\nCommit blocked. Fix above OR set ALLOW_HOTPATH=1 for emergency override.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
