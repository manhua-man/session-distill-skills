#!/usr/bin/env python3
"""OpenCode session distiller — storage/session + message/part JSON tree."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEXT_LIMIT = int(os.environ.get("OPENCODE_DISTILL_TEXT_LIMIT", "32000"))
ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped"}


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


def load_message_texts(session_id: str) -> tuple[list[str], list[str]]:
    user_blocks: list[str] = []
    assistant_blocks: list[str] = []
    message_dir = STORAGE_DIR / "message" / session_id
    part_root = STORAGE_DIR / "part"
    if not message_dir.exists():
        return user_blocks, assistant_blocks
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
                        chunks.append(val.strip()[:TEXT_LIMIT])
        body = "\n".join(chunks).strip()
        if not body:
            continue
        if role == "user":
            user_blocks.append(body)
        elif role == "assistant":
            assistant_blocks.append(body)
    return user_blocks, assistant_blocks


def generate_packet(session: dict[str, Any], out_path: Path) -> dict[str, Any]:
    user_blocks, assistant_blocks = load_message_texts(session["session_id"])
    warnings: list[str] = []
    if not user_blocks and not assistant_blocks:
        warnings.append("No message/part content found under storage/.")
    lines = [
        f"# Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        "- Platform: opencode",
        f"- Title: {session.get('thread_name', '')}",
        f"- Project: {session.get('project_path', '')}",
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
    if assistant_blocks:
        lines.extend(["", "### Final Answers", "", "```text", "\n\n".join(assistant_blocks[-3:]), "```", ""])
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"coverage": "partial" if warnings else "high"}


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
        status = old.get("status", "new")
        if status not in ALLOWED_STATUSES:
            status = "new"
        if not old:
            new_count += 1
            print(f"  + {sid} [{meta.get('project_path', '')}]")
        refreshed.append({**meta, "status": status, "bundle_path": old.get("bundle_path")})
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
    candidates = [
        s for s in manifest.get("sessions", []) if s.get("status") in {"new", "bundled"} and (not wanted or s["session_id"] in wanted)
    ]
    selected = candidates if session_ids else candidates[:next_count]
    if not selected:
        print("No sessions to bundle")
        return 0
    for session in selected:
        sid = session["session_id"]
        path = PACKETS_DIR / f"{sid}.md"
        print(f"  -> {sid}")
        generate_packet(session, path)
        session["status"] = "bundled"
        session["bundle_path"] = str(path)
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    return 0


def cmd_status() -> int:
    ensure_dirs()
    manifest = load_manifest()
    print(f"OpenCode distill dir: {DISTILL_DIR}")
    print(f"Storage: {STORAGE_DIR} ({'exists' if STORAGE_DIR.exists() else 'missing'})")
    for status in ("new", "bundled", "distilled", "skipped"):
        n = sum(1 for s in manifest.get("sessions", []) if s.get("status") == status)
        if n:
            print(f"  {status}: {n}")
    return 0


def cmd_mark(session_id: str, status: str) -> int:
    manifest = load_manifest()
    for session in manifest.get("sessions", []):
        if session["session_id"] == session_id:
            session["status"] = status
            manifest["updated_at"] = now_iso()
            save_manifest(manifest)
            print(f"Marked {session_id} as {status}")
            return 0
    print(f"Session not found: {session_id}")
    return 1


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
        return cmd_mark(args.arg, args.status)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
