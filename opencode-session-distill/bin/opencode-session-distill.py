#!/usr/bin/env python3
"""OpenCode session distiller — storage/session + message/part JSON tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unittest
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

ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped", "pending_redistill"}


def resolve_opencode_home() -> Path:
    if os.environ.get("OPENCODE_HOME"):
        return Path(os.environ["OPENCODE_HOME"])
    xdg = Path.home() / ".local" / "share" / "opencode"
    if xdg.exists():
        return xdg
    return Path.home() / ".config" / "opencode"


OPENCODE_HOME = resolve_opencode_home()
STORAGE_DIR = OPENCODE_HOME / "storage"
DISTILL_DIR = Path(os.environ.get("OPENCODE_DISTILL_DIR", OPENCODE_HOME / "session-distill"))
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
RAW_PRUNE_AUDIT_FILE = DISTILL_DIR / "raw-prune-audit.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text("# OpenCode Session Knowledge Base\n\n", encoding="utf-8")
    if not MANIFEST_FILE.exists():
        save_manifest({"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []})


def load_manifest() -> dict[str, Any]:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []}


def save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def discover_sessions(project_filter: str = "") -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    session_root = STORAGE_DIR / "session"
    if not session_root.exists():
        return sessions
    flt = project_filter.lower().replace("\\", "/")
    for project_dir in sorted(session_root.iterdir()):
        if not project_dir.is_dir():
            continue
        for path in sorted(project_dir.glob("*.json")):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            session_id = str(meta.get("id") or path.stem)
            title = str(meta.get("title") or meta.get("name") or session_id)
            project = str(meta.get("directory") or meta.get("cwd") or meta.get("project") or project_dir.name)
            if flt and flt not in project.lower().replace("\\", "/"):
                continue
            stat = path.stat()
            sessions.append(
                {
                    "session_id": session_id,
                    "thread_name": title,
                    "project_path": project,
                    "timestamp": meta.get("time", {}).get("created") if isinstance(meta.get("time"), dict) else "",
                    "file_path": str(path),
                    "size_bytes": stat.st_size,
                    "last_write_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
    return sessions


def load_messages(session_id: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    message_dir = STORAGE_DIR / "message" / session_id
    part_root = STORAGE_DIR / "part"
    if not message_dir.exists():
        return messages
    for msg_path in sorted(message_dir.glob("*.json")):
        try:
            msg = json.loads(msg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        role = str(msg.get("role") or "").lower()
        message_id = str(msg.get("id") or msg_path.stem)
        chunks: list[str] = []
        part_dir = part_root / message_id
        if part_dir.exists():
            for part_path in sorted(part_dir.glob("*.json")):
                try:
                    part = json.loads(part_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for key in ("text", "content", "value"):
                    val = part.get(key)
                    if isinstance(val, str) and val.strip():
                        chunks.append(val.strip())
        body = "\n".join(chunks).strip()
        if not body and role != "tool":
            continue
        messages.append({"role": role, "content": body, "tool_name": str(msg.get("tool") or "")})
    return messages


def source_tree_fields(meta: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint the session metadata, message rows, and referenced part rows."""
    session_path = Path(meta["file_path"])
    paths: list[Path] = [session_path]
    message_dir = STORAGE_DIR / "message" / meta["session_id"]
    message_paths = sorted(message_dir.glob("*.json")) if message_dir.exists() else []
    paths.extend(message_paths)
    for message_path in message_paths:
        try:
            message = json.loads(message_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        message_id = str(message.get("id") or message_path.stem)
        part_dir = STORAGE_DIR / "part" / message_id
        if part_dir.exists():
            paths.extend(sorted(part_dir.glob("*.json")))

    digest = hashlib.sha256()
    included = 0
    for path in sorted(set(paths), key=lambda item: item.as_posix()):
        try:
            relative = path.relative_to(STORAGE_DIR).as_posix().encode("utf-8")
            raw = path.read_bytes()
        except (OSError, ValueError):
            continue
        digest.update(relative)
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
        included += 1
    return {
        "storage_tree_sha256": digest.hexdigest(),
        "storage_tree_file_count": included,
    }


def needs_bundle_refresh(session: dict[str, Any]) -> bool:
    return (
        session.get("bundle_source_fingerprint") != session.get("source_fingerprint")
        or session.get("bundle_source_last_write_time") != session.get("last_write_time")
        or session.get("bundle_source_size_bytes") != session.get("size_bytes")
    )


def cmd_index(project_filter: str = "") -> int:
    ensure_dirs()
    print("==> Index: scanning OpenCode storage")
    if not STORAGE_DIR.exists():
        print(f"  (storage missing: {STORAGE_DIR})")
    manifest = load_manifest()
    previous = {s["session_id"]: s for s in manifest.get("sessions", [])}
    refreshed: list[dict[str, Any]] = []
    new_count = 0
    for meta in discover_sessions(project_filter=project_filter):
        sid = meta["session_id"]
        old = previous.get(sid, {})
        source_fields = source_tree_fields(meta)
        if not old:
            new_count += 1
            print(f"  + {sid} [{meta.get('project_path', '')}]")
        refreshed.append(
            index_session_entry(
                old,
                session_id=sid,
                source_fields=source_fields,
                base_meta={**meta, **source_fields},
            )
        )
    manifest["updated_at"] = now_iso()
    manifest["input_dirs"] = [str(STORAGE_DIR)]
    manifest["output_dir"] = str(DISTILL_DIR)
    manifest["sessions"] = refreshed
    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions")
    return 0


def cmd_bundle(next_count: int = 1, force: bool = False, session_ids: list[str] | None = None) -> int:
    ensure_dirs()
    manifest = load_manifest()
    wanted = set(session_ids or [])
    if wanted:
        pending = [
            s
            for s in manifest.get("sessions", [])
            if s.get("session_id") in wanted and (s.get("status") in BUNDLEABLE_STATUSES or force)
        ]
    else:
        pending = [
            s
            for s in manifest.get("sessions", [])
            if s.get("status") in {"new", "pending_redistill"}
            or (s.get("status") == "bundled" and (force or needs_bundle_refresh(s)))
        ]
        if next_count > 0:
            pending = pending[:next_count]
    if not pending:
        print("No sessions to bundle")
        return 0
    print(f"==> Bundle: generating {len(pending)} packet(s)")
    for session in pending:
        sid = session["session_id"]
        packet_path = PACKETS_DIR / f"{sid}.md"
        print(f"  -> {sid}")
        messages = load_messages(sid)
        turns = messages_to_turns(messages, turn_id_prefix=sid[:8])
        bundle_lossless_session(
            distill_dir=DISTILL_DIR,
            session=session,
            platform="opencode",
            turns=turns,
            source_fingerprint={
                "storage_tree_sha256": session.get("storage_tree_sha256"),
                "storage_tree_file_count": session.get("storage_tree_file_count"),
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
    print(f"OpenCode distill dir: {DISTILL_DIR}")
    print(f"Storage: {STORAGE_DIR} ({'exists' if STORAGE_DIR.exists() else 'missing'})")
    for status in ("new", "bundled", "pending_redistill", "distilled", "skipped"):
        n = sum(1 for s in manifest.get("sessions", []) if s.get("status") == status)
        if n:
            print(f"  {status}: {n}")
    return 0


def cmd_mark(session_id: str, status: str, force: bool = False) -> int:
    if status not in ALLOWED_STATUSES:
        print(f"Unsupported status: {status}")
        return 1
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
                session["last_distilled_revision_id"] = session.get("current_revision_id")
            manifest["updated_at"] = now_iso()
            save_manifest(manifest)
            print(f"Marked {session_id} as {status}")
            return 0
    print(f"Session not found: {session_id}")
    return 1


def cmd_self_test() -> int:
    test_dir = Path(__file__).resolve().parents[1] / "tests"
    if not test_dir.exists():
        print(f"No tests directory: {test_dir}")
        return 0
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCode session distiller")
    parser.add_argument("command", nargs="?", default="status")
    parser.add_argument("arg", nargs="?", default="")
    parser.add_argument("status", nargs="?", default="")
    parser.add_argument("--next", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--project", default="")
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
