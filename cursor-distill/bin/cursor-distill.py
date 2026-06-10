#!/usr/bin/env python3
"""
Cursor Conversation Distiller

Extracts knowledge from Cursor Composer conversations stored in SQLite.
Compatible with session-distill workflow.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone


# --- Constants ---
CURSOR_DB_PATH = os.path.expanduser("~/AppData/Roaming/Cursor/User/globalStorage/state.vscdb")
PACKET_OUTPUT_DIR = os.path.expanduser("~/.claude/session-distill/packets")
DISTILLED_DIR = os.path.expanduser("~/.claude/session-distill/distilled/sessions")
MANIFEST_PATH = os.path.expanduser("~/.claude/session-distill/cursor-manifest.json")

# Status file for tracking processed conversations
DEFAULT_PROJECT_FILTER = "servers"


def get_db_connection():
    """Connect to Cursor SQLite database (read-only)."""
    if not os.path.exists(CURSOR_DB_PATH):
        print(f"Error: Cursor database not found at {CURSOR_DB_PATH}")
        sys.exit(1)
    # Use immutable mode for safe read-only access
    uri = f"file:{CURSOR_DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def load_manifest():
    """Load or create manifest for tracking processed conversations."""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed": {}, "version": 1}


def save_manifest(manifest):
    """Save manifest to disk."""
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def get_composer_headers(conn):
    """Get all composer headers from ItemTable."""
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'")
    row = cursor.fetchone()
    if not row:
        return []
    data = json.loads(row[0])
    return data.get("allComposers", [])


def filter_conversations(headers, project=None, status=None, archived=None):
    """Filter conversations by project, status, archived state."""
    filtered = []
    for h in headers:
        # Project filter
        if project:
            ws = h.get("workspaceIdentifier", {})
            fs_path = ws.get("uri", {}).get("fsPath", "")
            if project.lower() not in fs_path.lower():
                continue

        # Status filter
        if status and h.get("status") != status:
            continue

        # Archived filter
        if archived is not None and h.get("isArchived") != archived:
            continue

        # Skip drafts
        if h.get("isDraft"):
            continue

        filtered.append(h)

    # Sort by createdAt descending (newest first)
    filtered.sort(key=lambda x: x.get("createdAt", 0), reverse=True)
    return filtered


def get_composer_data(conn, composer_id):
    """Get composerData for a specific conversation."""
    cursor = conn.cursor()
    key = f"composerData:{composer_id}"
    cursor.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (key,))
    row = cursor.fetchone()
    if not row:
        return None
    return json.loads(row[0])


def get_bubble(conn, composer_id, bubble_id):
    """Get a specific bubble message."""
    cursor = conn.cursor()
    key = f"bubbleId:{composer_id}:{bubble_id}"
    cursor.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (key,))
    row = cursor.fetchone()
    if not row:
        return None
    return json.loads(row[0])


def extract_user_text(bubble):
    """Extract user message text from bubble."""
    text = bubble.get("text", "")
    if not text:
        # Try richText
        rich = bubble.get("richText", "")
        if rich:
            try:
                rich_data = json.loads(rich) if isinstance(rich, str) else rich
                # Extract text from Lexical JSON
                text = extract_lexical_text(rich_data)
            except (json.JSONDecodeError, TypeError):
                text = str(rich)[:500]
    return text.strip()


def extract_lexical_text(node, depth=0):
    """Recursively extract text from Lexical JSON format."""
    if depth > 20:
        return ""
    text = ""
    if isinstance(node, dict):
        # Check for text node
        if "text" in node and isinstance(node["text"], str):
            text += node["text"]
        # Check for mention
        if node.get("type") == "mention":
            mention_text = node.get("text", "")
            if mention_text:
                text += mention_text
        # Recurse into children
        for child in node.get("children", []):
            text += extract_lexical_text(child, depth + 1)
        # Add newline for paragraph nodes
        if node.get("type") == "paragraph" and text:
            text += "\n"
    elif isinstance(node, list):
        for item in node:
            text += extract_lexical_text(item, depth + 1)
    return text


def extract_assistant_text(bubble):
    """Extract assistant response text from bubble."""
    text = bubble.get("text", "")
    return text.strip() if text else ""


def extract_tool_calls(bubble):
    """Extract tool call information from bubble."""
    tool_data = bubble.get("toolFormerData", {})
    if not tool_data:
        return None

    tool_name = tool_data.get("name", "unknown")
    raw_args = tool_data.get("rawArgs", "{}")

    # Parse args
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except (json.JSONDecodeError, TypeError):
        args = {"raw": str(raw_args)[:200]}

    # Summarize based on tool type
    summary = tool_name
    if "command" in args:
        cmd = args["command"]
        summary = f"{tool_name}: {cmd[:100]}"
    elif "path" in args:
        summary = f"{tool_name}: {args['path']}"
    elif "query" in args:
        summary = f"{tool_name}: {args['query'][:80]}"
    elif "pattern" in args:
        summary = f"{tool_name}: {args['pattern']}"

    return summary


def extract_code_blocks(bubble):
    """Extract code blocks from bubble."""
    blocks = bubble.get("codeBlocks", [])
    if not blocks:
        return []

    result = []
    for block in blocks:
        content = block.get("content", "")
        lang = block.get("languageId", "")
        if content:
            # Truncate long code blocks
            if len(content) > 500:
                content = content[:500] + "\n... (truncated)"
            result.append({"language": lang, "content": content})
    return result


def reconstruct_conversation(conn, composer_id):
    """Reconstruct full conversation flow for a composer."""
    composer_data = get_composer_data(conn, composer_id)
    if not composer_data:
        return None

    headers = composer_data.get("fullConversationHeadersOnly", [])
    if not headers:
        return None

    turns = []
    current_turn = {"user": [], "assistant": [], "tools": [], "code_blocks": []}

    for header in headers:
        bubble_id = header.get("bubbleId")
        bubble_type = header.get("type")  # 1=user, 2=assistant

        bubble = get_bubble(conn, composer_id, bubble_id)
        if not bubble:
            continue

        if bubble_type == 1:
            # User message - start new turn if previous turn has content
            if current_turn["user"] or current_turn["assistant"]:
                turns.append(current_turn)
                current_turn = {"user": [], "assistant": [], "tools": [], "code_blocks": []}

            text = extract_user_text(bubble)
            if text:
                current_turn["user"].append(text)

        elif bubble_type == 2:
            # Assistant message
            text = extract_assistant_text(bubble)
            if text:
                current_turn["assistant"].append(text)

            # Tool calls
            tool_info = extract_tool_calls(bubble)
            if tool_info:
                current_turn["tools"].append(tool_info)

            # Code blocks
            blocks = extract_code_blocks(bubble)
            current_turn["code_blocks"].extend(blocks)

    # Don't forget the last turn
    if current_turn["user"] or current_turn["assistant"]:
        turns.append(current_turn)

    return turns


def generate_packet(header, turns):
    """Generate Markdown packet from conversation data."""
    composer_id = header.get("composerId", "unknown")
    name = header.get("name", "Untitled")
    created_ms = header.get("createdAt", 0)
    created_dt = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    unified_mode = header.get("unifiedMode", "unknown")
    lines_added = header.get("totalLinesAdded", 0)
    lines_removed = header.get("totalLinesRemoved", 0)
    files_changed = header.get("filesChangedCount", 0)
    is_archived = header.get("isArchived", False)
    status = header.get("status", "unknown")

    lines = []
    lines.append(f"# Cursor Session Packet: {composer_id}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Source: Cursor SQLite")
    lines.append(f"- Composer ID: {composer_id}")
    lines.append(f"- Name: {name}")
    lines.append(f"- Created: {created_dt}")
    lines.append(f"- Mode: {unified_mode}")
    lines.append(f"- Status: {status}")
    lines.append(f"- Lines: +{lines_added}/-{lines_removed}")
    lines.append(f"- Files Changed: {files_changed}")
    lines.append(f"- Archived: {is_archived}")
    lines.append(f"- Turns: {len(turns)}")
    lines.append("")

    for i, turn in enumerate(turns, 1):
        lines.append(f"## Turn {i}")
        lines.append("")

        # User messages
        if turn["user"]:
            lines.append("### User")
            lines.append("")
            for msg in turn["user"]:
                lines.append(f"```text")
                lines.append(msg)
                lines.append("```")
                lines.append("")

        # Tool calls
        if turn["tools"]:
            lines.append("### Tool Calls")
            lines.append("")
            for tool in turn["tools"]:
                lines.append(f"- {tool}")
            lines.append("")

        # Code blocks
        if turn["code_blocks"]:
            lines.append("### Code Blocks")
            lines.append("")
            for block in turn["code_blocks"][:3]:  # Limit to 3 code blocks per turn
                lang = block["language"] or "text"
                lines.append(f"```{lang}")
                lines.append(block["content"])
                lines.append("```")
                lines.append("")

        # Assistant messages
        if turn["assistant"]:
            lines.append("### Assistant")
            lines.append("")
            for msg in turn["assistant"]:
                # Truncate very long messages
                if len(msg) > 2000:
                    msg = msg[:2000] + "\n... (truncated)"
                lines.append(msg)
                lines.append("")

    return "\n".join(lines)


def cmd_list(args):
    """List Cursor conversations."""
    conn = get_db_connection()
    headers = get_composer_headers(conn)
    conn.close()

    filtered = filter_conversations(headers, project=args.project)

    # Load manifest to check processed status
    manifest = load_manifest()
    processed = manifest.get("processed", {})

    print(f"Found {len(filtered)} conversations" + (f" for project '{args.project}'" if args.project else ""))
    print()

    # Summary stats
    statuses = {}
    for h in filtered:
        s = h.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print("Status distribution:")
    for s, count in sorted(statuses.items()):
        print(f"  {s}: {count}")

    archived_count = sum(1 for h in filtered if h.get("isArchived"))
    print(f"\nArchived: {archived_count}")
    print(f"Processed: {sum(1 for h in filtered if h.get('composerId') in processed)}")

    if args.verbose:
        print("\n--- Conversations ---")
        for h in filtered[:50]:
            cid = h.get("composerId", "?")
            name = h.get("name", "Untitled")[:50]
            created_ms = h.get("createdAt", 0)
            date = datetime.fromtimestamp(created_ms / 1000).strftime("%Y-%m-%d")
            status = h.get("status", "?")
            archived = "[A]" if h.get("isArchived") else "   "
            done = "[X]" if cid in processed else "   "
            print(f"  {done} {archived} {date} [{status:10}] {cid[:8]}... {name}")


def cmd_export(args):
    """Export conversations as packets."""
    conn = get_db_connection()
    headers = get_composer_headers(conn)

    filtered = filter_conversations(headers, project=args.project)

    # Load manifest
    manifest = load_manifest()
    processed = manifest.get("processed", {})

    # Normalize processed keys to short IDs (remove cursor- prefix if present)
    # This handles legacy manifest entries that may use either format
    def normalize_id(cid):
        if cid.startswith("cursor-"):
            cid = cid.replace("cursor-", "")
        return cid

    # Build set of short IDs from manifest
    processed_short_ids = {normalize_id(k) for k in processed.keys()}

    # Filter out already processed (compare short prefix of full UUID against stored short IDs)
    def is_processed(header):
        full_id = header.get("composerId", "")
        # Remove cursor- prefix and check if it starts with any known short ID
        normalized = normalize_id(full_id)
        for short_id in processed_short_ids:
            if normalized.startswith(short_id) or short_id in normalized:
                return True
        return False

    unprocessed = [h for h in filtered if not is_processed(h)]

    # Apply limit - but we need to find N that actually have data
    limit = args.next or 10

    print(f"Searching for {limit} conversations with data...")

    os.makedirs(PACKET_OUTPUT_DIR, exist_ok=True)
    exported = 0
    skipped = 0

    for header in unprocessed:
        if exported >= limit:
            break

        composer_id = header.get("composerId")
        name = header.get("name", "Untitled")

        # Reconstruct conversation
        turns = reconstruct_conversation(conn, composer_id)
        if not turns:
            skipped += 1
            continue

        # Generate packet
        packet = generate_packet(header, turns)

        # Write to file
        output_path = os.path.join(PACKET_OUTPUT_DIR, f"cursor-{composer_id}.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(packet)

        exported += 1
        print(f"  Exported: {name[:50]} -> cursor-{composer_id}.md")

    conn.close()
    print(f"\nExported {exported} packets (skipped {skipped} empty) to {PACKET_OUTPUT_DIR}")


def cmd_mark(args):
    """Mark a conversation as processed."""
    manifest = load_manifest()
    composer_id = args.composer_id
    status = args.status or "distilled"

    manifest["processed"][composer_id] = {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    save_manifest(manifest)
    print(f"Marked {composer_id} as {status}")


def main():
    parser = argparse.ArgumentParser(description="Cursor Conversation Distiller")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list command
    list_parser = subparsers.add_parser("list", help="List conversations")
    list_parser.add_argument("--project", default=DEFAULT_PROJECT_FILTER, help="Filter by project name")
    list_parser.add_argument("--verbose", "-v", action="store_true", help="Show details")

    # export command
    export_parser = subparsers.add_parser("export", help="Export conversations as packets")
    export_parser.add_argument("--project", default=DEFAULT_PROJECT_FILTER, help="Filter by project name")
    export_parser.add_argument("--next", type=int, default=10, help="Number of conversations to export")

    # mark command
    mark_parser = subparsers.add_parser("mark", help="Mark conversation as processed")
    mark_parser.add_argument("composer_id", help="Composer ID to mark")
    mark_parser.add_argument("status", nargs="?", default="distilled", help="Status to set")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "mark":
        cmd_mark(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
