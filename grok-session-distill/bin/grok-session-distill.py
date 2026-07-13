#!/usr/bin/env python3
"""Grok CLI session distiller for ~/.grok/sessions chat_history JSONL files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote


GROK_HOME = Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok"))
SESSIONS_ROOT = GROK_HOME / "sessions"
DISTILL_DIR = GROK_HOME / "session-distill"
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"

ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped"}
TEXT_LIMIT = 8000
OUTPUT_LIMIT = 8000
OUTPUT_LINE_LIMIT = 120
FILE_REF_LIMIT = 80
SESSION_ID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
FILE_REF_REGEX = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|\.{1,2}[\\/])?[A-Za-z0-9_.\\/\-]+?\.(?:"
    r"md|markdown|ya?ml|jsonl?|tsx|jsx|mjs|cjs|ts|js|py|ps1|sh|bat|cmd|sql|"
    r"env|txt|log|html|css|scss|csv|tsv"
    r"))(?::\d+)?",
    re.IGNORECASE,
)
KB_SOURCE_REGEX = re.compile(r"Source:\s*`(?P<session_id>[0-9a-f\-]{36})`\.?$", re.IGNORECASE)
USER_QUERY_REGEX = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL | re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text(
            "# Archived Session Knowledge Base\n\n"
            "Promote only stable, reusable lessons here. Cite source session ids in every entry.\n",
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def decode_project_path(encoded_name: str) -> str:
    decoded = unquote(encoded_name)
    if os.name == "nt":
        return decoded.replace("/", "\\")
    return decoded


def encode_project_path(project_path: str) -> str:
    normalized = project_path.replace("\\", "/")
    from urllib.parse import quote

    return quote(normalized, safe="")


def read_jsonl_records(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            try:
                yield line_no, json.loads(line), None
            except json.JSONDecodeError as exc:
                yield line_no, None, str(exc)


def read_session_summary(session_dir: Path) -> dict[str, Any]:
    summary_path = session_dir / "summary.json"
    if not summary_path.exists():
        return {}
    try:
        data = json.loads(read_text(summary_path))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def discover_session_dirs(project_filter: str = "") -> list[tuple[Path, Path, str]]:
    discovered: list[tuple[Path, Path, str]] = []
    if not SESSIONS_ROOT.exists():
        return discovered
    filter_lower = project_filter.lower().replace("\\", "/") if project_filter else ""
    for project_dir in sorted(SESSIONS_ROOT.iterdir()):
        if not project_dir.is_dir():
            continue
        project_path = decode_project_path(project_dir.name)
        if filter_lower and filter_lower not in project_path.replace("\\", "/").lower():
            continue
        for session_dir in sorted(project_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            if not SESSION_ID_REGEX.match(session_dir.name):
                continue
            chat_history = session_dir / "chat_history.jsonl"
            if not chat_history.exists():
                continue
            discovered.append((session_dir, chat_history, project_path))
    return discovered


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


def extract_grok_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text") is not None:
                parts.append(str(item.get("text")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def normalize_user_message(text: str, counters: Counter) -> str:
    message = (text or "").strip()
    if not message:
        return ""
    match = USER_QUERY_REGEX.search(message)
    if match:
        extracted = match.group(1).strip()
        if extracted:
            counters["trimmed_context_messages"] += 1
            return extracted
    if message.startswith("<user_info>") or "<git_status>" in message[:800]:
        counters["ignored_context_messages"] += 1
        return ""
    if len(message) > 6000 and ("<rules>" in message or "always_applied_workspace_rules" in message):
        counters["ignored_context_messages"] += 1
        return ""
    return message


def summarize_tool_call(name: str, args: Any) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return f"{name}: {args[:200]}"
    if not isinstance(args, dict):
        return name
    if args.get("command"):
        return f"{name}: {str(args['command'])[:200]}"
    for key in ("path", "query", "pattern", "url", "glob_pattern", "search_term"):
        if key in args:
            return f"{name}: {str(args[key])[:200]}"
    args_str = json.dumps(args, ensure_ascii=False)
    if args_str and args_str != "{}":
        return f"{name}: {args_str[:200]}"
    return name


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


def parse_grok_session(chat_history_path: Path, summary: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    summary = summary or {}
    info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
    session_id = str(info.get("id") or chat_history_path.parent.name)
    meta: dict[str, Any] = {
        "session_id": session_id,
        "source_path": str(chat_history_path),
        "session_dir": str(chat_history_path.parent),
        "cwd": info.get("cwd") or summary.get("git_root_dir") or "",
        "title": summary.get("generated_title") or summary.get("session_summary") or "",
        "created_at": summary.get("created_at") or "",
        "updated_at": summary.get("updated_at") or summary.get("last_active_at") or "",
        "model_id": summary.get("current_model_id") or "",
        "agent_name": summary.get("agent_name") or "",
        "git_branch": summary.get("head_branch") or "",
        "git_commit": summary.get("head_commit") or "",
        "num_messages": summary.get("num_messages") or 0,
    }
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counters: Counter = Counter()

    def start_turn() -> dict[str, Any]:
        nonlocal current
        if current and (current["user_messages"] or current["assistant_updates"] or current["command_outputs"]):
            current = None
        current = make_turn(f"turn-{len(turns) + 1}", cwd=str(meta.get("cwd") or ""))
        turns.append(current)
        return current

    for line_no, obj, error in read_jsonl_records(chat_history_path):
        if error:
            counters["invalid_json_lines"] += 1
            continue
        if not isinstance(obj, dict):
            continue
        record_type = obj.get("type")
        if record_type == "system":
            counters["system_messages"] += 1
            continue
        if record_type == "user":
            turn = start_turn()
            message = normalize_user_message(extract_grok_text(obj.get("content")), counters)
            if message:
                turn["user_messages"].append(message)
            continue
        if current is None:
            current = make_turn(f"turn-{len(turns) + 1}", cwd=str(meta.get("cwd") or ""))
            turns.append(current)
        turn = current
        if record_type == "reasoning":
            if obj.get("encrypted_content"):
                counters["encrypted_reasoning"] += 1
            summaries = obj.get("summary") or []
            if isinstance(summaries, list):
                for item in summaries:
                    if isinstance(item, dict) and item.get("type") == "summary_text" and item.get("text"):
                        turn["system_events"].append(f"reasoning: {str(item['text'])[:240]}")
            continue
        if record_type == "assistant":
            text = str(obj.get("content") or "").strip()
            if text:
                turn["assistant_updates"].append(text)
            for tool_call in obj.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                name = str(tool_call.get("name") or "unknown")
                args = tool_call.get("arguments")
                turn["commands"].append({
                    "name": name,
                    "arguments": args,
                    "summary": summarize_tool_call(name, args),
                    "tool_call_id": tool_call.get("id"),
                })
                counters["tool_calls"] += 1
            continue
        if record_type == "tool_result":
            output = extract_grok_text(obj.get("content"))
            if output.strip():
                turn["command_outputs"].append({"output": output, "tool_call_id": obj.get("tool_call_id")})
                counters["tool_results"] += 1
            continue
        counters["unknown_record_types"] += 1
        turn["system_events"].append(f"{record_type}: {str(obj)[:200]}")

    if turns and turns[-1]["assistant_updates"]:
        turns[-1]["final_answers"].append(turns[-1]["assistant_updates"][-1])

    return meta, turns, dict(counters)


def collect_file_refs(*texts: str) -> Counter:
    refs: Counter = Counter()
    for text in texts:
        for match in FILE_REF_REGEX.finditer(text or ""):
            ref = match.group("path")
            if ref.lower() in {"console.log"}:
                continue
            refs[ref] += 1
    return refs


def build_packet(session: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    chat_history_path = Path(session["file_path"])
    summary = read_session_summary(chat_history_path.parent)
    meta, turns, parse_counters = parse_grok_session(chat_history_path, summary)
    all_texts: list[str] = []
    clipped_text_blocks = 0
    clipped_outputs = 0
    lines = [
        f"# Grok Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        "",
        f"- Source: `{session['file_name']}`",
        f"- Session dir: `{session.get('session_dir', chat_history_path.parent)}`",
        f"- Project path: `{session.get('project_path', '')}`",
        f"- Size: {int(session.get('size_bytes', 0)) / 1024:.1f}KB",
        f"- Path: `{session['file_path']}`",
        f"- Queue status: `{session.get('status', 'new')}`",
        f"- Title: `{meta.get('title') or session.get('thread_name', '')}`",
        f"- CWD: `{meta.get('cwd', session.get('cwd', ''))}`",
        f"- Model: `{meta.get('model_id', '')}`",
        f"- Agent: `{meta.get('agent_name', '')}`",
        f"- Created: `{meta.get('created_at', session.get('timestamp', ''))}`",
        f"- Updated: `{meta.get('updated_at', '')}`",
    ]
    if meta.get("git_branch"):
        lines.append(f"- Git branch: `{meta.get('git_branch')}`")
    if meta.get("git_commit"):
        lines.append(f"- Git commit: `{meta.get('git_commit')}`")

    rendered_turns: list[list[str]] = []
    for index, turn in enumerate(turns, start=1):
        block = ["", f"## Turn {index}", "", f"- Turn id: `{turn.get('turn_id')}`"]
        if turn.get("cwd"):
            block.append(f"- CWD: `{turn['cwd']}`")
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
                summary = command.get("summary") or command.get("name")
                all_texts.append(str(summary))
                block.append(f"- `{summary}`")
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
    warnings: list[str] = []
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
        f"- Unique referenced files: {audit['unique_file_refs']}",
    ])
    for key in (
        "invalid_json_lines",
        "encrypted_reasoning",
        "ignored_context_messages",
        "trimmed_context_messages",
        "tool_calls",
        "tool_results",
    ):
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
        "- If `Coverage: partial`, inspect the raw `chat_history.jsonl` span before trusting clipped packet content.",
        "- `mark distilled` requires a session note and promotion decision.",
        "- Grok keeps live session state under `~/.grok/sessions`; raw files are kept unless `--delete-raw` is used.",
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
        f"3. Run `grok-session-distill mark {session['session_id']} distilled`.",
        "",
    ])
    return "\n".join(lines), audit


def cmd_index(project_filter: str = "") -> int:
    ensure_dirs()
    print("==> Index: scanning Grok sessions")
    manifest = load_manifest()
    previous = {entry["session_id"]: entry for entry in manifest.get("sessions", [])}
    refreshed: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()
    new_count = 0
    for session_dir, chat_history, project_path in discover_session_dirs(project_filter=project_filter):
        stat = chat_history.stat()
        session_id = session_dir.name
        seen_session_ids.add(session_id)
        summary = read_session_summary(session_dir)
        info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
        old = previous.get(session_id, {})
        status = old.get("status", "new")
        if status not in ALLOWED_STATUSES:
            status = "new"
        if not old:
            new_count += 1
            print(f"  + {session_id} ({stat.st_size / 1024:.1f}KB) [{project_path}]")
        refreshed.append({
            "session_id": session_id,
            "file_name": chat_history.name,
            "file_path": str(chat_history),
            "session_dir": str(session_dir),
            "project_path": project_path,
            "thread_name": summary.get("generated_title") or summary.get("session_summary") or old.get("thread_name", ""),
            "timestamp": summary.get("created_at") or "",
            "cwd": info.get("cwd") or summary.get("git_root_dir") or "",
            "model_id": summary.get("current_model_id") or "",
            "agent_name": summary.get("agent_name") or "",
            "size_bytes": stat.st_size,
            "last_write_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "status": status,
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
    manifest["input_dirs"] = [str(SESSIONS_ROOT)]
    manifest["output_dir"] = str(DISTILL_DIR)
    manifest["sessions"] = refreshed
    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions")
    return 0


def needs_bundle_refresh(session: dict[str, Any]) -> bool:
    return (
        session.get("bundle_source_last_write_time") != session.get("last_write_time")
        or session.get("bundle_source_size_bytes") != session.get("size_bytes")
    )


def cmd_bundle(next_count: int = 1, force: bool = False, session_ids: list[str] | None = None) -> int:
    ensure_dirs()
    manifest = load_manifest()
    wanted = set(session_ids or [])
    if wanted:
        pending = [
            s for s in manifest.get("sessions", [])
            if s.get("session_id") in wanted and (s.get("status") in {"new", "bundled"} or force)
        ]
        missing = sorted(wanted - {s.get("session_id") for s in pending})
        for session_id in missing:
            print(f"Session not bundleable: {session_id}")
    else:
        pending = [
            s for s in manifest.get("sessions", [])
            if s.get("status") == "new" or (s.get("status") == "bundled" and (force or needs_bundle_refresh(s)))
        ]
        if next_count > 0:
            pending = pending[:next_count]
    print("==> Bundle: generating packets")
    count = 0
    for session in pending:
        if session.get("status") not in {"new", "bundled"} and not force:
            continue
        packet_path = PACKETS_DIR / f"{session['session_id']}.md"
        print(f"  -> {session['session_id']}")
        session["status"] = "bundled"
        packet_text, _ = build_packet(session)
        packet_path.write_text(packet_text, encoding="utf-8")
        session["bundle_path"] = str(packet_path)
        session["bundle_source_last_write_time"] = session.get("last_write_time")
        session["bundle_source_size_bytes"] = session.get("size_bytes")
        count += 1
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> Bundle done: {count} packets")
    return 0


def cmd_run(next_count: int = 1, force: bool = False, session_ids: list[str] | None = None, project_filter: str = "") -> int:
    cmd_index(project_filter=project_filter)
    cmd_bundle(next_count=next_count, force=force, session_ids=session_ids)
    return cmd_status()


def cmd_status() -> int:
    ensure_dirs()
    manifest = load_manifest()
    sessions = manifest.get("sessions", [])
    counts = Counter(s.get("status", "new") for s in sessions)
    print("==> Grok Session Distiller Status")
    print("")
    print(
        "Sessions: "
        f"{len(sessions)} total | new={counts['new']} | bundled={counts['bundled']} | "
        f"distilled={counts['distilled']} | skipped={counts['skipped']}"
    )
    if counts["bundled"]:
        print("")
        print("Pending packets:")
        for session in sessions:
            if session.get("status") == "bundled":
                title = session.get("thread_name", "")
                print(f"  - {session['session_id']} {title}".rstrip())
    print("")
    print(f"Knowledge base: {KNOWLEDGE_FILE}")
    return 0


def cmd_list(min_size_kb: int = 0) -> int:
    ensure_dirs()
    cmd_index()
    manifest = load_manifest()
    for session in manifest.get("sessions", []):
        if int(session.get("size_bytes", 0)) >= min_size_kb * 1024:
            title = session.get("thread_name", "")
            project_path = session.get("project_path", "")
            print(
                f"{session['session_id']} | {session.get('status')} | "
                f"{int(session.get('size_bytes', 0)) / 1024:.1f}KB | {project_path} | {title}"
            )
    return 0


def packet_coverage(session_id: str) -> str:
    packet = PACKETS_DIR / f"{session_id}.md"
    if not packet.exists():
        return "missing"
    text = read_text(packet)
    if "Coverage: `partial`" in text:
        return "partial"
    if "Coverage: `high`" in text:
        return "high"
    return "unknown"


def validate_distilled(session_id: str) -> list[str]:
    errors: list[str] = []
    note_path = DISTILLED_DIR / f"{session_id}.md"
    packet_path = PACKETS_DIR / f"{session_id}.md"
    if not packet_path.exists():
        errors.append(f"packet missing: {packet_path}")
    if not note_path.exists():
        errors.append(f"session note missing: {note_path}")
        return errors
    note = read_text(note_path).lower()
    coverage = packet_coverage(session_id)
    if coverage == "partial" and not any(
        marker in note for marker in ["raw transcript", "raw jsonl", "raw review", "chat_history", "原始", "补看"]
    ):
        errors.append("partial packet requires raw transcript review note")
    if not any(
        marker in note for marker in ["promotion decision", "memory decision", "no promotion", "不提升", "知识", "promote"]
    ):
        errors.append("session note must record promotion/no-promotion decision")
    return errors


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
    if not is_under(raw_path, SESSIONS_ROOT):
        return False, f"refuse to delete raw file outside Grok sessions root: {raw_path}"
    raw_path.unlink()
    session["raw_deleted_at"] = now_iso()
    session["source_missing"] = True
    return True, f"deleted raw file: {raw_path}"


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
    for session in manifest.get("sessions", []):
        if session.get("session_id") != session_id:
            continue
        session["status"] = status
        if status == "distilled":
            session["distilled_path"] = str(DISTILLED_DIR / f"{session_id}.md")
            if delete_raw:
                deleted, message = delete_raw_source(session)
                print(f"==> {message}")
                if not deleted and not session.get("source_missing"):
                    return 1
            else:
                print("==> kept raw Grok session files (default). Use --delete-raw to remove chat_history.jsonl.")
        found = True
        break
    if not found:
        print(f"Session not found: {session_id}")
        return 1
    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> Marked {session_id} -> {status}")
    return 0


def cmd_prune(statuses: set[str] | None = None, source_missing_only: bool = True) -> int:
    ensure_dirs()
    manifest = load_manifest()
    statuses = statuses or {"distilled", "skipped"}
    before = len(manifest.get("sessions", []))
    pruned: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
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
    print("==> Grok Session Distiller Self-Test")
    test_dir = Path(__file__).resolve().parents[1] / "tests"
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"run", "bundle", "index", "status", "list", "mark", "prune", "self-test", "help"}
    command = "help"
    for index, token in enumerate(argv):
        if token in commands:
            command = token
            del argv[index]
            break
    parser = argparse.ArgumentParser(description="Grok Session Distiller")
    parser.add_argument("--next", type=int, default=1)
    parser.add_argument("--size", type=int, default=0)
    parser.add_argument("--project", type=str, default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delete-raw", action="store_true")
    parser.add_argument("--statuses", type=str, default="distilled,skipped")
    parser.add_argument("--all-pruned", action="store_true")
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
    if command == "index":
        return cmd_index(project_filter=args.project)
    if command == "run":
        return cmd_run(args.next, args.force, session_ids=args.args, project_filter=args.project)
    if command == "bundle":
        return cmd_bundle(args.next, args.force, session_ids=args.args)
    if command == "prune":
        statuses = {item.strip() for item in args.statuses.split(",") if item.strip()}
        return cmd_prune(statuses=statuses, source_missing_only=not args.all_pruned)
    if command == "mark":
        if len(args.args) < 2:
            print("Usage: grok-session-distill mark <session-id> <status>")
            return 1
        return cmd_mark(args.args[0], args.args[1], force=args.force, delete_raw=args.delete_raw)
    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())