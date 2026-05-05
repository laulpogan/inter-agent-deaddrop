#!/usr/bin/env python3
"""
Wire daemon for git-as-wire transport.

Watches the local _coordination/ dir for outbound JSONL appends, commits +
pushes them to origin. Polls origin at heartbeat cadence, fetches + rebases,
notifies on new inbound messages.

Usage:
    python3 wire-daemon.py <wire-repo-path> [--config <path>] [--once]

Config file `<wire-repo-path>/.wire-config.json` shape:

    {
      "agent": "agent_a",
      "outbound_file": "_coordination/a_to_b.jsonl",
      "inbound_file": "_coordination/b_to_a.jsonl",
      "heartbeat_cadence_sec": 90,
      "remote": "origin",
      "branch": "main"
    }

State file `<wire-repo-path>/.wire-state.json` is daemon-managed:
    - last_pushed_local_sha
    - last_seen_remote_sha
    - last_inbound_line_count
    - last_heartbeat_ts

Exit codes:
    0  clean shutdown (--once mode after one successful tick)
    1  config error
    2  git error not auto-recoverable (push rejected after 3 retries)
    3  schema drift incident
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FMT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(format=LOG_FMT, level=logging.INFO, datefmt="%Y-%m-%dT%H:%M:%SZ")
log = logging.getLogger("wire-daemon")


def run(cmd: list[str], cwd: Path, check: bool = True, capture: bool = True) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        capture_output=capture,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nstderr: {proc.stderr}")
    return proc.returncode, proc.stdout, proc.stderr


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"failed to read {path}: {e}; using default")
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def parse_last_msg(jsonl_path: Path, after_line: int) -> list[dict[str, Any]]:
    """Read lines after `after_line` (1-indexed; 0 = read from start) and parse."""
    if not jsonl_path.exists():
        return []
    out = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            if i <= after_line:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError as e:
                log.warning(f"{jsonl_path}:{i}: malformed JSON: {e}")
    return out


def stage_and_commit(repo: Path, files: list[str], message: str, sign: bool) -> bool:
    """Stage given files; commit if anything is staged. Returns True if a commit was made."""
    run(["git", "add", *files], cwd=repo)
    code, out, _ = run(["git", "diff", "--cached", "--quiet"], cwd=repo, check=False)
    if code == 0:
        return False  # nothing staged
    cmd = ["git", "commit"]
    if sign:
        cmd.append("-S")
    cmd += ["-m", message]
    run(cmd, cwd=repo)
    return True


def push_with_retry(repo: Path, remote: str, branch: str, max_attempts: int = 3) -> None:
    for attempt in range(1, max_attempts + 1):
        code, out, err = run(["git", "push", remote, branch], cwd=repo, check=False)
        if code == 0:
            return
        log.warning(f"push attempt {attempt}/{max_attempts} failed: {err.strip()}")
        # try rebase + retry
        run(["git", "fetch", remote, branch], cwd=repo)
        code2, _, err2 = run(["git", "rebase", f"{remote}/{branch}"], cwd=repo, check=False)
        if code2 != 0:
            log.error(f"rebase failed: {err2.strip()} — manual intervention needed")
            run(["git", "rebase", "--abort"], cwd=repo, check=False)
            raise RuntimeError("rebase conflict on append-only files — protocol violation suspected")
        time.sleep(2 ** attempt)
    raise RuntimeError(f"push to {remote}/{branch} failed after {max_attempts} attempts")


def fetch_with_rebase(repo: Path, remote: str, branch: str) -> int:
    """Fetch and rebase. Returns commit count behind before rebase (0 = already up to date)."""
    run(["git", "fetch", remote, branch], cwd=repo)
    code, out, _ = run(["git", "rev-list", "--count", f"HEAD..{remote}/{branch}"], cwd=repo)
    behind = int(out.strip())
    if behind == 0:
        return 0
    code, _, err = run(["git", "rebase", f"{remote}/{branch}"], cwd=repo, check=False)
    if code != 0:
        log.error(f"rebase failed: {err.strip()}")
        run(["git", "rebase", "--abort"], cwd=repo, check=False)
        raise RuntimeError("rebase conflict — protocol violation suspected (append-only broken)")
    return behind


def is_signing_configured(repo: Path) -> bool:
    code, out, _ = run(["git", "config", "--get", "commit.gpgsign"], cwd=repo, check=False)
    return code == 0 and out.strip() == "true"


def tick(repo: Path, cfg: dict, state: dict) -> dict:
    """One iteration of the daemon loop. Returns updated state."""
    outbound = repo / cfg["outbound_file"]
    inbound = repo / cfg["inbound_file"]
    sign = is_signing_configured(repo)
    if not sign:
        log.warning("commit.gpgsign not enabled; commits will be unsigned")

    # 1. Outbound: stage + commit + push if outbound JSONL changed
    code, out, _ = run(["git", "status", "--porcelain", str(cfg["outbound_file"])], cwd=repo)
    if out.strip():
        new_lines = count_lines(outbound)
        old_lines = state.get("last_pushed_outbound_line_count", 0)
        added = new_lines - old_lines
        if added > 0:
            msg = f"msg: {cfg['agent']} appended {added} entries [{utc_iso()}]"
            committed = stage_and_commit(repo, [cfg["outbound_file"]], msg, sign)
            if committed:
                log.info(f"committed: {msg}")
                push_with_retry(repo, cfg["remote"], cfg["branch"])
                log.info("pushed to remote")
                state["last_pushed_outbound_line_count"] = new_lines

    # 2. Inbound: fetch + rebase + read new lines
    behind = fetch_with_rebase(repo, cfg["remote"], cfg["branch"])
    if behind > 0:
        log.info(f"fetched {behind} new commit(s) from remote")
    after_line = state.get("last_read_inbound_line_count", 0)
    new_msgs = parse_last_msg(inbound, after_line)
    if new_msgs:
        log.info(f"new inbound: {len(new_msgs)} message(s)")
        for msg in new_msgs:
            log.info(f"  [{msg.get('type','?')}] {msg.get('subject','')[:70]} (from={msg.get('from','?')})")
        state["last_read_inbound_line_count"] = count_lines(inbound)

    state["last_heartbeat_ts"] = utc_iso()
    return state


def main():
    p = argparse.ArgumentParser()
    p.add_argument("repo", help="path to local clone of wire repo")
    p.add_argument("--config", help="path to .wire-config.json", default=None)
    p.add_argument("--once", action="store_true", help="run one tick and exit")
    args = p.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        log.error(f"{repo} is not a git repo")
        sys.exit(1)

    cfg_path = Path(args.config) if args.config else repo / ".wire-config.json"
    cfg = read_json(cfg_path)
    if not cfg:
        log.error(f"missing or invalid config: {cfg_path}")
        sys.exit(1)

    required = ["agent", "outbound_file", "inbound_file", "heartbeat_cadence_sec", "remote", "branch"]
    missing = [k for k in required if k not in cfg]
    if missing:
        log.error(f"config missing required keys: {missing}")
        sys.exit(1)

    state_path = repo / ".wire-state.json"
    state = read_json(state_path, default={})

    cadence = float(cfg["heartbeat_cadence_sec"])
    log.info(f"daemon starting: agent={cfg['agent']} cadence={cadence}s repo={repo}")

    try:
        while True:
            try:
                state = tick(repo, cfg, state)
                write_json(state_path, state)
            except Exception as e:
                log.error(f"tick failed: {e}")
                # Continue running; transient errors are normal.
                time.sleep(5)
                continue

            if args.once:
                log.info("--once mode: exiting after one tick")
                return

            time.sleep(cadence)
    except KeyboardInterrupt:
        log.info("shutdown requested")


if __name__ == "__main__":
    main()
