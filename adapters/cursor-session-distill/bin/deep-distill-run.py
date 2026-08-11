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

ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"
PACKET_PREFIX = "cursor-"


def _session_has_source(mod, sid: str) -> bool:
    """真实源存在性检查：jsonl 目录有文件，或 sqlite composerData 缓存存在。"""
    jdir = mod.CURSOR_JSONL_TRANSCRIPTS_DIR / sid
    if jdir.is_dir() and any(jdir.glob("*.jsonl")):
        return True
    try:
        conn = mod.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM cursorDiskKV WHERE key=?", (f"composerData:{sid}",))
            return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False


def load_project_sessions(*, project: str, include_processed: bool = False) -> list[dict]:
    """无状态选批：按 --project 过滤 workspace，跳过无真实源或已有 packet 的会话。

    packet 文件即「已处理」标记（无状态去重）；不依赖 manifest status。
    """
    manifest = mod.load_manifest()
    sessions = [
        s for s in manifest.get("sessions", [])
        if project.lower() in (s.get("workspace") or "").lower()
    ]
    pending: list[dict] = []
    for s in sessions:
        if s.get("source_missing"):
            continue
        sid = s["session_id"]
        if not _session_has_source(mod, sid):
            continue
        packet = mod.PACKETS_DIR / f"{PACKET_PREFIX}{sid}.md"
        if packet.exists() and not include_processed:
            continue
        pending.append(s)
    return sorted(pending, key=lambda s: s.get("created_at") or "")


def main() -> int:
    parser = build_arg_parser("Cursor deep distill batch runner (stateless)")
    args = parser.parse_args()

    if args.reindex:
        mod.cmd_index()

    sessions = load_project_sessions(project=args.project, include_processed=args.include_processed)
    if args.session_ids:
        by_id = {s["session_id"]: s for s in sessions}
        batch = [by_id[sid] for sid in args.session_ids if sid in by_id]
    else:
        batch = sessions[args.offset : args.offset + args.batch_size]

    if not batch:
        print(f"No pending sessions for project '{args.project}'")
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
        queue_file=None,  # 无状态：不再写 servers-deep-queue.md
    )


if __name__ == "__main__":
    raise SystemExit(main())
