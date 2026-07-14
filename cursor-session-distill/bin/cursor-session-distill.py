#!/usr/bin/env python3
"""Cursor session distiller for Cursor Composer SQLite conversations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unittest
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


# --- Paths ---
CURSOR_DB_PATH = Path(os.environ.get(
    "CURSOR_DB_PATH",
    Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
))
DISTILL_DIR = Path(os.environ.get(
    "CURSOR_DISTILL_DIR",
    Path.home() / ".cursor" / "session-distill",
))
MANIFEST_FILE = DISTILL_DIR / "cursor-manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
KB_REVIEW_STATE_FILE = DISTILL_DIR / "knowledge-review-state.json"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
DEFAULT_PROJECT_FILTER = "servers"
CURSOR_JSONL_TRANSCRIPTS_DIR = Path.home() / ".cursor" / "projects" / "e-project-servers" / "agent-transcripts"

# --- Limits (Deep Distill default: high clip, overridable via env) ---
TEXT_LIMIT = int(os.environ.get("CURSOR_DISTILL_TEXT_LIMIT", "32000"))
OUTPUT_LIMIT = int(os.environ.get("CURSOR_DISTILL_OUTPUT_LIMIT", "32000"))
OUTPUT_LINE_LIMIT = int(os.environ.get("CURSOR_DISTILL_OUTPUT_LINE_LIMIT", "120"))
FILE_REF_LIMIT = 30
KB_REVIEW_THRESHOLD = 5
KB_HIT_KEYWORD_MIN = 2
ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped", "pending_redistill"}

# --- Regexes ---
FILE_REF_REGEX = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|\.{1,2}[\\/])?[A-Za-z0-9_.\\/\-]+?\.(?:"
    r"md|markdown|ya?ml|jsonl?|tsx|jsx|mjs|cjs|ts|js|py|ps1|sh|bat|cmd|sql|"
    r"env|txt|log|html|css|scss|csv|tsv"
    r"))(?::\d+)?",
    re.IGNORECASE,
)
WORD_REGEX = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[一-鿿]{2,}")
KB_SOURCE_REGEX = re.compile(r"Source:\s*`(?P<session_id>[0-9a-f\-]{36})`\.?$", re.IGNORECASE)
KB_VOLATILE_MARKERS = (
    "temporary", "one-off", "workaround", "临时", "一次性",
    "端口", "pid", "timestamp", "branch", "backup",
)
KB_VOLATILE_REGEXES = tuple(
    re.compile(rf"(?<![A-Za-z0-9_]){re.escape(marker)}(?![A-Za-z0-9_])", re.IGNORECASE)
    for marker in KB_VOLATILE_MARKERS
)
KB_STABLE_HINTS = (
    "always", "do not", "prefer", "should", "must", "verify", "wrap", "when",
    "如果", "当", "应", "需要", "不要",
)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


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
        save_manifest({"version": 1, "updated_at": "", "input_db": str(CURSOR_DB_PATH), "sessions": []})
    if not KB_REVIEW_STATE_FILE.exists():
        KB_REVIEW_STATE_FILE.write_text(
            json.dumps({"last_reviewed_entry_count": 0, "last_reviewed_at": ""}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


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


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest() -> dict[str, Any]:
    if MANIFEST_FILE.exists():
        return json.loads(read_text(MANIFEST_FILE))
    return {"version": 1, "updated_at": "", "input_db": str(CURSOR_DB_PATH), "sessions": []}


def save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# KB review state
# ---------------------------------------------------------------------------

def load_kb_review_state() -> dict[str, Any]:
    ensure_dirs()
    return json.loads(read_text(KB_REVIEW_STATE_FILE))


def save_kb_review_state(state: dict[str, Any]) -> None:
    KB_REVIEW_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# SQLite access
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    if not CURSOR_DB_PATH.exists():
        print(f"Error: Cursor database not found at {CURSOR_DB_PATH}")
        sys.exit(1)
    uri = f"file:{CURSOR_DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def get_composer_headers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'")
    row = cursor.fetchone()
    if not row:
        return []
    data = json.loads(row[0])
    return data.get("allComposers", [])


def get_composer_data(conn: sqlite3.Connection, composer_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    key = f"composerData:{composer_id}"
    cursor.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (key,))
    row = cursor.fetchone()
    if not row:
        return None
    return json.loads(row[0])


def get_bubble(conn: sqlite3.Connection, composer_id: str, bubble_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    key = f"bubbleId:{composer_id}:{bubble_id}"
    cursor.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (key,))
    row = cursor.fetchone()
    if not row:
        return None
    return json.loads(row[0])


# ---------------------------------------------------------------------------
# Status inference
# ---------------------------------------------------------------------------

def infer_status(header: dict[str, Any], composer_id: str = "") -> str:
    """Infer conversation status from Cursor header fields.

    Cursor composerHeaders have no explicit status field.
    Rules:
    - isDraft -> 'draft'
    - has lastUpdatedTime and not isDraft -> 'completed'
    - otherwise -> 'unknown'
    - If the session exists in SQLite but has 0 bubbles AND has a JSONL
      transcript, mark as 'archived-jsonl'
    """
    if header.get("isDraft"):
        return "draft"
    if header.get("lastUpdatedTime"):
        return "completed"
    # Check for archived session with JSONL fallback
    if composer_id:
        jsonl_path = CURSOR_JSONL_TRANSCRIPTS_DIR / composer_id / f"{composer_id}.jsonl"
        if jsonl_path.exists():
            return "archived-jsonl"
    return "unknown"


# ---------------------------------------------------------------------------
# Text / content extraction
# ---------------------------------------------------------------------------

def extract_lexical_text(node: Any, depth: int = 0) -> str:
    if depth > 20:
        return ""
    text = ""
    if isinstance(node, dict):
        if "text" in node and isinstance(node["text"], str):
            text += node["text"]
        if node.get("type") == "mention":
            mention_text = node.get("text", "")
            if mention_text:
                text += mention_text
        for child in node.get("children", []):
            text += extract_lexical_text(child, depth + 1)
        if node.get("type") == "paragraph" and text:
            text += "\n"
    elif isinstance(node, list):
        for item in node:
            text += extract_lexical_text(item, depth + 1)
    return text


def extract_user_text(bubble: dict[str, Any]) -> str:
    text = bubble.get("text", "")
    if not text:
        rich = bubble.get("richText", "")
        if rich:
            try:
                rich_data = json.loads(rich) if isinstance(rich, str) else rich
                text = extract_lexical_text(rich_data)
            except (json.JSONDecodeError, TypeError):
                text = str(rich)[:500]
    return text.strip()


def extract_assistant_text(bubble: dict[str, Any]) -> str:
    text = bubble.get("text", "")
    return text.strip() if text else ""


def extract_tool_calls(bubble: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool call information from bubble's toolFormerData.

    Cursor stores tool call data in toolFormerData. Arguments may be in:
    - rawArgs (string, possibly JSON) -> look for command, path, query, pattern
    - args (nested object) -> look at first-level keys for command/path/etc.
    - rawArgs.command (for shell tools)
    """
    tool_data = bubble.get("toolFormerData", {})
    if not tool_data:
        return []

    # toolFormerData can be a single dict or a list
    if isinstance(tool_data, list):
        items = tool_data
    else:
        items = [tool_data]

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("name", "unknown")

        # Parse rawArgs
        raw_args = item.get("rawArgs", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except (json.JSONDecodeError, TypeError):
            args = {}

        # Also check the args field (some tools store structured args here)
        structured_args = item.get("args", {})
        if isinstance(structured_args, dict) and structured_args:
            if not isinstance(args, dict) or not args:
                args = structured_args
            else:
                # Merge: structured_args may have deeper info
                for k, v in structured_args.items():
                    if k not in args:
                        args[k] = v

        # Summarize based on known patterns
        summary = tool_name
        command = None
        if isinstance(args, dict):
            command = args.get("command")
            if command:
                summary = f"{tool_name}: {command[:200]}"
            elif "path" in args:
                path_val = args["path"]
                summary = f"{tool_name}: {path_val}"
            elif "query" in args:
                summary = f"{tool_name}: {str(args['query'])[:120]}"
            elif "pattern" in args:
                summary = f"{tool_name}: {args['pattern']}"
            elif "filePath" in args:
                summary = f"{tool_name}: {args['filePath']}"
            elif "searchQuery" in args:
                summary = f"{tool_name}: {args['searchQuery'][:120]}"
            elif "filePaths" in args:
                paths = args["filePaths"]
                if isinstance(paths, list):
                    summary = f"{tool_name}: {', '.join(str(p) for p in paths[:5])}"
                else:
                    summary = f"{tool_name}: {str(paths)[:120]}"
            else:
                # Generic: show first 200 chars of args
                args_str = json.dumps(args, ensure_ascii=False) if args else ""
                if args_str and args_str != "{}":
                    summary = f"{tool_name}: {args_str[:200]}"

        results.append({
            "name": tool_name,
            "arguments": args,
            "summary": summary,
            "command": command,
        })

    return results


def extract_code_blocks(bubble: dict[str, Any]) -> list[dict[str, str]]:
    blocks = bubble.get("codeBlocks", [])
    if not blocks:
        return []
    result = []
    for block in blocks:
        content = block.get("content", "")
        lang = block.get("languageId", "")
        if content:
            if len(content) > 800:
                content = content[:800] + "\n... (truncated)"
            result.append({"language": lang, "content": content})
    return result


# ---------------------------------------------------------------------------
# File reference extraction
# ---------------------------------------------------------------------------

def collect_file_refs(*texts: str) -> Counter:
    refs: Counter = Counter()
    for text in texts:
        for match in FILE_REF_REGEX.finditer(text or ""):
            ref = match.group("path")
            # Filter false positives
            lower = ref.lower()
            if lower in {"console.log", "index.js", "index.ts"}:
                continue
            refs[ref] += 1
    return refs


# ---------------------------------------------------------------------------
# Conversation reconstruction & JSONL fallback
# ---------------------------------------------------------------------------

def reconstruct_from_jsonl(composer_id: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reconstruct conversation from Cursor JSONL agent transcript.

    Looks for {CURSOR_JSONL_TRANSCRIPTS_DIR}/{composer_id}/{composer_id}.jsonl.
    Each line is a JSON object with 'role' (user/assistant) and 'message'.
    message.content is a list of items with type: text, tool_use, or tool_result.

    Returns (turns, counters) with the same format as reconstruct_conversation.
    """
    jsonl_path = CURSOR_JSONL_TRANSCRIPTS_DIR / composer_id / f"{composer_id}.jsonl"
    if not jsonl_path.exists():
        return [], {"missing_jsonl": 1}

    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counters: dict[str, int] = Counter()

    def ensure_turn() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = make_turn(f"turn-{len(turns)+1}")
            turns.append(current)
        return current

    try:
        lines = read_text(jsonl_path).splitlines()
    except Exception:
        return [], {"jsonl_read_error": 1}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg_obj = json.loads(line)
        except json.JSONDecodeError:
            counters["jsonl_parse_errors"] = counters.get("jsonl_parse_errors", 0) + 1
            continue

        role = msg_obj.get("role", "")
        message = msg_obj.get("message", {})
        content_items = message.get("content", [])
        if isinstance(content_items, str):
            content_items = [{"type": "text", "text": content_items}]

        # Determine if this is a tool_result message
        is_tool_result = role == "user" and any(
            isinstance(item, dict) and item.get("type") == "tool_result"
            for item in content_items
        )

        if is_tool_result:
            # Tool result - add to current turn's command_outputs
            if current is None:
                current = ensure_turn()
            for item in content_items:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    output_content = item.get("content", "")
                    if isinstance(output_content, list):
                        output_text = ""
                        for sub in output_content:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                output_text += sub.get("text", "")
                            else:
                                output_text += str(sub)
                    else:
                        output_text = str(output_content) if output_content else ""
                    if output_text.strip():
                        current["command_outputs"].append({"output": output_text})
                        counters["tool_results"] += 1

        elif role == "user":
            # User message - start new turn
            if current and (current["user_messages"] or current["assistant_updates"]):
                current = None
            turn = ensure_turn()

            for item in content_items:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "").strip()
                    if text:
                        turn["user_messages"].append(text)

        elif role == "assistant":
            # Assistant message
            turn = ensure_turn()

            for item in content_items:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text = item.get("text", "").strip()
                        if text:
                            turn["assistant_updates"].append(text)
                            counters["assistant_texts"] += 1

                    elif item.get("type") == "tool_use":
                        tool_name = item.get("name", "unknown")
                        tool_input = item.get("input", {})

                        # Build summary same way as extract_tool_calls
                        summary = tool_name
                        command_val = None
                        if isinstance(tool_input, dict):
                            command_val = tool_input.get("command")
                            if command_val:
                                summary = f"{tool_name}: {str(command_val)[:200]}"
                            elif "path" in tool_input:
                                summary = f"{tool_name}: {tool_input['path']}"
                            elif "query" in tool_input:
                                summary = f"{tool_name}: {str(tool_input['query'])[:120]}"
                            elif "pattern" in tool_input:
                                summary = f"{tool_name}: {tool_input['pattern']}"
                            elif "filePath" in tool_input:
                                summary = f"{tool_name}: {tool_input['filePath']}"
                            elif "searchQuery" in tool_input:
                                summary = f"{tool_name}: {tool_input['searchQuery'][:120]}"
                            else:
                                args_str = json.dumps(tool_input, ensure_ascii=False)[:200]
                                if args_str and args_str != "{}":
                                    summary = f"{tool_name}: {args_str}"

                        turn["commands"].append({
                            "name": tool_name,
                            "arguments": tool_input,
                            "summary": summary,
                            "command": command_val,
                        })
                        counters["tool_calls"] += 1

    if not turns:
        return [], {"jsonl_no_turns": 1}

    return turns, dict(counters)


def reconstruct_with_fallback(conn: sqlite3.Connection, composer_id: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reconstruct conversation with JSONL fallback for archived sessions.

    1. Tries SQLite conversation reconstruction first.
    2. If SQLite returns empty turns due to missing bubbles, falls back to JSONL.
    3. Returns (turns, counters) from whichever source succeeded.
    """
    turns, counters = reconstruct_conversation(conn, composer_id)

    # Fallback to JSONL if SQLite had missing bubbles and no useful turns
    if not turns and counters.get("missing_bubbles", 0) > 0:
        jsonl_turns, jsonl_counters = reconstruct_from_jsonl(composer_id)
        if jsonl_turns:
            jsonl_counters["source"] = "jsonl_fallback"
            jsonl_counters["sqlite_missing_bubbles"] = counters.get("missing_bubbles", 0)
            return jsonl_turns, jsonl_counters

    return turns, counters


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


def reconstruct_conversation(conn: sqlite3.Connection, composer_id: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reconstruct full conversation flow for a composer.

    Returns (turns, counters).
    """
    composer_data = get_composer_data(conn, composer_id)
    if not composer_data:
        return [], {"missing_composer_data": 1}

    headers = composer_data.get("fullConversationHeadersOnly", [])
    if not headers:
        return [], {"empty_conversation": 1}

    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counters: dict[str, int] = Counter()

    def ensure_turn(timestamp: str = "") -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = make_turn(f"turn-{len(turns)+1}", timestamp=timestamp)
            turns.append(current)
        return current

    for header in headers:
        bubble_id = header.get("bubbleId")
        bubble_type = header.get("type")  # 1=user, 2=assistant

        bubble = get_bubble(conn, composer_id, bubble_id)
        if not bubble:
            counters["missing_bubbles"] += 1
            continue

        if bubble_type == 1:
            # User message - start new turn
            if current and (current["user_messages"] or current["assistant_updates"]):
                current = None  # force new turn
            turn = ensure_turn()

            text = extract_user_text(bubble)
            if text:
                turn["user_messages"].append(text)

        elif bubble_type == 2:
            # Assistant message
            turn = ensure_turn()

            text = extract_assistant_text(bubble)
            if text:
                # Heuristic: if it's long and at the end of the turn, treat as final answer
                turn["assistant_updates"].append(text)

            # Tool calls
            tool_calls = extract_tool_calls(bubble)
            for tc in tool_calls:
                turn["commands"].append(tc)
                counters["tool_calls"] += 1

            # Code blocks
            blocks = extract_code_blocks(bubble)
            for block in blocks:
                counters["code_blocks"] += 1
                # Store code blocks as pseudo-patches for the audit
                turn["patches"].append(f"[{block['language']}] {block['content'][:300]}")

    # Ensure last turn is appended
    if current and (current["user_messages"] or current["assistant_updates"]):
        pass  # already in turns

    return turns, dict(counters)


# ---------------------------------------------------------------------------
# Packet generation
# ---------------------------------------------------------------------------

def build_packet(session: dict[str, Any], conn: sqlite3.Connection) -> tuple[str, dict[str, Any]]:
    """Generate Markdown packet from conversation data, aligned with Codex format."""
    composer_id = session["session_id"]
    header = session.get("_header", {})

    turns, parse_counters = reconstruct_with_fallback(conn, composer_id)

    name = header.get("name", "Untitled")
    created_ms = header.get("createdAt", 0)
    created_dt = (
        datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if created_ms
        else "unknown"
    )
    last_updated_ms = header.get("lastUpdatedTime", 0)
    last_updated_dt = (
        datetime.fromtimestamp(last_updated_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if last_updated_ms
        else ""
    )
    unified_mode = header.get("unifiedMode", "unknown")
    status = infer_status(header, composer_id=composer_id)
    lines_added = header.get("totalLinesAdded", 0)
    lines_removed = header.get("totalLinesRemoved", 0)
    files_changed = header.get("filesChangedCount", 0)
    is_archived = header.get("isArchived", False)
    workspace = header.get("workspaceIdentifier", {}).get("uri", {}).get("fsPath", "")

    # Determine the source label
    source_label = parse_counters.get("source", "")
    if source_label == "jsonl_fallback":
        source_line = f"- Source: `Cursor JSONL transcript` (SQLite had {parse_counters.get('sqlite_missing_bubbles', '?')} missing bubbles)"
    else:
        source_line = f"- Source: `Cursor SQLite ({CURSOR_DB_PATH.name})`"

    all_texts: list[str] = []
    clipped_text_blocks = 0
    clipped_outputs = 0

    lines: list[str] = []
    lines.extend([
        f"# Cursor Session Packet: {composer_id}",
        "",
        "## Metadata",
        "",
        source_line,
        f"- Composer ID: `{composer_id}`",
        f"- Name: {name}",
        f"- Created: `{created_dt}`",
        f"- Last Updated: `{last_updated_dt}`" if last_updated_dt else "- Last Updated: (none)",
        f"- Mode: `{unified_mode}`",
        f"- Status: `{status}`",
        f"- Lines: +{lines_added}/-{lines_removed}",
        f"- Files Changed: {files_changed}",
        f"- Archived: {is_archived}",
        f"- Workspace: `{workspace}`" if workspace else "- Workspace: (unknown)",
        f"- Turns: {len(turns)}",
        f"- Queue status: `{session.get('status', 'new')}`",
    ])

    # Render turns
    rendered_turns: list[list[str]] = []
    for index, turn in enumerate(turns, start=1):
        block = ["", f"## Turn {index}", "", f"- Turn id: `{turn.get('turn_id')}`"]
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

    # File references
    refs = collect_file_refs(*all_texts)

    # Warnings
    warnings: list[str] = []
    if clipped_text_blocks:
        warnings.append(f"{clipped_text_blocks} text block(s) clipped at {TEXT_LIMIT} chars.")
    if clipped_outputs:
        warnings.append(f"{clipped_outputs} command output excerpt(s) clipped.")
    if len(refs) > FILE_REF_LIMIT:
        warnings.append(f"Referenced Files shows only top {FILE_REF_LIMIT} of {len(refs)} paths.")
    if parse_counters.get("missing_bubbles"):
        warnings.append(f"Missing bubble data: {parse_counters['missing_bubbles']} bubble(s).")
    if parse_counters.get("missing_composer_data"):
        warnings.append("Composer data missing entirely.")

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

    # Packet Audit
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
    for key in ("missing_bubbles", "missing_composer_data", "empty_conversation", "tool_calls", "code_blocks", "tool_results", "missing_jsonl", "jsonl_read_error", "jsonl_parse_errors", "jsonl_no_turns", "assistant_texts"):
        if audit.get(key):
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {audit[key]}")
    source_label = parse_counters.get("source", "")
    if source_label == "jsonl_fallback":
        lines.append(f"- JSONL sqlite_missing_bubbles: {parse_counters.get('sqlite_missing_bubbles', '?')}")
    if warnings:
        lines.extend(["", "### Audit Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    # Distillation Reminder
    lines.extend([
        "",
        "## Distillation Reminder",
        "",
        "- Read `references/distillation-rules.md` before promotion.",
        "- If `Coverage: partial`, inspect the raw SQLite data before trusting clipped packet content.",
        "- `mark distilled` will require a session note and promotion decision.",
    ])

    # Referenced Files
    if refs:
        lines.extend(["", "## Referenced Files", ""])
        for ref, count in refs.most_common(FILE_REF_LIMIT):
            lines.append(f"- `{ref}` ({count})")

    # Turns
    for block in rendered_turns:
        lines.extend(block)

    # Suggested Next Step
    lines.extend([
        "",
        "## Suggested Next Step",
        "",
        f"1. Write `distilled/sessions/{composer_id}.md`.",
        "2. Record `Promotion Decision` or `No Promotion` in the note.",
        f"3. Run `cursor-session-distill mark {composer_id} distilled`.",
        "",
    ])

    return "\n".join(lines), audit


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

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
    return {token for token in keywords if token not in {
        "source", "when", "then", "with", "that", "this", "from", "then", "will", "code",
    }}


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
            "Run `cursor-session-distill review-kb --next 20`."
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
        manifest = load_manifest()
        session = next(
            (s for s in manifest.get("sessions", []) if s.get("session_id") == session_id),
            None,
        )
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


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def packet_coverage(session_id: str) -> str:
    packet = PACKETS_DIR / f"cursor-{session_id}.md"
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


def validate_distilled(session_id: str) -> list[str]:
    errors: list[str] = []
    note_path = DISTILLED_DIR / f"{session_id}.md"
    packet_path = PACKETS_DIR / f"cursor-{session_id}.md"
    if not packet_path.exists():
        errors.append(f"packet missing: {packet_path}")
    if not note_path.exists():
        errors.append(f"session note missing: {note_path}")
        return errors
    note = read_text(note_path).lower()
    coverage = packet_coverage(session_id)
    if coverage == "partial" and not any(
        marker in note for marker in ["raw transcript", "raw jsonl", "raw review", "原始", "补看"]
    ):
        errors.append("partial packet requires raw transcript review note")
    errors.extend(validate_final_review(read_text(note_path)))
    if not any(
        marker in note for marker in ["promotion decision", "memory decision", "no promotion", "不提升", "知识", "promote"]
    ):
        errors.append("session note must record promotion/no-promotion decision")
    kb_entries = load_kb_entries()
    sourced_entries = [entry for entry in kb_entries if entry.get("session_id") == session_id]
    for entry in sourced_entries:
        status, reasons = assess_kb_entry(entry, current_session_id=session_id)
        if status == "needs-review":
            errors.append(f"knowledge entry needs review: {entry['text']} ({'; '.join(reasons)})")
    return errors


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_index() -> int:
    ensure_dirs()
    print("==> Index: scanning Cursor Composer sessions")
    manifest = load_manifest()
    previous = {entry["session_id"]: entry for entry in manifest.get("sessions", [])}

    conn = get_db_connection()
    try:
        headers = get_composer_headers(conn)
    finally:
        conn.close()

    refreshed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    new_count = 0

    for header in headers:
        # Skip drafts
        if header.get("isDraft"):
            continue

        composer_id = header.get("composerId", "")
        if not composer_id:
            continue
        seen_ids.add(composer_id)

        created_ms = header.get("createdAt", 0)
        last_updated_ms = header.get("lastUpdatedTime", 0)
        name = header.get("name", "Untitled")
        workspace = header.get("workspaceIdentifier", {}).get("uri", {}).get("fsPath", "")
        status_inferred = infer_status(header, composer_id=composer_id)

        old = previous.get(composer_id, {})
        last_updated_iso = (
            datetime.fromtimestamp(last_updated_ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if last_updated_ms else ""
        )
        source_fp_hash = compute_source_fingerprint({
            "last_updated_at": last_updated_iso,
            "lines_added": header.get("totalLinesAdded", 0),
            "lines_removed": header.get("totalLinesRemoved", 0),
            "files_changed_count": header.get("filesChangedCount", 0),
        })
        queue_status = compute_queue_status_on_index(
            old,
            source_fingerprint=source_fp_hash,
            current_revision_id=old.get("current_revision_id"),
        )

        if not old:
            new_count += 1
            print(f"  + {composer_id[:16]}... {name[:50]}")

        refreshed.append({
            "session_id": composer_id,
            "name": name,
            "workspace": workspace,
            "cursor_status": status_inferred,
            "is_archived": header.get("isArchived", False),
            "created_at": (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if created_ms else ""
            ),
            "last_updated_at": last_updated_iso,
            "lines_added": header.get("totalLinesAdded", 0),
            "lines_removed": header.get("totalLinesRemoved", 0),
            "files_changed_count": header.get("filesChangedCount", 0),
            "mode": header.get("unifiedMode", ""),
            "status": queue_status,
            "source_fingerprint": source_fp_hash,
            "last_indexed_fingerprint": source_fp_hash,
            "current_revision_id": old.get("current_revision_id"),
            "last_distilled_revision_id": old.get("last_distilled_revision_id"),
            "revision_path": old.get("revision_path"),
            "bundle_path": old.get("bundle_path"),
            "bundle_source_last_updated": old.get("bundle_source_last_updated"),
            "distilled_path": old.get("distilled_path"),
            "notes": old.get("notes", ""),
            "_header": header,
        })

    # Preserve entries that are no longer in DB but were distilled/skipped
    for session_id, old in previous.items():
        if session_id in seen_ids:
            continue
        if old.get("status") not in {"distilled", "skipped"}:
            continue
        preserved = dict(old)
        preserved["source_missing"] = True
        preserved.setdefault("source_missing_since", now_iso())
        preserved.pop("_header", None)
        refreshed.append(preserved)

    manifest["version"] = 1
    manifest["updated_at"] = now_iso()
    manifest["input_db"] = str(CURSOR_DB_PATH)
    manifest["sessions"] = refreshed
    save_manifest(manifest)
    print(f"==> Index done: {new_count} new sessions, {len(refreshed)} total")
    return 0


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
            or (s.get("status") == "bundled" and force)
        ]
        if next_count > 0:
            pending = pending[:next_count]

    print("==> Bundle: generating packets")
    conn = get_db_connection()
    count = 0
    try:
        for session in pending:
            if session.get("status") not in BUNDLEABLE_STATUSES and not force:
                continue
            session_id = session["session_id"]
            # Need header for metadata
            if "_header" not in session:
                # Try to get it from DB
                headers = get_composer_headers(conn)
                header = next((h for h in headers if h.get("composerId") == session_id), {})
                session["_header"] = header

            packet_path = PACKETS_DIR / f"cursor-{session_id}.md"
            print(f"  -> {session_id[:16]}... {session.get('name', '')[:40]}")

            turns, parse_counters = reconstruct_with_fallback(conn, session_id)
            source_fp = {
                "last_updated_at": session.get("last_updated_at"),
                "lines_added": session.get("lines_added"),
                "lines_removed": session.get("lines_removed"),
                "files_changed_count": session.get("files_changed_count"),
            }
            metadata = {
                **{k: v for k, v in session.items() if k != "_header"},
                "name": session.get("name") or session.get("_header", {}).get("name", ""),
                "workspace": session.get("workspace") or session.get("_header", {}).get("workspaceIdentifier", {}).get("uri", {}).get("fsPath", ""),
                "parse_counters": parse_counters,
            }
            revision_id, revision_dir, _audit = ingest_revision(
                DISTILL_DIR,
                session_id=session_id,
                platform="cursor",
                turns=turns,
                source_fingerprint=source_fp,
                metadata=metadata,
            )
            packet_path.write_text(read_text(revision_dir / "packet.md"), encoding="utf-8")

            session["status"] = "bundled"
            session["bundle_path"] = str(packet_path)
            session["bundle_source_last_updated"] = session.get("last_updated_at")
            session["current_revision_id"] = revision_id
            session["revision_path"] = str(revision_dir)

            print_kb_hit_reminder(read_text(packet_path), exclude_session_id=session_id, source_label=f"packet {session_id}")
            count += 1
    finally:
        conn.close()

    # Strip _header before saving (not serializable cleanly)
    for session in manifest.get("sessions", []):
        session.pop("_header", None)

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
    print("==> Cursor Session Distiller Status")
    print("")
    print(
        f"Sessions: {len(sessions)} total | "
        f"new={counts['new']} | bundled={counts['bundled']} | "
        f"pending_redistill={counts.get('pending_redistill', 0)} | "
        f"distilled={counts['distilled']} | skipped={counts['skipped']}"
    )
    if counts["bundled"]:
        print("")
        print("Pending packets:")
        for s in sessions:
            if s.get("status") == "bundled":
                print(f"  - {s['session_id'][:16]}... {s.get('name', '')}".rstrip())
    print("")
    print(f"Knowledge base: {KNOWLEDGE_FILE}")
    return 0


def cmd_list(project: str = "", verbose: bool = False) -> int:
    ensure_dirs()
    cmd_index()
    manifest = load_manifest()

    conn = get_db_connection()
    try:
        headers = get_composer_headers(conn)
    finally:
        conn.close()

    # Filter by project
    filtered = headers
    if project:
        filtered = [
            h for h in filtered
            if project.lower() in h.get("workspaceIdentifier", {}).get("uri", {}).get("fsPath", "").lower()
        ]

    # Skip drafts
    filtered = [h for h in filtered if not h.get("isDraft")]
    filtered.sort(key=lambda x: x.get("createdAt", 0), reverse=True)

    processed = {s["session_id"]: s for s in manifest.get("sessions", [])}

    print(f"Found {len(filtered)} conversations" + (f" for project '{project}'" if project else ""))
    print()

    # Status distribution (from manifest, not database)
    # manifest key is raw composerId (no prefix)
    statuses: dict[str, int] = {}
    for h in filtered:
        cid = h.get("composerId", "")
        s = processed.get(cid, {}).get("status", "new")
        statuses[s] = statuses.get(s, 0) + 1
    print("Status distribution:")
    for s in ALLOWED_STATUSES:
        count = statuses.get(s, 0)
        print(f"  {s}: {count}")

    archived_count = sum(1 for h in filtered if h.get("isArchived"))
    distilled_count = sum(
        1 for h in filtered
        if processed.get(h.get("composerId", ""), {}).get("status") == "distilled"
    )
    print(f"\nArchived: {archived_count}")
    print(f"Distilled: {distilled_count}")

    if verbose:
        print("\n--- Conversations ---")
        for h in filtered[:50]:
            cid = h.get("composerId", "?")
            name = h.get("name", "Untitled")[:50]
            created_ms = h.get("createdAt", 0)
            date = datetime.fromtimestamp(created_ms / 1000).strftime("%Y-%m-%d") if created_ms else "????-??-??"
            manifest_status = processed.get(cid, {}).get("status", "new")
            archived = "[A]" if h.get("isArchived") else "   "
            done = "[X]" if manifest_status == "distilled" else "   "
            print(f"  {done} {archived} {date} [{manifest_status:10}] {cid[:16]}... {name}")

    return 0


def cmd_mark(session_id: str, status: str, force: bool = False) -> int:
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


def cmd_prune(statuses: set[str] | None = None, source_missing_only: bool = True) -> int:
    ensure_dirs()
    manifest = load_manifest()
    statuses = statuses or {"distilled", "skipped"}
    before = len(manifest.get("sessions", []))
    pruned: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for session in manifest.get("sessions", []):
        s = session.get("status")
        source_missing = bool(session.get("source_missing"))
        if s in statuses and ((not source_missing_only) or source_missing):
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
    counts: Counter = Counter()
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
        f"needs-review={counts['needs-review']} | stale={counts['stale']}"
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


def cmd_self_test() -> int:
    print("==> Cursor Session Distiller Self-Test")
    test_dir = Path(__file__).resolve().parents[1] / "tests"
    if not test_dir.exists():
        print(f"Test directory not found: {test_dir}")
        print("Running inline smoke tests instead...")
        _run_smoke_tests()
        return 0
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _run_smoke_tests() -> None:
    """Basic smoke tests for core functions."""
    passed = 0
    failed = 0

    # Test clip_text
    short, c = clip_text("hello", 10)
    assert not c and short == "hello", f"clip_text short failed: {short!r}"
    long_text = "x" * 2000
    clipped, c = clip_text(long_text, TEXT_LIMIT)
    assert c and "[clipped]" in clipped, f"clip_text long failed"
    passed += 2

    # Test clip_output
    short_out, c = clip_output("line1\nline2")
    assert not c, f"clip_output short failed"
    long_out = "\n".join(f"line{i}" for i in range(30))
    clipped_out, c = clip_output(long_out)
    assert c and "[clipped]" in clipped_out, f"clip_output long failed"
    passed += 2

    # Test collect_file_refs
    refs = collect_file_refs("see src/main.ts and lib/utils.py")
    assert "src/main.ts" in refs and "lib/utils.py" in refs, f"collect_file_refs failed: {refs}"
    passed += 1

    # Test infer_status
    assert infer_status({"isDraft": True}) == "draft"
    assert infer_status({"lastUpdatedTime": 123, "isDraft": False}) == "completed"
    assert infer_status({}) == "unknown"
    assert infer_status({}, composer_id="nonexistent") == "unknown"
    passed += 3

    # Test extract_keywords
    kw = extract_keywords("TypeScript NestJS module boundary check")
    assert "typescript" in kw and "nestjs" in kw, f"extract_keywords failed: {kw}"
    passed += 1

    print(f"  Smoke tests: {passed} passed, {failed} failed")


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "run", "bundle", "status", "list", "mark", "prune",
        "review-kb", "prune-kb", "verify-entry", "self-test", "help",
    }
    command = "help"
    for index, token in enumerate(argv):
        if token in commands:
            command = token
            del argv[index]
            break

    parser = argparse.ArgumentParser(description="Cursor Session Distiller")
    parser.add_argument("--next", type=int, default=1)
    parser.add_argument("--project", type=str, default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--statuses", type=str, default="distilled,skipped")
    parser.add_argument("--all-pruned", action="store_true")
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("--verbose", "-v", action="store_true")
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
        return cmd_list(project=args.project, verbose=args.verbose)
    if command == "run":
        return cmd_run(args.next, args.force, session_ids=args.args)
    if command == "bundle":
        return cmd_bundle(args.next, args.force, session_ids=args.args)
    if command == "prune":
        statuses = {item.strip() for item in args.statuses.split(",") if item.strip()}
        return cmd_prune(statuses=statuses, source_missing_only=not args.all_pruned)
    if command == "review-kb":
        return cmd_review_kb(limit=args.next, query=args.query)
    if command == "prune-kb":
        statuses = {item.strip() for item in args.statuses.split(",") if item.strip()}
        return cmd_prune_kb(query=args.query, remove_statuses=statuses)
    if command == "verify-entry":
        query = args.query or (args.args[0] if args.args else "")
        if not query:
            print("Usage: cursor-session-distill verify-entry <session-id|keyword>")
            return 1
        return cmd_verify_entry(query)
    if command == "mark":
        if len(args.args) < 2:
            print("Usage: cursor-session-distill mark SESSION-ID STATUS")
            return 1
        return cmd_mark(args.args[0], args.args[1], force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
