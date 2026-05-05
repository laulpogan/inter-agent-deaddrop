"""
Atomic JSONL append helper.

POSIX `O_APPEND` writes are atomic only up to PIPE_BUF (~4KB on macOS, 4KB on
Linux). For agent coordination messages with arbitrary body sizes, use this
helper to ensure no torn writes.

Locking strategy:
- fcntl advisory lock on the target file
- O_APPEND + write + flush + fsync inside the locked critical section
- Lock is released even on exception

This works for multi-process append (e.g., agent session + retry daemon writing
to the same outbox). Cross-machine append correctness depends on the underlying
filesystem (NFS lock semantics differ; check before relying).
"""

import fcntl
import json
import os
from pathlib import Path
from typing import Any, Mapping


def safe_append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    """
    Atomically append `record` as a JSON line to `path`.

    Args:
        path: target JSONL file (will be created if missing)
        record: dict-like object, must be JSON-serializable

    Raises:
        TypeError if record is not JSON-serializable
        OSError on filesystem failure
    """
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    encoded = line.encode("utf-8")

    # Open with O_APPEND so kernel handles concurrent appends atomically up to
    # PIPE_BUF; advisory lock ensures atomicity for larger writes.
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(path, flags, 0o664)

    try:
        # Exclusive lock; blocks if another writer holds it.
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def read_last_n(path: Path, n: int) -> list[dict[str, Any]]:
    """
    Read the last `n` JSON lines from `path` as parsed dicts.

    Returns empty list if file missing. Skips malformed lines with a stderr
    warning rather than raising.
    """
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    for raw in lines[-n:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError as e:
            print(f"WARN: skipping malformed line in {path}: {e}", flush=True)
    return out


if __name__ == "__main__":
    # smoke test
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        p = Path(f.name)

    safe_append_jsonl(p, {"timestamp": "2026-05-04T00:00:00Z", "from": "a", "type": "heartbeat", "body": "test"})
    safe_append_jsonl(p, {"timestamp": "2026-05-04T00:01:30Z", "from": "b", "type": "ack", "body": "got it"})

    msgs = read_last_n(p, 5)
    assert len(msgs) == 2
    assert msgs[0]["from"] == "a"
    assert msgs[1]["from"] == "b"
    print("OK")
    p.unlink()
