#!/usr/bin/env python3
"""Antigravity (agy) session distiller — history.jsonl + brain transcripts."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEXT_LIMIT = int(os.environ.get("AGY_DISTILL_TEXT_LIMIT", "32000"))
ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped"}


def resolve_agy_home() -> Path:
    if os.environ.get("ANTIGRAVITY_CLI_ROOT"):
        return Path(os.environ["ANTIGRAVITY_CLI_ROOT"])
    if os.environ.get("AGY_HOME"):
        return Path(os.environ["AGY_HOME"])
    return Path.home() / ".gemini" / "antigravity-cli"


AGY_HOME = resolve_agy_home()
DISTILL_DIR = Path(os.environ.get("AGY_DISTILL_DIR", AGY_HOME / "session-distill"))
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
HISTORY_FILE = AGY_HOME / "history.jsonl"
BRAIN_DIR = AGY_HOME / "brain"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text("# Antigravity Session Knowledge Base\n\n", encoding="utf-8")
    if not MANIFEST_FILE.exists():
        save_manifest({"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []})


def load_manifest() -> dict[str, Any]:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []}


def save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_history(project_filter: str = "") -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    if not HISTORY_FILE.exists():
        return grouped
    flt = project_filter.lower().replace("\\", "/")
    with HISTORY_FILE.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            conv_id = obj.get("conversationId") or obj.get("conversation_id")
            if not conv_id:
                continue
            workspace = obj.get("workspace") or obj.get("cwd") or ""
            if flt and flt not in workspace.lower().replace("\\", "/"):
                continue
            entry = grouped.setdefault(
                str(conv_id),
                {
                    "session_id": str(conv_id),
                    "thread_name": "",
                    "project_path": workspace,
                    "prompts": [],
                    "timestamp": "",
                    "size_bytes": 0,
                    "last_write_time": "",
                },
            )
            display = (obj.get("display") or "").strip()
            if display:
                entry["prompts"].append(display[:TEXT_LIMIT])
                if not entry["thread_name"]:
                    entry["thread_name"] = display[:120]
            ts = obj.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts) / 1000, timezone.utc)
                    iso = dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    entry["timestamp"] = iso
                    entry["last_write_time"] = iso
                except (TypeError, ValueError, OSError):
                    pass
            entry["size_bytes"] = len(entry["prompts"])
    return grouped


def find_transcript(conversation_id: str) -> Path | None:
    candidates = [
        BRAIN_DIR / conversation_id / ".system_generated" / "logs" / "transcript_full.jsonl",
        BRAIN_DIR / conversation_id / ".system_generated" / "logs" / "transcript.jsonl",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def read_transcript_lines(path: Path) -> list[str]:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                lines.append(raw[:500])
                continue
            for key in ("text", "content", "message", "display"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    lines.append(val.strip()[:TEXT_LIMIT])
                    break
    return lines


def generate_packet(session: dict[str, Any], out_path: Path) -> dict[str, Any]:
    prompts = session.get("prompts", [])
    transcript_path = find_transcript(session["session_id"])
    transcript_lines = read_transcript_lines(transcript_path) if transcript_path else []
    warnings: list[str] = []
    if not transcript_path:
        warnings.append("No brain transcript found; packet built from history.jsonl prompts only.")
    lines = [
        f"# Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        "- Platform: antigravity",
        f"- Title: {session.get('thread_name', '')}",
        f"- Project: {session.get('project_path', '')}",
        f"- History prompts: {len(prompts)}",
        f"- Transcript: {transcript_path or 'missing'}",
        "",
        "## Packet Audit",
        f"- Coverage: `{'partial' if warnings else 'high'}`",
    ]
    if warnings:
        lines.extend(["", "### Audit Warnings", ""])
        lines.extend(f"- {w}" for w in warnings)
    if prompts:
        lines.extend(["", "## User Requests", ""])
        for block in prompts[-10:]:
            lines.extend(["```text", block, "```", ""])
    final = transcript_lines[-5:] or prompts[-3:]
    if final:
        lines.extend(["", "### Final Answers", "", "```text", "\n\n".join(final), "```", ""])
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"coverage": "partial" if warnings else "high"}


def cmd_index(project_filter: str = "") -> int:
    ensure_dirs()
    print("==> Index: scanning Antigravity history.jsonl")
    manifest = load_manifest()
    previous = {s["session_id"]: s for s in manifest.get("sessions", [])}
    grouped = read_history(project_filter=project_filter)
    refreshed: list[dict[str, Any]] = []
    new_count = 0
    for sid, meta in sorted(grouped.items(), key=lambda kv: kv[1].get("timestamp") or ""):
        old = previous.get(sid, {})
        status = old.get("status", "new")
        if status not in ALLOWED_STATUSES:
            status = "new"
        if not old:
            new_count += 1
            print(f"  + {sid} [{meta.get('project_path', '')}]")
        refreshed.append({**meta, "status": status, "bundle_path": old.get("bundle_path")})
    manifest["updated_at"] = now_iso()
    manifest["input_dirs"] = [str(HISTORY_FILE)]
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
    print(f"Antigravity distill dir: {DISTILL_DIR}")
    print(f"History: {HISTORY_FILE}")
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
    parser = argparse.ArgumentParser(description="Antigravity session distiller")
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
