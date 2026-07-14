#!/usr/bin/env python3
"""Codex Deep Distill batch runner (Grok paradigm)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

os.environ.setdefault("CODEX_DISTILL_TEXT_LIMIT", "32000")
os.environ.setdefault("CODEX_DISTILL_OUTPUT_LIMIT", "32000")
os.environ.setdefault("CODEX_DISTILL_OUTPUT_LINE_LIMIT", "120")

from deep_distill_runner import build_arg_parser, load_adapter, run_deep_batch

SCRIPT = _BIN_DIR / "session-distill.py"
mod = load_adapter(SCRIPT, "codex_sd")

QUEUE_FILE = mod.DISTILL_DIR / "servers-deep-queue.md"
ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"
REPO_KB = Path("E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md")


def is_servers_session(session: dict) -> bool:
    cwd = (session.get("cwd") or "").lower().replace("/", "\\")
    return "servers" in cwd and "servers-wt" not in cwd


def load_servers_sessions(*, pending_only: bool = True) -> list[dict]:
    manifest = mod.load_manifest()
    sessions = [s for s in manifest.get("sessions", []) if is_servers_session(s)]
    if pending_only:
        sessions = [s for s in sessions if s.get("status") in {"new", "bundled", "pending_redistill"}]
    return sorted(sessions, key=lambda s: s.get("timestamp") or "")


def write_queue_file(*, batch: list[dict], offset: int, batch_size: int = 3) -> None:
    manifest = mod.load_manifest()
    all_servers = [s for s in manifest.get("sessions", []) if is_servers_session(s)]
    counts = {
        "new": sum(1 for s in all_servers if s.get("status") == "new"),
        "bundled": sum(1 for s in all_servers if s.get("status") == "bundled"),
        "pending_redistill": sum(1 for s in all_servers if s.get("status") == "pending_redistill"),
        "distilled": sum(1 for s in all_servers if s.get("status") == "distilled"),
        "skipped": sum(1 for s in all_servers if s.get("status") == "skipped"),
    }
    pending = [s for s in all_servers if s.get("status") in {"new", "bundled", "pending_redistill"}]
    done = counts["distilled"] + counts["skipped"]
    total = len(all_servers)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Servers Deep Distillation Queue (Codex)",
        "",
        f"**Progress: {done}/{total}** (distilled={counts['distilled']}, skipped={counts['skipped']}) | pending={len(pending)}",
        f"Updated: {stamp}",
        "",
        f"KB: `{REPO_KB}`",
        "",
        "## Next batch",
        "",
        f"- offset: `{offset}`",
        f"- batch-size: `{batch_size}`",
        "",
        "## Pending servers sessions (chronological)",
        "",
    ]
    for index, session in enumerate(pending[:30]):
        marker = "→" if offset <= index < offset + batch_size else "-"
        title = (session.get("thread_name") or "")[:60]
        lines.append(f"{marker} `{session['session_id']}` | {title}")
    if len(pending) > 30:
        lines.append(f"- ... and {len(pending) - 30} more")
    lines.append("")
    QUEUE_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = build_arg_parser("Codex deep distill batch runner")
    parser.set_defaults(reindex=True)
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
        write_queue_file(batch=[], offset=args.offset, batch_size=args.batch_size)
        print("No sessions in batch")
        print(f"Queue: {QUEUE_FILE}")
        return 1

    result = run_deep_batch(
        mod=mod,
        platform="codex",
        batch=batch,
        answer_dir=ANSWER_DIR,
        check_work_dir=CHECK_WORK_DIR,
        packet_prefix="",
        project_path_key="cwd",
        offset=args.offset,
        force_bundle=args.force_bundle,
        force_extract=args.force_extract,
        queue_file=QUEUE_FILE,
        queue_writer=lambda **kwargs: write_queue_file(
            batch=kwargs.get("batch", batch),
            offset=args.offset,
            batch_size=args.batch_size,
        ),
    )
    print(f"==> Repo KB: {REPO_KB}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
