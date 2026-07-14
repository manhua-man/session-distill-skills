#!/usr/bin/env python3
"""Claude Code deep distill batch runner."""

from __future__ import annotations

import sys
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

from deep_distill_runner import build_arg_parser, load_adapter, run_deep_batch

SCRIPT = _BIN_DIR / "session-distill.py"
mod = load_adapter(SCRIPT, "claude_sd")

QUEUE_FILE = mod.DISTILL_DIR / "servers-deep-queue.md"
ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"
REPO_KB = Path("E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md")


def find_servers_project() -> Path | None:
    for candidate in sorted(mod.PROJECTS_DIR.glob("*servers*")):
        if candidate.is_dir():
            return candidate
    return mod.find_project_path("servers")


def is_servers_session(session: dict) -> bool:
    path = (session.get("project_path") or session.get("file_path") or "").lower().replace("/", "\\")
    return "servers" in path and "servers-wt" not in path


def load_servers_sessions(*, pending_only: bool = True) -> list[dict]:
    manifest = mod.load_manifest()
    sessions = [s for s in manifest.get("sessions", []) if is_servers_session(s)]
    if pending_only:
        sessions = [s for s in sessions if s.get("status") in {"new", "bundled", "pending_redistill"}]
    return sorted(sessions, key=lambda s: s.get("mtime_iso") or "")


def main() -> int:
    parser = build_arg_parser("Claude Code deep distill batch runner")
    parser.set_defaults(reindex=True)
    args = parser.parse_args()

    project_path = find_servers_project()
    if args.reindex:
        if not project_path:
            print("Error: cannot find servers project under ~/.claude/projects")
            return 1
        mod.cmd_index(project_path)

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

    if project_path is None:
        project_path = find_servers_project()

    original_bundle = mod.cmd_bundle

    def bundle_wrapper(*, next_count=1, force=False, session_ids=None, **_kwargs):
        return original_bundle(project_path, next_count=next_count, force=force, session_ids=session_ids)

    mod.cmd_bundle = bundle_wrapper

    result = run_deep_batch(
        mod=mod,
        platform="claude",
        batch=batch,
        answer_dir=ANSWER_DIR,
        check_work_dir=CHECK_WORK_DIR,
        packet_prefix="",
        project_path_key="project_path",
        offset=args.offset,
        force_bundle=args.force_bundle,
        force_extract=args.force_extract,
        queue_file=QUEUE_FILE,
    )
    print(f"==> Repo KB: {REPO_KB}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
