#!/usr/bin/env python3
"""Codex session distiller for ~/.codex rollout JSONL files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

from distill_core.final_review import validate_final_review
from distill_core.ingest import ingest_revision
from distill_core.queue import BUNDLEABLE_STATUSES, compute_queue_status_on_index
from distill_core.revision import compute_source_fingerprint


CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
DISTILL_DIR = CODEX_HOME / "session-distill"
RAW_PRUNE_AUDIT_FILE = DISTILL_DIR / "raw-prune-audit.jsonl"
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
KB_REVIEW_STATE_FILE = DISTILL_DIR / "knowledge-review-state.json"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
MEMORY_DRAFTS_DIR = DISTILL_DIR / "memory-drafts"
ARCHIVED_DIR = CODEX_HOME / "archived_sessions"
LIVE_SESSIONS_DIR = CODEX_HOME / "sessions"
SESSION_INDEX_FILE = CODEX_HOME / "session_index.jsonl"

ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped", "pending_redistill"}
TEXT_LIMIT = int(os.environ.get("CODEX_DISTILL_TEXT_LIMIT", "1600"))
OUTPUT_LIMIT = int(os.environ.get("CODEX_DISTILL_OUTPUT_LIMIT", "1200"))
OUTPUT_LINE_LIMIT = int(os.environ.get("CODEX_DISTILL_OUTPUT_LINE_LIMIT", "20"))
FILE_REF_LIMIT = 30
KB_REVIEW_THRESHOLD = 5
KB_HIT_KEYWORD_MIN = 2
KB_VOLATILE_MARKERS = (
    "temporary",
    "one-off",
    "workaround",
    "临时",
    "一次性",
    "端口",
    "pid",
    "timestamp",
    "branch",
    "backup",
)
KB_VOLATILE_REGEXES = tuple(
    re.compile(rf"(?<![A-Za-z0-9_]){re.escape(marker)}(?![A-Za-z0-9_])", re.IGNORECASE)
    for marker in KB_VOLATILE_MARKERS
)
KB_STABLE_HINTS = (
    "always",
    "do not",
    "prefer",
    "should",
    "must",
    "verify",
    "wrap",
    "when",
    "如果",
    "当",
    "应",
    "需要",
    "不要",
)
FILE_REF_REGEX = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|\.{1,2}[\\/])?[A-Za-z0-9_.\\/\-]+?\.(?:"
    r"md|markdown|ya?ml|jsonl?|tsx|jsx|mjs|cjs|ts|js|py|ps1|sh|bat|cmd|sql|"
    r"env|txt|log|html|css|scss|csv|tsv"
    r"))(?::\d+)?",
    re.IGNORECASE,
)
SESSION_ID_REGEX = re.compile(r".*(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.IGNORECASE)
KB_SOURCE_REGEX = re.compile(r"Source:\s*`(?P<session_id>[0-9a-f\-]{36})`\.?$", re.IGNORECASE)
WORD_REGEX = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}")
IDE_REQUEST_MARKERS = (
    "## My request for Codex:",
    "## My request for Claude:",
    "## 我的请求:",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text("# Archived Session Knowledge Base\n\nPromote only stable, reusable lessons here. Cite source session ids in every entry.\n", encoding="utf-8")
    if not MANIFEST_FILE.exists():
        save_manifest({"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []})
    if not KB_REVIEW_STATE_FILE.exists():
        KB_REVIEW_STATE_FILE.write_text(json.dumps({"last_reviewed_entry_count": 0, "last_reviewed_at": ""}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest() -> dict[str, Any]:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": "", "input_dirs": [], "output_dir": str(DISTILL_DIR), "sessions": []}


def save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_kb_review_state() -> dict[str, Any]:
    ensure_dirs()
    return json.loads(read_text(KB_REVIEW_STATE_FILE))


def save_kb_review_state(state: dict[str, Any]) -> None:
    KB_REVIEW_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def session_id_from_path(path: Path) -> str:
    meta = read_session_meta(path)
    if meta.get("id"):
        return str(meta["id"])
    match = SESSION_ID_REGEX.match(path.name)
    if match:
        return match.group("id")
    return path.stem


def read_jsonl_records(path: Path):
    invalid = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            try:
                yield line_no, json.loads(line), None
            except json.JSONDecodeError as exc:
                invalid += 1
                yield line_no, None, str(exc)


def read_session_meta(path: Path) -> dict[str, Any]:
    for _, obj, _ in read_jsonl_records(path):
        if obj and obj.get("type") == "session_meta":
            payload = obj.get("payload") or {}
            return payload if isinstance(payload, dict) else {}
    return {}


def load_thread_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if not SESSION_INDEX_FILE.exists():
        return names
    for _, obj, _ in read_jsonl_records(SESSION_INDEX_FILE):
        if not obj:
            continue
        session_id = obj.get("id")
        thread_name = obj.get("thread_name")
        if session_id and thread_name:
            names[str(session_id)] = str(thread_name)
    return names


def discover_session_files() -> list[tuple[Path, str]]:
    discovered: dict[str, tuple[Path, str]] = {}
    for path in sorted(ARCHIVED_DIR.glob("rollout-*.jsonl")) if ARCHIVED_DIR.exists() else []:
        discovered[session_id_from_path(path)] = (path, "archived")
    if LIVE_SESSIONS_DIR.exists():
        for path in sorted(LIVE_SESSIONS_DIR.rglob("rollout-*.jsonl")):
            session_id = session_id_from_path(path)
            if session_id not in discovered:
                discovered[session_id] = (path, "live")
    return list(discovered.values())


def cmd_index() -> int:
    ensure_dirs()
    print("==> Index: scanning Codex sessions")
    manifest = load_manifest()
    previous = {entry["session_id"]: entry for entry in manifest.get("sessions", [])}
    thread_names = load_thread_names()
    refreshed = []
    seen_session_ids = set()
    new_count = 0
    for path, source_kind in discover_session_files():
        stat = path.stat()
        session_id = session_id_from_path(path)
        seen_session_ids.add(session_id)
        meta = read_session_meta(path)
        old = previous.get(session_id, {})
        source_fp_hash = compute_source_fingerprint({
            "size_bytes": stat.st_size,
            "last_write_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        })
        status = compute_queue_status_on_index(
            old,
            source_fingerprint=source_fp_hash,
            current_revision_id=old.get("current_revision_id"),
        )
        if not old:
            new_count += 1
            print(f"  + {path.name} ({stat.st_size / 1024:.1f}KB)")
        refreshed.append({
            "session_id": session_id,
            "file_name": path.name,
            "file_path": str(path),
            "source_kind": source_kind,
            "thread_name": thread_names.get(session_id, old.get("thread_name", "")),
            "timestamp": meta.get("timestamp") or "",
            "cwd": meta.get("cwd") or "",
            "source": meta.get("source") or meta.get("originator") or "",
            "model_provider": meta.get("model_provider") or "",
            "git": meta.get("git") or {},
            "size_bytes": stat.st_size,
            "last_write_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "status": status,
            "source_fingerprint": source_fp_hash,
            "last_indexed_fingerprint": source_fp_hash,
            "current_revision_id": old.get("current_revision_id"),
            "last_distilled_revision_id": old.get("last_distilled_revision_id"),
            "revision_path": old.get("revision_path"),
            "bundle_path": old.get("bundle_path"),
            "bundle_source_last_write_time": old.get("bundle_source_last_write_time"),
            "bundle_source_size_bytes": old.get("bundle_source_size_bytes"),
            "distilled_path": old.get("distilled_path"),
            "notes": old.get("notes", ""),
        })
    for session_id, old in previous.items():
        if session_id in seen_session_ids:
            continue
        if old.get("status") not in {"distilled", "skipped"}:
            continue
        preserved = dict(old)
        preserved["source_missing"] = True
        preserved.setdefault("source_missing_since", now_iso())
        refreshed.append(preserved)
    manifest["version"] = 1
    manifest["updated_at"] = now_iso()
    manifest["input_dirs"] = [str(ARCHIVED_DIR), str(LIVE_SESSIONS_DIR)]
    manifest["output_dir"] = str(DISTILL_DIR)
    manifest["sessions"] = refreshed
    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions")
    return 0


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def delete_raw_source(session: dict[str, Any]) -> tuple[bool, str]:
    raw_path_text = session.get("file_path")
    if not raw_path_text:
        return False, "raw file path missing"
    raw_path = Path(raw_path_text)
    if not raw_path.exists():
        session["raw_deleted_at"] = session.get("raw_deleted_at") or now_iso()
        session["source_missing"] = True
        return False, f"raw file already missing: {raw_path}"
    if not raw_path.is_file():
        return False, f"raw path is not a file: {raw_path}"
    if not (is_under(raw_path, ARCHIVED_DIR) or is_under(raw_path, LIVE_SESSIONS_DIR)):
        return False, f"refuse to delete raw file outside Codex session roots: {raw_path}"
    raw_path.unlink()
    session["raw_deleted_at"] = now_iso()
    session["source_missing"] = True
    return True, f"deleted raw file: {raw_path}"


def needs_bundle_refresh(session: dict[str, Any]) -> bool:
    return (
        session.get("bundle_source_last_write_time") != session.get("last_write_time")
        or session.get("bundle_source_size_bytes") != session.get("size_bytes")
    )


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"output_text", "input_text", "text"} and item.get("text") is not None:
                    parts.append(str(item.get("text")))
                elif item.get("type") == "tool_result" and item.get("content") is not None:
                    parts.append(str(item.get("content")))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def normalize_user_message(text: str, counters: Counter) -> str:
    message = (text or "").strip()
    if not message:
        return ""
    if message.startswith("# AGENTS.md instructions for ") and "<INSTRUCTIONS>" in message:
        counters["ignored_context_messages"] += 1
        return ""
    if message.startswith("<environment_context>"):
        counters["ignored_context_messages"] += 1
        return ""
    if message.startswith("# Context from my IDE setup:"):
        for marker in IDE_REQUEST_MARKERS:
            if marker in message:
                request = message.split(marker, 1)[1].strip()
                if request:
                    counters["trimmed_context_messages"] += 1
                    return request
        counters["ignored_context_messages"] += 1
        return ""
    return message


def clip_text(text: str, limit: int = TEXT_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n\n[clipped]", True


def clip_output(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    clipped = False
    if len(lines) > OUTPUT_LINE_LIMIT:
        lines = lines[:OUTPUT_LINE_LIMIT]
        clipped = True
    text = "\n".join(lines)
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT].rstrip()
        clipped = True
    if clipped:
        text += "\n[clipped]"
    return text, clipped


def make_turn(turn_id: str, cwd: str = "", timestamp: str = "") -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "cwd": cwd,
        "timestamp": timestamp,
        "user_messages": [],
        "assistant_updates": [],
        "final_answers": [],
        "plans": [],
        "commands": [],
        "command_outputs": [],
        "patches": [],
        "system_events": [],
    }


def parse_codex_session(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    meta: dict[str, Any] = {"session_id": session_id_from_path(path), "source_path": str(path)}
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counters = Counter()

    def ensure_turn(timestamp: str = "") -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = make_turn("unknown", timestamp=timestamp)
            turns.append(current)
        return current

    for line_no, obj, error in read_jsonl_records(path):
        if error:
            counters["invalid_json_lines"] += 1
            continue
        if not isinstance(obj, dict):
            continue
        outer_type = obj.get("type")
        timestamp = obj.get("timestamp") or ""
        payload = obj.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if outer_type == "session_meta":
            meta.update({
                "session_id": payload.get("id") or meta.get("session_id"),
                "timestamp": payload.get("timestamp") or timestamp,
                "cwd": payload.get("cwd") or "",
                "originator": payload.get("originator") or "",
                "cli_version": payload.get("cli_version") or "",
                "source": payload.get("source") or "",
                "model_provider": payload.get("model_provider") or "",
                "git": payload.get("git") or {},
            })
            continue
        if outer_type == "turn_context":
            current = make_turn(str(payload.get("turn_id") or f"turn-{len(turns)+1}"), cwd=str(payload.get("cwd") or ""), timestamp=timestamp)
            turns.append(current)
            continue
        turn = ensure_turn(timestamp)
        if outer_type == "event_msg":
            event_type = payload.get("type")
            if event_type == "user_message":
                message = normalize_user_message(str(payload.get("message") or ""), counters)
                if message:
                    turn["user_messages"].append(message)
            elif event_type == "agent_message":
                turn["assistant_updates"].append(str(payload.get("message") or ""))
            elif event_type == "item_completed":
                item = payload.get("item") or {}
                if isinstance(item, dict) and item.get("type") == "Plan":
                    turn["plans"].append(str(item.get("text") or ""))
                else:
                    turn["system_events"].append(f"item_completed: {str(item)[:300]}")
            elif event_type == "patch_apply_end":
                stdout = str(payload.get("stdout") or "")
                turn["patches"].append(stdout)
            elif event_type in {"task_started", "task_complete"}:
                turn["system_events"].append(event_type)
            continue
        if outer_type == "response_item":
            item_type = payload.get("type")
            if item_type == "message":
                role = payload.get("role")
                phase = payload.get("phase")
                text = extract_text_from_content(payload.get("content"))
                if role == "assistant" and phase == "final_answer":
                    turn["final_answers"].append(text)
                elif role == "assistant":
                    turn["assistant_updates"].append(text)
                elif role == "user":
                    message = normalize_user_message(text, counters)
                    if message:
                        turn["user_messages"].append(message)
            elif item_type in {"function_call", "custom_tool_call", "tool_search_call"}:
                name = payload.get("name") or item_type
                args = payload.get("arguments") if "arguments" in payload else payload.get("input")
                turn["commands"].append({"name": str(name), "arguments": args, "call_id": payload.get("call_id")})
            elif item_type in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
                output = str(payload.get("output") or "")
                turn["command_outputs"].append({"call_id": payload.get("call_id"), "output": output})
            elif item_type == "reasoning" and payload.get("encrypted_content"):
                counters["encrypted_reasoning"] += 1
    return meta, turns, dict(counters)


def collect_file_refs(*texts: str) -> Counter:
    refs = Counter()
    for text in texts:
        for match in FILE_REF_REGEX.finditer(text or ""):
            ref = match.group("path")
            if ref.lower() in {"console.log"}:
                continue
            refs[ref] += 1
    return refs


def build_packet(session: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    meta, turns, parse_counters = parse_codex_session(Path(session["file_path"]))
    thread_name = session.get("thread_name") or ""
    all_texts: list[str] = []
    clipped_text_blocks = 0
    clipped_outputs = 0
    lines: list[str] = []
    lines.extend([
        f"# Codex Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        "",
        f"- Source: `{session['file_name']}`",
        f"- Source kind: `{session.get('source_kind', '')}`",
        f"- Size: {int(session.get('size_bytes', 0)) / 1024:.1f}KB",
        f"- Path: `{session['file_path']}`",
        f"- Queue status: `{session.get('status', 'new')}`",
        f"- Thread name: `{thread_name}`",
        f"- CWD: `{meta.get('cwd', session.get('cwd', ''))}`",
        f"- Codex source: `{meta.get('source', '')}`",
        f"- CLI version: `{meta.get('cli_version', '')}`",
        f"- Model provider: `{meta.get('model_provider', '')}`",
        f"- Timestamp: `{meta.get('timestamp', session.get('timestamp', ''))}`",
    ])
    git = meta.get("git") or {}
    if isinstance(git, dict) and git:
        lines.append(f"- Git branch: `{git.get('branch', '')}`")
        lines.append(f"- Git commit: `{git.get('commit_hash', '')}`")

    rendered_turns: list[list[str]] = []
    for index, turn in enumerate(turns, start=1):
        block = ["", f"## Turn {index}", "", f"- Turn id: `{turn.get('turn_id')}`"]
        if turn.get("cwd"):
            block.append(f"- CWD: `{turn['cwd']}`")
        if turn.get("timestamp"):
            block.append(f"- Timestamp: `{turn['timestamp']}`")
        sections = [
            ("User Requests", "user_messages", TEXT_LIMIT),
            ("Assistant Updates", "assistant_updates", TEXT_LIMIT),
            ("Final Answers", "final_answers", TEXT_LIMIT),
            ("Plans", "plans", TEXT_LIMIT),
            ("Patches", "patches", OUTPUT_LIMIT),
        ]
        for title, key, limit in sections:
            values = [value for value in turn.get(key, []) if str(value).strip()]
            if not values:
                continue
            block.extend(["", f"### {title}", ""])
            for value in values:
                text, clipped = clip_text(str(value), limit)
                clipped_text_blocks += int(clipped)
                all_texts.append(text)
                block.extend(["```text", text, "```", ""])
        if turn.get("commands"):
            block.extend(["", "### Commands", ""])
            for command in turn["commands"]:
                args = command.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False) if args is not None else ""
                line = f"- `{command.get('name')}` {args[:500]}"
                all_texts.append(line)
                block.append(line)
        if turn.get("command_outputs"):
            block.extend(["", "### Command Outputs", ""])
            for output in turn["command_outputs"]:
                text, clipped = clip_output(output.get("output") or "")
                clipped_outputs += int(clipped)
                all_texts.append(text)
                block.extend(["```text", text, "```", ""])
        if turn.get("system_events"):
            block.extend(["", "### System Events", ""])
            for event in turn["system_events"][:20]:
                block.append(f"- {event}")
        rendered_turns.append(block)

    refs = collect_file_refs(*all_texts)
    warnings = []
    if clipped_text_blocks:
        warnings.append(f"{clipped_text_blocks} text block(s) clipped at {TEXT_LIMIT} chars.")
    if clipped_outputs:
        warnings.append(f"{clipped_outputs} command output excerpt(s) clipped.")
    if len(refs) > FILE_REF_LIMIT:
        warnings.append(f"Referenced Files shows only top {FILE_REF_LIMIT} of {len(refs)} paths.")
    if parse_counters.get("invalid_json_lines"):
        warnings.append(f"Invalid JSON lines skipped: {parse_counters['invalid_json_lines']}.")

    coverage = "partial" if warnings else "high"
    audit = {
        "coverage": coverage,
        "turns": len(turns),
        "user_messages": sum(len(t.get("user_messages", [])) for t in turns),
        "assistant_updates": sum(len(t.get("assistant_updates", [])) for t in turns),
        "final_answers": sum(len(t.get("final_answers", [])) for t in turns),
        "commands": sum(len(t.get("commands", [])) for t in turns),
        "command_outputs": sum(len(t.get("command_outputs", [])) for t in turns),
        "patches": sum(len(t.get("patches", [])) for t in turns),
        "unique_file_refs": len(refs),
        "warnings": warnings,
        **parse_counters,
    }

    lines.extend([
        "",
        "## Packet Audit",
        "",
        f"- Coverage: `{audit['coverage']}`",
        f"- Turns rendered: {audit['turns']}",
        f"- User request blocks: {audit['user_messages']}",
        f"- Assistant updates: {audit['assistant_updates']}",
        f"- Final answers: {audit['final_answers']}",
        f"- Commands: {audit['commands']}",
        f"- Command outputs: {audit['command_outputs']}",
        f"- Patches: {audit['patches']}",
        f"- Unique referenced files: {audit['unique_file_refs']}",
    ])
    for key in ("invalid_json_lines", "encrypted_reasoning", "ignored_context_messages", "trimmed_context_messages"):
        if audit.get(key):
            lines.append(f"- {key.replace('_', ' ').title()}: {audit[key]}")
    if warnings:
        lines.extend(["", "### Audit Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend([
        "",
        "## Distillation Reminder",
        "",
        "- Read `references/distillation-rules.md` before promotion.",
        "- If `Coverage: partial`, inspect the raw JSONL span before trusting clipped packet content.",
        "- `mark distilled` will require a session note and promotion decision.",
    ])
    if refs:
        lines.extend(["", "## Referenced Files", ""])
        for ref, count in refs.most_common(FILE_REF_LIMIT):
            lines.append(f"- `{ref}` ({count})")
    for block in rendered_turns:
        lines.extend(block)
    lines.extend([
        "",
        "## Suggested Next Step",
        "",
        f"1. Write `distilled/sessions/{session['session_id']}.md`.",
        "2. Record `Promotion Decision` or `No Promotion` in the note.",
        f"3. Run `session-distill mark {session['session_id']} distilled`.",
        "",
    ])
    return "\n".join(lines), audit


def cmd_bundle(next_count: int = 1, force: bool = False, session_ids: list[str] | None = None) -> int:
    ensure_dirs()
    manifest = load_manifest()
    wanted = set(session_ids or [])
    if wanted:
        pending = [
            s for s in manifest.get("sessions", [])
            if s.get("session_id") in wanted
            and (s.get("status") in BUNDLEABLE_STATUSES or force)
        ]
        found = {s.get("session_id") for s in pending}
        missing = sorted(wanted - found)
        for session_id in missing:
            print(f"Session not bundleable: {session_id}")
    else:
        pending = [
            s for s in manifest.get("sessions", [])
            if s.get("status") in {"new", "pending_redistill"}
            or (s.get("status") == "bundled" and (force or needs_bundle_refresh(s)))
        ]
        if next_count > 0:
            pending = pending[:next_count]
    print("==> Bundle: generating packets")
    count = 0
    for session in pending:
        if session.get("status") not in BUNDLEABLE_STATUSES and not force:
            continue
        packet_path = PACKETS_DIR / f"{session['session_id']}.md"
        print(f"  -> {session['session_id']}")
        session["status"] = "bundled"
        _meta, turns, parse_counters = parse_codex_session(Path(session["file_path"]))
        source_fp = {
            "size_bytes": session.get("size_bytes"),
            "last_write_time": session.get("last_write_time"),
            "file_name": session.get("file_name"),
        }
        metadata = {
            **session,
            "thread_name": session.get("thread_name") or "",
            "cwd": _meta.get("cwd", session.get("cwd", "")),
            "parse_counters": parse_counters,
        }
        revision_id, revision_dir, _audit = ingest_revision(
            DISTILL_DIR,
            session_id=session["session_id"],
            platform="codex",
            turns=turns,
            source_fingerprint=source_fp,
            metadata=metadata,
        )
        packet_path.write_text(read_text(revision_dir / "packet.md"), encoding="utf-8")
        session["bundle_path"] = str(packet_path)
        session["bundle_source_last_write_time"] = session.get("last_write_time")
        session["bundle_source_size_bytes"] = session.get("size_bytes")
        session["current_revision_id"] = revision_id
        session["revision_path"] = str(revision_dir)
        print_kb_hit_reminder(read_text(packet_path), exclude_session_id=session["session_id"], source_label=f"packet {session['session_id']}")
        count += 1
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> Bundle done: {count} packets")
    return 0


def cmd_run(next_count: int = 1, force: bool = False, session_ids: list[str] | None = None) -> int:
    cmd_index()
    cmd_bundle(next_count=next_count, force=force, session_ids=session_ids)
    return cmd_status()


def cmd_status() -> int:
    ensure_dirs()
    manifest = load_manifest()
    sessions = manifest.get("sessions", [])
    counts = Counter(s.get("status", "new") for s in sessions)
    print("==> Codex Session Distiller Status")
    print("")
    print(f"Sessions: {len(sessions)} total | new={counts['new']} | bundled={counts['bundled']} | pending_redistill={counts.get('pending_redistill', 0)} | distilled={counts['distilled']} | skipped={counts['skipped']}")
    if counts["bundled"]:
        print("")
        print("Pending packets:")
        for s in sessions:
            if s.get("status") == "bundled":
                print(f"  - {s['session_id']} {s.get('thread_name', '')}".rstrip())
    print("")
    print(f"Knowledge base: {KNOWLEDGE_FILE}")
    return 0


def cmd_list(min_size_kb: int = 100) -> int:
    ensure_dirs()
    cmd_index()
    manifest = load_manifest()
    for session in manifest.get("sessions", []):
        if int(session.get("size_bytes", 0)) >= min_size_kb * 1024:
            print(f"{session['session_id']} | {session.get('status')} | {int(session.get('size_bytes', 0)) / 1024:.1f}KB | {session.get('thread_name', '')}")
    return 0


def packet_coverage(session_id: str) -> str:
    packet = PACKETS_DIR / f"{session_id}.md"
    if not packet.exists():
        return "missing"
    text = read_text(packet)
    if "Coverage: `lossless`" in text:
        return "lossless"
    if "Coverage: `partial`" in text:
        return "partial"
    if "Coverage: `high`" in text:
        return "high"
    return "unknown"


def load_draft_pending_count(session_id: str) -> int:
    draft_path = MEMORY_DRAFTS_DIR / f"{session_id}.json"
    if not draft_path.exists():
        return 0
    data = json.loads(draft_path.read_text(encoding="utf-8"))
    entries = data.get("draft_entries") or data.get("entries") or []
    return sum(1 for entry in entries if entry.get("review_status") == "pending")


def validate_distilled(session_id: str) -> list[str]:
    errors = []
    note_path = DISTILLED_DIR / f"{session_id}.md"
    packet_path = PACKETS_DIR / f"{session_id}.md"
    if not packet_path.exists():
        errors.append(f"packet missing: {packet_path}")
    if not note_path.exists():
        errors.append(f"session note missing: {note_path}")
        return errors
    note = read_text(note_path).lower()
    coverage = packet_coverage(session_id)
    if coverage == "partial" and not any(marker in note for marker in ["raw transcript", "raw jsonl", "raw review", "原始", "补看"]):
        errors.append("partial packet requires raw transcript review note")
    errors.extend(validate_final_review(read_text(note_path)))
    if not any(marker in note for marker in ["promotion decision", "memory decision", "no promotion", "不提升", "知识", "promote"]):
        errors.append("session note must record promotion/no-promotion decision")
    pending = load_draft_pending_count(session_id)
    if pending:
        errors.append(f"memory draft has {pending} pending entrie(s)")
    kb_entries = load_kb_entries()
    sourced_entries = [entry for entry in kb_entries if entry.get("session_id") == session_id]
    for entry in sourced_entries:
        status, reasons = assess_kb_entry(entry, current_session_id=session_id)
        if status == "needs-review":
            errors.append(f"knowledge entry needs review: {entry['text']} ({'; '.join(reasons)})")
    return errors


def load_kb_entries() -> list[dict[str, Any]]:
    ensure_dirs()
    if not KNOWLEDGE_FILE.exists():
        return []
    section = ""
    entries: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(read_text(KNOWLEDGE_FILE).splitlines(), start=1):
        line = raw_line.rstrip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        match = KB_SOURCE_REGEX.search(stripped)
        if not match:
            continue
        text = stripped[2:].strip()
        text = KB_SOURCE_REGEX.sub("", text).strip()
        entries.append({
            "line_no": line_no,
            "section": section,
            "session_id": match.group("session_id"),
            "text": text,
            "raw_line": line,
        })
    return entries


def extract_keywords(text: str) -> set[str]:
    keywords = {token.lower() for token in WORD_REGEX.findall(text or "")}
    return {token for token in keywords if token not in {"source", "when", "then", "with", "that", "this", "from", "then", "will", "code"}}


def find_kb_hits(text: str, exclude_session_id: str = "", limit: int = 5) -> list[dict[str, Any]]:
    text_keywords = extract_keywords(text)
    if not text_keywords:
        return []
    hits: list[dict[str, Any]] = []
    for entry in load_kb_entries():
        if exclude_session_id and entry.get("session_id") == exclude_session_id:
            continue
        entry_keywords = extract_keywords(entry.get("text", ""))
        overlap = text_keywords & entry_keywords
        if len(overlap) >= KB_HIT_KEYWORD_MIN:
            hits.append({
                "entry": entry,
                "overlap": sorted(overlap)[:8],
                "score": len(overlap),
            })
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:limit]


def print_kb_review_reminder() -> None:
    entries = load_kb_entries()
    state = load_kb_review_state()
    last_reviewed_entry_count = int(state.get("last_reviewed_entry_count", 0))
    delta = len(entries) - last_reviewed_entry_count
    if delta >= KB_REVIEW_THRESHOLD:
        print("==> Knowledge Review Reminder")
        print(
            f"Knowledge base has {len(entries)} entries, {delta} more than the last recorded review. "
            "Run `session-distill review-kb --next 20`."
        )


def print_kb_hit_reminder(text: str, exclude_session_id: str = "", source_label: str = "text") -> None:
    hits = find_kb_hits(text, exclude_session_id=exclude_session_id)
    if not hits:
        return
    print(f"==> Knowledge Verify Reminder ({source_label})")
    print("This content overlaps with existing knowledge. Consider `verify-entry` on:")
    for item in hits:
        entry = item["entry"]
        overlap = ", ".join(item["overlap"])
        print(f"  - {entry['session_id']} | overlap={overlap}")
        print(f"    {entry['text']}")


def assess_kb_entry(entry: dict[str, Any], current_session_id: str = "") -> tuple[str, list[str]]:
    text = (entry.get("text") or "").strip()
    lowered = text.lower()
    reasons: list[str] = []
    status = "stable"
    if len(text) < 40:
        reasons.append("entry too short to convey a reusable rule")
    if not any(marker in lowered for marker in KB_STABLE_HINTS):
        reasons.append("entry does not read like a reusable rule/workflow")
    if any(pattern.search(text) for pattern in KB_VOLATILE_REGEXES):
        reasons.append("entry contains volatile or workaround-like wording")
    session_id = entry.get("session_id")
    if not session_id:
        reasons.append("missing source session id")
    else:
        note_path = DISTILLED_DIR / f"{session_id}.md"
        if not note_path.exists():
            reasons.append("source distilled note missing")
        else:
            note = read_text(note_path).lower()
            if "promotion decision" not in note and "no promotion" not in note:
                reasons.append("source note lacks promotion decision section")
            if session_id not in note:
                reasons.append("source note does not self-identify session id")
            entry_keywords = extract_keywords(text)
            note_keywords = extract_keywords(note)
            overlap = len(entry_keywords & note_keywords)
            if entry_keywords and overlap < max(2, min(4, len(entry_keywords) // 3 or 1)):
                reasons.append("knowledge entry is not meaningfully supported by the source note")
        session = next((s for s in load_manifest().get("sessions", []) if s.get("session_id") == session_id), None)
        if session and session_id != current_session_id and session.get("status") not in {"distilled", "skipped"}:
            reasons.append(f"source session status is {session.get('status')}, not distilled/skipped")
    if reasons:
        status = "needs-review"
    if any("missing" in reason for reason in reasons):
        status = "stale"
    return status, reasons


def collect_verify_questions(entry: dict[str, Any]) -> list[str]:
    text = entry.get("text") or ""
    return [
        f"这条现在还成立吗: {text}",
        "代码/配置/文档真相现在还一致吗",
        "有没有被后续改动推翻，或者只是一次性 workaround",
        "它应该继续留在 knowledge-base，还是降级回 session note",
    ]


def cmd_review_kb(limit: int = 20, query: str = "") -> int:
    entries = load_kb_entries()
    if query:
        lowered = query.lower()
        entries = [
            entry for entry in entries
            if lowered in (entry.get("text") or "").lower()
            or lowered in (entry.get("session_id") or "").lower()
            or lowered in (entry.get("section") or "").lower()
        ]
    entries = list(reversed(entries))
    if limit > 0:
        entries = entries[:limit]
    print("==> Knowledge Review")
    if not entries:
        print("No matching knowledge entries.")
        return 0
    counts = Counter()
    for entry in entries:
        status, reasons = assess_kb_entry(entry)
        counts[status] += 1
        print(f"[{status}] line {entry['line_no']} | {entry['session_id']} | {entry.get('section', '')}")
        print(f"  {entry['text']}")
        for reason in reasons[:4]:
            print(f"  - {reason}")
    print("")
    print(
        f"Summary: total={len(entries)} | stable={counts['stable']} | "
        f"needs-review={counts['needs-review']} | stale={counts['stale']} | superseded={counts['superseded']}"
    )
    state = load_kb_review_state()
    state["last_reviewed_entry_count"] = len(load_kb_entries())
    state["last_reviewed_at"] = now_iso()
    save_kb_review_state(state)
    return 0


def cmd_verify_entry(query: str) -> int:
    entries = load_kb_entries()
    lowered = query.lower()
    matches = [
        entry for entry in entries
        if lowered in (entry.get("text") or "").lower()
        or lowered in (entry.get("session_id") or "").lower()
        or lowered in (entry.get("section") or "").lower()
    ]
    print("==> Knowledge Verify")
    if not matches:
        print(f"No knowledge entry matched: {query}")
        return 1
    for entry in matches[:10]:
        status, reasons = assess_kb_entry(entry)
        print(f"[{status}] line {entry['line_no']} | {entry['session_id']} | {entry.get('section', '')}")
        print(f"  {entry['text']}")
        if reasons:
            print("  Review findings:")
            for reason in reasons[:6]:
                print(f"  - {reason}")
        print("  Grill-me style questions:")
        for question in collect_verify_questions(entry):
            print(f"  - {question}")
    if len(matches) > 10:
        print(f"... and {len(matches) - 10} more match(es)")
    return 0


def cmd_prune_kb(query: str = "", remove_statuses: set[str] | None = None) -> int:
    remove_statuses = remove_statuses or {"stale", "superseded"}
    lines = read_text(KNOWLEDGE_FILE).splitlines()
    entries = load_kb_entries()
    remove_lines: set[int] = set()
    removed: list[tuple[str, dict[str, Any]]] = []
    for entry in entries:
        if query:
            lowered = query.lower()
            haystack = " ".join([entry.get("text", ""), entry.get("session_id", ""), entry.get("section", "")]).lower()
            if lowered not in haystack:
                continue
        status, _ = assess_kb_entry(entry)
        if status in remove_statuses:
            remove_lines.add(entry["line_no"])
            removed.append((status, entry))
    if not removed:
        print("==> Knowledge Prune")
        print("No matching knowledge entries to prune.")
        return 0
    new_lines = [line for idx, line in enumerate(lines, start=1) if idx not in remove_lines]
    KNOWLEDGE_FILE.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    print("==> Knowledge Prune")
    print(f"Removed {len(removed)} knowledge entrie(s).")
    for status, entry in removed[:20]:
        print(f"  - [{status}] line {entry['line_no']} | {entry['session_id']} | {entry['text']}")
    if len(removed) > 20:
        print(f"  ... and {len(removed) - 20} more")
    return 0


def cmd_mark(session_id: str, status: str, force: bool = False, delete_raw: bool = False) -> int:
    if status not in ALLOWED_STATUSES:
        print(f"Unsupported status: {status}")
        return 1
    ensure_dirs()
    if status == "distilled" and not force:
        errors = validate_distilled(session_id)
        if errors:
            print("Cannot mark distilled:")
            for error in errors:
                print(f"  - {error}")
            print("Use --force only after manual review.")
            return 1
    manifest = load_manifest()
    found = False
    note_text = ""
    for session in manifest.get("sessions", []):
        if session.get("session_id") == session_id:
            session["status"] = status
            if status == "distilled":
                session["distilled_path"] = str(DISTILLED_DIR / f"{session_id}.md")
                session["last_distilled_revision_id"] = session.get("current_revision_id") or session.get("last_distilled_revision_id")
                note_path = DISTILLED_DIR / f"{session_id}.md"
                if note_path.exists():
                    note_text = read_text(note_path)
                if delete_raw:
                    deleted, message = delete_raw_source(session)
                    print(f"==> {message}")
                    if not deleted and not session.get("source_missing"):
                        return 1
            found = True
            break
    if not found:
        print(f"Session not found: {session_id}")
        return 1
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> Marked {session_id} -> {status}")
    if status == "distilled":
        print_kb_review_reminder()
        if note_text:
            print_kb_hit_reminder(note_text, exclude_session_id=session_id, source_label=f"note {session_id}")
    return 0


def cmd_prune_raw(session_id: str, *, confirm: bool = False, reason: str = "") -> int:
    ensure_dirs()
    manifest = load_manifest()
    session = next((item for item in manifest.get("sessions", []) if item.get("session_id") == session_id), None)
    if not session:
        print(f"Session not found: {session_id}")
        return 1
    if not confirm:
        print("Dry run: would delete raw source for session (pass --confirm to execute)")
        print(f"  session_id: {session_id}")
        print(f"  file_path: {session.get('file_path')}")
        return 0
    deleted, message = delete_raw_source(session)
    audit_entry = {
        "at": now_iso(),
        "session_id": session_id,
        "reason": reason or "manual prune",
        "message": message,
        "deleted": deleted,
    }
    RAW_PRUNE_AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with RAW_PRUNE_AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> {message}")
    return 0 if deleted or session.get("source_missing") else 1


def cmd_prune(statuses: set[str] | None = None, source_missing_only: bool = True) -> int:
    ensure_dirs()
    manifest = load_manifest()
    statuses = statuses or {"distilled", "skipped"}
    before = len(manifest.get("sessions", []))
    pruned = []
    kept = []
    for session in manifest.get("sessions", []):
        status = session.get("status")
        source_missing = bool(session.get("source_missing"))
        if status in statuses and ((not source_missing_only) or source_missing):
            pruned.append(session)
            continue
        kept.append(session)
    manifest["sessions"] = kept
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> Pruned {len(pruned)} session record(s); {before} -> {len(kept)}")
    for session in pruned[:20]:
        print(f"  - {session.get('status')} {session.get('session_id')}")
    if len(pruned) > 20:
        print(f"  ... and {len(pruned) - 20} more")
    return 0


def cmd_self_test() -> int:
    import unittest

    print("==> Codex Session Distiller Self-Test")
    test_dir = Path(__file__).resolve().parents[1] / "tests"
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"run", "bundle", "status", "list", "mark", "prune", "prune-raw", "review-kb", "prune-kb", "verify-entry", "self-test", "help"}
    command = "help"
    for index, token in enumerate(argv):
        if token in commands:
            command = token
            del argv[index]
            break
    parser = argparse.ArgumentParser(description="Codex Session Distiller")
    parser.add_argument("--next", type=int, default=1)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delete-raw", action="store_true", help="Deprecated for mark; use prune-raw instead")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--reason", type=str, default="")
    parser.add_argument("--statuses", type=str, default="distilled,skipped")
    parser.add_argument("--all-pruned", action="store_true")
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("args", nargs="*")
    args = parser.parse_args(argv)
    if command == "help":
        parser.print_help()
        return 0
    if command == "self-test":
        return cmd_self_test()
    if command == "status":
        return cmd_status()
    if command == "list":
        return cmd_list(args.size)
    if command == "run":
        return cmd_run(args.next, args.force, session_ids=args.args)
    if command == "bundle":
        return cmd_bundle(args.next, args.force, session_ids=args.args)
    if command == "prune":
        statuses = {item.strip() for item in args.statuses.split(",") if item.strip()}
        return cmd_prune(statuses=statuses, source_missing_only=not args.all_pruned)
    if command == "prune-raw":
        if not args.args:
            print("Usage: session-distill prune-raw SESSION-ID [--confirm] [--reason TEXT]")
            return 1
        return cmd_prune_raw(args.args[0], confirm=args.confirm, reason=args.reason)
    if command == "review-kb":
        return cmd_review_kb(limit=args.next, query=args.query)
    if command == "prune-kb":
        statuses = {item.strip() for item in args.statuses.split(",") if item.strip()}
        return cmd_prune_kb(query=args.query, remove_statuses=statuses)
    if command == "verify-entry":
        query = args.query or (args.args[0] if args.args else "")
        if not query:
            print("Usage: session-distill verify-entry <session-id|keyword>")
            return 1
        return cmd_verify_entry(query)
    if command == "mark":
        if len(args.args) < 2:
            print("Usage: session-distill mark SESSION-ID STATUS")
            return 1
        return cmd_mark(args.args[0], args.args[1], force=args.force, delete_raw=args.delete_raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
