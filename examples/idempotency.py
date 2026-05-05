"""
Idempotency cache for inter-agent-deaddrop.

Closes the replay-attack gap that v3 signing alone leaves open: a v3-signed
message remains cryptographically valid forever, so a malicious wire-host
could re-deliver an old message and the receiver would re-process it.

Pattern: each agent maintains a cache of `correlation_id`s it has already
processed. New messages with a `correlation_id` already in the cache are
treated as no-ops (logged as `incident: replay_detected` if you want to be
loud about it; silently dropped otherwise).

Cache shape:
    {<agent>: set(<correlation_id>)}

Persistence: JSONL append-only file at `<agent>_seen.jsonl`. One line per
processed correlation_id. On startup, read the file into the set; on each
message read, append to the file + add to the set.

Bounded growth: archive yearly with the rest of `_coordination/archive/`.
Use a TTL window if you want bounded memory: only keep correlation_ids
within last N days.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


class IdempotencyCache:
    """Per-agent cache of seen correlation_ids."""

    def __init__(self, path: Path, ttl_days: float | None = None):
        self.path = Path(path)
        self.ttl = timedelta(days=ttl_days) if ttl_days else None
        self._seen: dict[str, str] = {}  # correlation_id -> first-seen ISO timestamp
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        cutoff = (datetime.now(timezone.utc) - self.ttl) if self.ttl else None
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = rec.get("correlation_id")
                ts = rec.get("seen_at")
                if not cid:
                    continue
                if cutoff and ts:
                    try:
                        seen_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if seen_dt < cutoff:
                            continue
                    except ValueError:
                        pass
                self._seen[cid] = ts or ""

    def has_seen(self, correlation_id: str) -> bool:
        return correlation_id in self._seen

    def mark_seen(self, correlation_id: str) -> bool:
        """
        Mark correlation_id as seen. Returns True if it was new (i.e., this is
        the first time we've seen it) or False if it was a replay.
        """
        if correlation_id in self._seen:
            return False
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seen[correlation_id] = ts
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"correlation_id": correlation_id, "seen_at": ts}) + "\n")
        return True

    def filter_new(self, messages: Iterable[dict]) -> list[dict]:
        """Return only messages with new correlation_ids; mark them seen."""
        out = []
        for msg in messages:
            cid = msg.get("correlation_id")
            if not cid:
                continue
            if self.mark_seen(cid):
                out.append(msg)
        return out


if __name__ == "__main__":
    # smoke test
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = Path(f.name)

    try:
        cache = IdempotencyCache(path)

        msg1 = {"correlation_id": "2026-05-05T16:00:00Z", "type": "ship"}
        msg2 = {"correlation_id": "2026-05-05T16:01:00Z", "type": "ack"}
        msg1_replay = {"correlation_id": "2026-05-05T16:00:00Z", "type": "ship"}

        new = cache.filter_new([msg1, msg2, msg1_replay])
        assert len(new) == 2, f"expected 2 new, got {len(new)}"

        # restart: cache should reload from file
        cache2 = IdempotencyCache(path)
        assert cache2.has_seen("2026-05-05T16:00:00Z")
        assert cache2.has_seen("2026-05-05T16:01:00Z")

        # replay still rejected after restart
        assert not cache2.mark_seen("2026-05-05T16:00:00Z")
        assert cache2.mark_seen("2026-05-05T16:02:00Z")  # new

        print("OK idempotency cache")
    finally:
        path.unlink()
