#!/usr/bin/env python3
"""Cursor Deep Distill batch runner (Grok paradigm)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

from deep_distill_runner import build_arg_parser, load_adapter, run_deep_batch

SCRIPT = _BIN_DIR / "cursor-session-distill.py"
mod = load_adapter(SCRIPT, "cursor_sd")

QUEUE_FILE = mod.DISTILL_DIR / "servers-deep-queue.md"
ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"
PACKET_PREFIX = "cursor-"


def load_servers_sessions(*, pending_only: bool = True) -> list[dict]:
    manifest = mod.load_manifest()
    sessions = [
        s for s in manifest.get("sessions", [])
        if "servers" in (s.get("workspace") or "").lower()
    ]
    if pending_only:
        sessions = [s for s in sessions if s.get("status") in {"new", "bundled", "pending_redistill"}]
    return sorted(sessions, key=lambda s: s.get("created_at") or "")


def main() -> int:
    parser = build_arg_parser("Cursor deep distill batch runner")
    args = parser.parse_args()

    if args.reindex:
        mod.cmd_index()

    sessions = load_servers_sessions(pending_only=not args.include_processed)
    if args.session_ids:
        by_id = {s["session_id"]: s for s in sessions}
        batch = [by_id[sid] for sid in args.session_ids if sid in by_id]
    else:
        batch = sessions[args.offset : args.offset + args.batch_size]

    if not batch:
        print("No sessions in batch")
        print(f"Queue: {QUEUE_FILE}")
        return 1

    return run_deep_batch(
        mod=mod,
        platform="cursor",
        batch=batch,
        answer_dir=ANSWER_DIR,
        check_work_dir=CHECK_WORK_DIR,
        packet_prefix=PACKET_PREFIX,
        project_path_key="workspace",
        offset=args.offset,
        force_bundle=args.force_bundle,
        force_extract=args.force_extract,
        queue_file=QUEUE_FILE,
    )


if __name__ == "__main__":
    raise SystemExit(main())
