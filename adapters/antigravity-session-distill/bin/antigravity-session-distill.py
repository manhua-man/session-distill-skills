#!/usr/bin/env python3
"""Antigravity (agy) session distiller — history.jsonl + brain transcripts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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
    lines_to_turns,
    validate_distilled_note,
)
from distill_core.queue import BUNDLEABLE_STATUSES
from deep_distill_lib import resolve_repo_kb_path

TEXT_LIMIT = int(os.environ.get("AGY_DISTILL_TEXT_LIMIT", "32000"))
ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped", "pending_redistill"}


def resolve_agy_candidate_homes() -> list[Path]:
    candidates: list[Path] = []
    for env_var in ("ANTIGRAVITY_CLI_ROOT", "AGY_HOME", "ANTIGRAVITY_HOME"):
        val = os.environ.get(env_var)
        if val:
            p = Path(val)
            if p not in candidates:
                candidates.append(p)
    if "AGY_HOME" in globals() and isinstance(globals()["AGY_HOME"], Path):
        g_home = globals()["AGY_HOME"]
        if g_home not in candidates:
            candidates.insert(0, g_home)

    if not candidates or (len(candidates) == 1 and not os.environ.get("AGY_HOME") and not os.environ.get("ANTIGRAVITY_CLI_ROOT")):
        default_cli = Path.home() / ".gemini" / "antigravity-cli"
        default_ide = Path.home() / ".gemini" / "antigravity"
        for d in (default_cli, default_ide):
            if d not in candidates and d.exists():
                candidates.append(d)
        if not candidates:
            candidates.append(default_cli)
    return candidates


def resolve_primary_home() -> Path:
    homes = resolve_agy_candidate_homes()
    return homes[0]


AGY_HOME = resolve_primary_home()
DISTILL_DIR = Path(os.environ.get("AGY_DISTILL_DIR", AGY_HOME / "session-distill"))
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
UNIFIED_REPO_KB = resolve_repo_kb_path()
KNOWLEDGE_FILE = UNIFIED_REPO_KB if UNIFIED_REPO_KB.exists() else DISTILL_DIR / "knowledge-base.md"
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
    history_paths: list[Path] = []
    for home in resolve_agy_candidate_homes():
        h = home / "history.jsonl"
        if h.exists() and h not in history_paths:
            history_paths.append(h)
    if not history_paths and HISTORY_FILE.exists():
        history_paths.append(HISTORY_FILE)

    flt = project_filter.lower().replace("\\", "/")
    for h_path in history_paths:
        with h_path.open("r", encoding="utf-8", errors="replace") as handle:
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

    # Fallback: scan brain directories directly for unlisted brain sessions
    for home in resolve_agy_candidate_homes():
        brain = home / "brain"
        if brain.exists():
            for folder in brain.iterdir():
                sid = folder.name
                if not folder.is_dir() or sid in grouped:
                    continue
                trans_path = (
                    folder / ".system_generated" / "logs" / "transcript_full.jsonl"
                    if (folder / ".system_generated" / "logs" / "transcript_full.jsonl").exists()
                    else folder / ".system_generated" / "logs" / "transcript.jsonl"
                )
                if not trans_path.exists():
                    trans_path = folder / "transcript.jsonl"
                if trans_path.exists():
                    first_prompt = ""
                    proj_path = ""
                    with trans_path.open("r", encoding="utf-8", errors="replace") as fh:
                        for l in fh:
                            try:
                                o = json.loads(l)
                                if o.get("type") == "USER_INPUT" and not first_prompt:
                                    first_prompt = re.sub(r"</?[A-Z_]+>", "", str(o.get("content") or "")).strip()[:120]
                            except Exception:
                                pass
                    if flt and flt not in proj_path.lower().replace("\\", "/"):
                        continue
                    mtime = datetime.fromtimestamp(trans_path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    grouped[sid] = {
                        "session_id": sid,
                        "thread_name": first_prompt or f"Brain Session {sid[:8]}",
                        "project_path": proj_path,
                        "prompts": [first_prompt] if first_prompt else [],
                        "timestamp": mtime,
                        "size_bytes": trans_path.stat().st_size,
                        "last_write_time": mtime,
                    }
    return grouped


def find_transcript(conversation_id: str) -> Path | None:
    for home in resolve_agy_candidate_homes():
        brain = home / "brain"
        candidates = [
            brain / conversation_id / ".system_generated" / "logs" / "transcript_full.jsonl",
            brain / conversation_id / ".system_generated" / "logs" / "transcript.jsonl",
            brain / conversation_id / "transcript.jsonl",
        ]
        for path in candidates:
            if path.exists():
                return path
    return None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_step_summary(obj: dict[str, Any], *, clip_content: bool = True) -> str | None:
    step_type = obj.get("type", "")
    content = obj.get("content")
    tool_calls = obj.get("tool_calls") or []

    parts: list[str] = []

    if isinstance(content, str) and content.strip():
        text = content.strip()
        if step_type == "USER_INPUT":
            clean_text = re.sub(r"</?[A-Z_]+>", "", text).strip()
            parts.append(f"User: {clean_text}" if clean_text else text)
        elif step_type == "PLANNER_RESPONSE":
            parts.append(text)
        elif step_type not in ("CHECKPOINT", "CONVERSATION_HISTORY"):
            parts.append(text)

    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                t_name = tc.get("name", "tool")
                t_args = tc.get("args") or {}
                if isinstance(t_args, dict):
                    arg_summary = []
                    for k in ("CommandLine", "TargetFile", "AbsolutePath", "Query", "SearchPath", "DirectoryPath"):
                        if k in t_args:
                            arg_summary.append(f"{k}={t_args[k]}")
                    summary_str = ", ".join(arg_summary) if arg_summary else str(t_args)[:120]
                    parts.append(f"[Tool Call: {t_name}({summary_str})]")
                else:
                    parts.append(f"[Tool Call: {t_name}]")

    if not parts:
        for key in ("text", "message", "display"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
                break

    if not parts:
        return None

    full_text = "\n".join(parts)
    if clip_content and len(full_text) > TEXT_LIMIT:
        return full_text[:TEXT_LIMIT] + "\n[clipped]"
    return full_text


def read_transcript_lines(path: Path, *, clip_content: bool = True) -> list[str]:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                lines.append(raw if not clip_content else raw[:TEXT_LIMIT])
                continue
            summary = parse_step_summary(obj, clip_content=clip_content)
            if summary:
                lines.append(summary)
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
        if not old:
            new_count += 1
            print(f"  + {sid} [{meta.get('project_path', '')}]")
        refreshed.append(
            index_session_entry(
                old,
                session_id=sid,
                source_fields={
                    "size_bytes": meta.get("size_bytes"),
                    "last_write_time": meta.get("last_write_time"),
                    "prompt_count": len(meta.get("prompts") or []),
                },
                base_meta=meta,
            )
        )
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
        s for s in manifest.get("sessions", [])
        if s.get("status") in BUNDLEABLE_STATUSES and (not wanted or s["session_id"] in wanted or force)
    ]
    selected = candidates if session_ids else candidates[:next_count]
    if not selected:
        print("No sessions to bundle")
        return 0
    for session in selected:
        sid = session["session_id"]
        path = PACKETS_DIR / f"{sid}.md"
        print(f"  -> {sid}")
        transcript_path = find_transcript(sid)
        transcript_lines = read_transcript_lines(transcript_path, clip_content=False) if transcript_path else []
        prompt_lines = [str(p) for p in session.get("prompts") or []]
        source_lines = transcript_lines or prompt_lines
        turns = lines_to_turns(source_lines, turn_id_prefix=sid[:8])
        bundle_lossless_session(
            distill_dir=DISTILL_DIR,
            session=session,
            platform="antigravity",
            turns=turns,
            source_fingerprint={
                "size_bytes": session.get("size_bytes"),
                "last_write_time": session.get("last_write_time"),
                "prompt_count": len(prompt_lines),
                "transcript": str(transcript_path or ""),
            },
            packet_path=path,
            read_text=read_text,
            parse_counters={
                "history_prompts": len(prompt_lines),
                "transcript_lines": len(transcript_lines),
                "transcript_missing": int(transcript_path is None),
            },
        )
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    return 0


def cmd_status() -> int:
    ensure_dirs()
    manifest = load_manifest()
    print(f"Antigravity distill dir: {DISTILL_DIR}")
    print(f"History: {HISTORY_FILE}")
    for status in ("new", "bundled", "pending_redistill", "distilled", "skipped"):
        n = sum(1 for s in manifest.get("sessions", []) if s.get("status") == status)
        if n:
            print(f"  {status}: {n}")
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
                if os.environ.get("AGY_PURGE_RAW_ON_DISTILL", "true").lower() in ("1", "true", "yes"):
                    for home in resolve_agy_candidate_homes():
                        raw_folder = home / "brain" / session_id
                        if raw_folder.exists() and raw_folder.is_dir():
                            try:
                                shutil.rmtree(raw_folder)
                                print(f"Auto-purged raw brain folder: {session_id}")
                            except Exception as err:
                                print(f"Warning: Could not auto-purge raw folder {session_id}: {err}")
                        conv_dir = home / "conversations"
                        if conv_dir.exists():
                            for ext in ("", "-wal", "-shm"):
                                db_f = conv_dir / f"{session_id}.db{ext}"
                                if db_f.exists():
                                    try:
                                        db_f.unlink()
                                        print(f"Auto-purged conversation db: {db_f.name}")
                                    except Exception:
                                        pass
                        pb_f = home / "agyhub_summaries_proto.pb"
                        if pb_f.exists():
                            try:
                                pb_f.unlink()
                            except Exception:
                                pass
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
    parser = argparse.ArgumentParser(description="Antigravity session distiller")
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
