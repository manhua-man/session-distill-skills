#!/usr/bin/env python3
"""Hermes Agent session distiller (SQLite state.db → Deep Distill packets)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

from distill_core.adapter_common import (
    bundle_lossless_session,
    index_session_entry,
    messages_to_turns,
    validate_distilled_note,
)
from distill_core.queue import BUNDLEABLE_STATUSES

TEXT_LIMIT = int(os.environ.get("HERMES_DISTILL_TEXT_LIMIT", "32000"))
ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped", "pending_redistill"}
USER_QUERY_REGEX = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL | re.IGNORECASE)


def resolve_hermes_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"])
    local = Path.home() / "AppData" / "Local" / "hermes"
    if local.exists():
        return local
    return Path.home() / ".hermes"


HERMES_HOME = resolve_hermes_home()
DISTILL_DIR = Path(os.environ.get("HERMES_DISTILL_DIR", HERMES_HOME / "session-distill"))
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def db_path() -> Path:
    override = os.environ.get("HERMES_STATE_DB")
    if override:
        return Path(override)
    for candidate in (HERMES_HOME / "state.db", Path.home() / ".hermes" / "state.db"):
        if candidate.exists():
            return candidate
    return HERMES_HOME / "state.db"


def ensure_dirs() -> None:
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text(
            "# Hermes Session Knowledge Base\n\nPromote only verified, reusable lessons here.\n",
            encoding="utf-8",
        )
    if not MANIFEST_FILE.exists():
        save_manifest({"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []})


def load_manifest() -> dict[str, Any]:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []}


def save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def connect_db() -> sqlite3.Connection:
    path = db_path()
    if not path.exists():
        raise FileNotFoundError(f"Hermes state.db not found: {path}")
    return sqlite3.connect(path)


def fetch_sessions(project_filter: str = "") -> list[dict[str, Any]]:
    conn = connect_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, title, source, started_at, ended_at, message_count, cwd, git_repo_root, model
        FROM sessions
        WHERE COALESCE(archived, 0) = 0
        ORDER BY started_at DESC
        """
    ).fetchall()
    conn.close()
    flt = project_filter.lower().replace("\\", "/")
    sessions: list[dict[str, Any]] = []
    for row in rows:
        project = row["git_repo_root"] or row["cwd"] or ""
        if flt and flt not in project.lower().replace("\\", "/"):
            continue
        sessions.append(
            {
                "session_id": row["id"],
                "thread_name": row["title"] or row["id"],
                "project_path": project,
                "timestamp": datetime.fromtimestamp(float(row["started_at"]), timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
                if row["started_at"]
                else "",
                "source": row["source"] or "cli",
                "message_count": int(row["message_count"] or 0),
                "model": row["model"] or "",
                "size_bytes": int(row["message_count"] or 0),
                "last_write_time": datetime.fromtimestamp(
                    float(row["ended_at"] or row["started_at"] or 0), timezone.utc
                )
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return sessions


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fetch_messages(session_id: str, *, clip_content: bool = True) -> list[dict[str, str]]:
    conn = connect_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT role, content, tool_name
        FROM messages
        WHERE session_id = ? AND COALESCE(active, 1) = 1
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    conn.close()
    messages: list[dict[str, str]] = []
    for row in rows:
        role = (row["role"] or "").strip()
        content = (row["content"] or "").strip()
        if not content and role != "tool":
            continue
        if role == "tool" and row["tool_name"]:
            content = f"[tool:{row['tool_name']}] {content}"
        if clip_content:
            content = content[:TEXT_LIMIT]
        messages.append({"role": role, "content": content, "tool_name": row["tool_name"] or ""})
    return messages


def clip(text: str, limit: int = TEXT_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: limit - 3] + "...", True


def generate_packet(session: dict[str, Any], out_path: Path) -> dict[str, Any]:
    messages = fetch_messages(session["session_id"])
    user_blocks: list[str] = []
    assistant_blocks: list[str] = []
    clipped = 0
    for msg in messages:
        text, was_clipped = clip(msg["content"])
        if was_clipped:
            clipped += 1
        if msg["role"] == "user":
            user_blocks.append(text)
        elif msg["role"] == "assistant":
            assistant_blocks.append(text)

    final_answers = assistant_blocks[-3:] if assistant_blocks else []
    warnings: list[str] = []
    if clipped:
        warnings.append(f"{clipped} message block(s) clipped at {TEXT_LIMIT} chars.")
    if not messages:
        warnings.append("No messages found in SQLite store.")

    lines = [
        f"# Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        f"- Platform: hermes",
        f"- Title: {session.get('thread_name', '')}",
        f"- Project: {session.get('project_path', '')}",
        f"- Source: {session.get('source', '')}",
        f"- Model: {session.get('model', '')}",
        f"- Messages: {len(messages)}",
        "",
        "## Packet Audit",
        f"- Coverage: `{'partial' if warnings else 'high'}`",
        f"- User blocks: {len(user_blocks)}",
        f"- Assistant blocks: {len(assistant_blocks)}",
    ]
    if warnings:
        lines.extend(["", "### Audit Warnings", ""])
        lines.extend(f"- {w}" for w in warnings)

    if user_blocks:
        lines.extend(["", "## User Requests", ""])
        for block in user_blocks[-8:]:
            lines.extend(["```text", block, "```", ""])

    if final_answers:
        lines.extend(["", "### Final Answers", ""])
        lines.extend(["```text", "\n\n".join(final_answers), "```", ""])

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"coverage": "partial" if warnings else "high", "warnings": warnings}


def cmd_index(project_filter: str = "") -> int:
    ensure_dirs()
    print("==> Index: scanning Hermes SQLite sessions")
    manifest = load_manifest()
    previous = {s["session_id"]: s for s in manifest.get("sessions", [])}
    refreshed: list[dict[str, Any]] = []
    new_count = 0
    for meta in fetch_sessions(project_filter=project_filter):
        sid = meta["session_id"]
        old = previous.get(sid, {})
        if not old:
            new_count += 1
            print(f"  + {sid} [{meta.get('project_path', '')}]")
        entry = index_session_entry(
            old,
            session_id=sid,
            source_fields={
                "size_bytes": meta.get("size_bytes"),
                "last_write_time": meta.get("last_write_time"),
                "message_count": meta.get("message_count"),
            },
            base_meta=meta,
        )
        refreshed.append(entry)
    manifest["updated_at"] = now_iso()
    manifest["input_dirs"] = [str(db_path())]
    manifest["output_dir"] = str(DISTILL_DIR)
    manifest["sessions"] = refreshed
    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions")
    return 0


def cmd_bundle(next_count: int = 1, force: bool = False, session_ids: list[str] | None = None) -> int:
    ensure_dirs()
    manifest = load_manifest()
    wanted = set(session_ids or [])
    candidates = [
        s
        for s in manifest.get("sessions", [])
        if s.get("status") in BUNDLEABLE_STATUSES
        and (not wanted or s["session_id"] in wanted or force)
    ]
    if session_ids:
        selected = candidates
    else:
        selected = candidates[:next_count]
    if not selected:
        print("No sessions to bundle")
        return 0
    print(f"==> Bundle: generating {len(selected)} packet(s)")
    for session in selected:
        sid = session["session_id"]
        packet_path = PACKETS_DIR / f"{sid}.md"
        print(f"  -> {sid[:16]}... {session.get('thread_name', '')[:50]}")
        messages = fetch_messages(sid, clip_content=False)
        turns = messages_to_turns(messages, turn_id_prefix=sid[:8])
        bundle_lossless_session(
            distill_dir=DISTILL_DIR,
            session=session,
            platform="hermes",
            turns=turns,
            source_fingerprint={
                "size_bytes": session.get("size_bytes"),
                "last_write_time": session.get("last_write_time"),
                "message_count": session.get("message_count"),
            },
            packet_path=packet_path,
            read_text=read_text,
            parse_counters={"messages": len(messages), "turns": len(turns)},
        )
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print("==> Bundle done")
    return 0


def cmd_status() -> int:
    ensure_dirs()
    manifest = load_manifest()
    counts: dict[str, int] = {}
    for s in manifest.get("sessions", []):
        counts[s.get("status", "new")] = counts.get(s.get("status", "new"), 0) + 1
    print(f"Hermes distill dir: {DISTILL_DIR}")
    print(f"State DB: {db_path()}")
    for status in ("new", "bundled", "pending_redistill", "distilled", "skipped"):
        if counts.get(status):
            print(f"  {status}: {counts[status]}")
    return 0


def cmd_mark(session_id: str, status: str, force: bool = False) -> int:
    if status == "distilled" and not force:
        errors = validate_distilled_note(
            session_id=session_id,
            packets_dir=PACKETS_DIR,
            distilled_dir=DISTILLED_DIR,
            read_text=read_text,
        )
        if errors:
            print("Cannot mark distilled:")
            for error in errors:
                print(f"  - {error}")
            return 1
    manifest = load_manifest()
    for session in manifest.get("sessions", []):
        if session["session_id"] == session_id:
            session["status"] = status
            if status == "distilled":
                session["distilled_path"] = str(DISTILLED_DIR / f"{session_id}.md")
                session["last_distilled_revision_id"] = session.get("current_revision_id") or session.get("last_distilled_revision_id")
            manifest["updated_at"] = now_iso()
            save_manifest(manifest)
            print(f"Marked {session_id} as {status}")
            return 0
    print(f"Session not found: {session_id}")
    return 1


def cmd_self_test() -> int:
    import unittest

    test_dir = Path(__file__).resolve().parents[1] / "tests"
    if not test_dir.exists():
        print(f"No tests directory: {test_dir}")
        return 0
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes session distiller")
    parser.add_argument("command", nargs="?", default="status")
    parser.add_argument("arg", nargs="?", default="")
    parser.add_argument("status", nargs="?", default="")
    parser.add_argument("--next", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--project", default="servers")
    parser.add_argument("--session-ids", nargs="*", default=[])
    args = parser.parse_args()

    if args.command == "index":
        return cmd_index(project_filter=args.project)
    if args.command == "run":
        cmd_index(project_filter=args.project)
        return cmd_bundle(next_count=args.next, force=args.force)
    if args.command == "bundle":
        return cmd_bundle(next_count=args.next, force=args.force, session_ids=args.session_ids)
    if args.command == "status":
        return cmd_status()
    if args.command == "mark" and args.arg and args.status:
        return cmd_mark(args.arg, args.status, force=args.force)
    if args.command == "self-test":
        return cmd_self_test()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
