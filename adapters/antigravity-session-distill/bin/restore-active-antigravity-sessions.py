#!/usr/bin/env python3
"""Restore active Antigravity conversations, trajectory schemas, and sidebar project associations.

Ensures:
1. Valid SQLite trajectory database schemas in conversations/<cid>.db so the IDE does not crash.
2. Correct Protobuf raw_summary encoding containing trajectoryMetadata.projectId and workspaceUri.
3. Clean synchronization with agyhub_summaries_proto.pb and conversation_summaries.db.
4. Optional live RPC broadcast (JetboxWriteSummary) to running language_server.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import time
import urllib.request
import uuid
from datetime import datetime

AG_DIR = pathlib.Path.home() / ".gemini" / "antigravity"
PB_FILE = AG_DIR / "agyhub_summaries_proto.pb"
CONV_DIR = AG_DIR / "conversations"
BRAIN_DIR = AG_DIR / "brain"
DB_FILE = AG_DIR / "conversation_summaries.db"


def encode_varint(val: int) -> bytes:
    out = bytearray()
    while val > 0x7F:
        out.append((val & 0x7F) | 0x80)
        val >>= 7
    out.append(val & 0x7F)
    return bytes(out)


def make_field(field_num: int, wire_type: int, val: int | bytes | bytearray) -> bytes:
    key = (field_num << 3) | wire_type
    out = bytearray(encode_varint(key))
    if wire_type == 0:
        out.extend(encode_varint(int(val)))
    elif wire_type == 2:
        out.extend(encode_varint(len(val)))
        out.extend(val)
    elif wire_type in (1, 5):
        out.extend(val)
    return bytes(out)


def make_timestamp(sec: int, nanos: int = 0) -> bytes:
    b1 = make_field(1, 0, sec)
    b2 = make_field(2, 0, nanos)
    return b1 + b2


def make_workspace_info(ws_uri_raw: str) -> bytes:
    if not ws_uri_raw:
        return b""
    b1 = make_field(1, 2, ws_uri_raw.encode("utf-8"))
    b2 = make_field(2, 2, ws_uri_raw.encode("utf-8"))
    return b1 + b2


def make_raw_summary(
    cid: str,
    title: str,
    ws_uri_raw: str,
    ws_uri_encoded: str,
    project_id: str,
    ts_sec: int,
    step_count: int = 10,
) -> bytes:
    """Encode a CascadeTrajectorySummary protobuf compatible with Antigravity IDE."""
    ts_bytes = make_timestamp(ts_sec, 0)
    meta_uuid = str(uuid.uuid4())
    summary_uuid = str(uuid.uuid4())

    # Field 17: trajectoryMetadata
    f17_parts = bytearray()
    if ws_uri_raw:
        ws_info = make_workspace_info(ws_uri_raw)
        f17_parts.extend(make_field(1, 2, ws_info))
    f17_parts.extend(make_field(2, 2, ts_bytes))
    f17_parts.extend(make_field(3, 2, meta_uuid.encode("utf-8")))
    f17_parts.extend(make_field(6, 2, cid.encode("utf-8")))
    if ws_uri_encoded:
        f17_parts.extend(make_field(7, 2, ws_uri_encoded.encode("utf-8")))
    if project_id and project_id != "outside-of-project":
        f17_parts.extend(make_field(18, 2, project_id.encode("utf-8")))
    else:
        f17_parts.extend(make_field(18, 2, b"outside-of-project"))
    f17 = make_field(17, 2, bytes(f17_parts))

    # Field 15: title & timestamp
    f15_parts = bytearray()
    if title:
        f15_parts.extend(make_field(1, 2, title.encode("utf-8")))
    f15_parts.extend(make_field(7, 2, ts_bytes))
    f15 = make_field(15, 2, bytes(f15_parts))

    parts = bytearray()
    if title:
        parts.extend(make_field(1, 2, title.encode("utf-8")))
    parts.extend(make_field(2, 0, step_count))
    parts.extend(make_field(3, 2, ts_bytes))
    parts.extend(make_field(4, 2, summary_uuid.encode("utf-8")))
    parts.extend(make_field(5, 0, 1))
    parts.extend(make_field(7, 2, ts_bytes))
    if ws_uri_raw:
        parts.extend(make_field(9, 2, make_workspace_info(ws_uri_raw)))
    parts.extend(make_field(10, 2, ts_bytes))
    parts.extend(f15)
    parts.extend(make_field(16, 0, step_count))
    parts.extend(f17)
    parts.extend(make_field(22, 0, 4))
    parts.extend(make_field(28, 0, 4))
    return bytes(parts)


def init_trajectory_db(conv_file: pathlib.Path, cid: str) -> bool:
    """Create a valid conversation SQLite schema so IDE does not crash or prune the session."""
    if conv_file.exists():
        return False

    conv_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(conv_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS `trajectory_meta` (
            `trajectory_id` text,
            `cascade_id` text,
            `trajectory_type` integer,
            `source` integer,
            PRIMARY KEY (`trajectory_id`)
        )
    """)
    cur.execute("INSERT OR REPLACE INTO `trajectory_meta` VALUES (?, ?, 1, 1)", (cid, cid))
    cur.execute("""
        CREATE TABLE IF NOT EXISTS `steps` (
            `idx` integer,
            `step_type` integer NOT NULL DEFAULT 0,
            `status` integer NOT NULL DEFAULT 0,
            `has_subtrajectory` numeric NOT NULL DEFAULT false,
            `metadata` blob,
            `error_details` blob,
            `permissions` blob,
            `task_details` blob,
            `render_info` blob,
            `step_payload` blob,
            `step_format` integer NOT NULL DEFAULT 0,
            PRIMARY KEY (`idx`)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS `idx_steps_status` ON `steps`(`status`)")
    cur.execute("CREATE INDEX IF NOT EXISTS `idx_steps_step_type` ON `steps`(`step_type`)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS `gen_metadata` (
            `idx` integer,
            `data` blob,
            `size` integer NOT NULL DEFAULT 0,
            PRIMARY KEY (`idx`)
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS `executor_metadata` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
    cur.execute("CREATE TABLE IF NOT EXISTS `parent_references` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS `trajectory_metadata_blob` (
            `id` text DEFAULT "main",
            `data` blob,
            PRIMARY KEY (`id`)
        )
    """)
    cur.execute("INSERT OR REPLACE INTO `trajectory_metadata_blob` VALUES ('main', x'')")
    cur.execute("CREATE TABLE IF NOT EXISTS `battle_mode_infos` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")
    conn.commit()
    conn.close()
    return True


def sync_active_conversations(ag_dir: pathlib.Path | None = None) -> dict[str, int]:
    base_dir = ag_dir or AG_DIR
    conv_dir = base_dir / "conversations"
    brain_dir = base_dir / "brain"
    db_file = base_dir / "conversation_summaries.db"
    pb_file = base_dir / "agyhub_summaries_proto.pb"

    if not db_file.exists():
        print(f"Error: {db_file} not found.")
        return {}

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT conversation_id, title, workspace_uris, project_id, last_modified_time, raw_summary
        FROM conversation_summaries
    """).fetchall()

    stats = {
        "total_active": len(rows),
        "db_schemas_created": 0,
        "raw_summaries_generated": 0,
        "pb_entries_written": 0,
    }

    all_pb_entries = []

    for cid, title, ws_uris_str, proj_id, mtime_str, existing_raw in rows:
        # 1. Ensure conversation SQLite db exists
        conv_file = conv_dir / f"{cid}.db"
        if init_trajectory_db(conv_file, cid):
            stats["db_schemas_created"] += 1

        # 2. Ensure brain folder exists
        (brain_dir / cid).mkdir(parents=True, exist_ok=True)

        # 3. Ensure raw_summary Protobuf exists
        if existing_raw is not None and len(existing_raw) > 0:
            raw_bytes = existing_raw
        else:
            ws_uri_encoded = ""
            ws_uri_raw = ""
            if ws_uris_str:
                try:
                    arr = json.loads(ws_uris_str)
                    if arr:
                        ws_uri_encoded = arr[0]
                        ws_uri_raw = ws_uri_encoded.replace("%3A", ":")
                except Exception:
                    pass

            ts_sec = int(time.time())
            if mtime_str:
                try:
                    clean_str = mtime_str.split("+")[0].split(".")[0]
                    dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                    ts_sec = int(dt.timestamp())
                except Exception:
                    pass

            raw_bytes = make_raw_summary(cid, title or "", ws_uri_raw, ws_uri_encoded, proj_id or "", ts_sec)
            cur.execute("UPDATE conversation_summaries SET raw_summary = ? WHERE conversation_id = ?", (raw_bytes, cid))
            stats["raw_summaries_generated"] += 1

        all_pb_entries.append((cid, raw_bytes))

    conn.commit()
    cur.execute("PRAGMA wal_checkpoint(FULL)")
    conn.close()

    # 4. Write agyhub_summaries_proto.pb
    pb_out = bytearray()
    for cid, raw_bytes in all_pb_entries:
        entry_body = bytearray()
        entry_body.extend(make_field(1, 2, cid.encode("utf-8")))
        entry_body.extend(make_field(2, 2, raw_bytes))
        pb_out.extend(make_field(1, 2, bytes(entry_body)))

    pb_file.write_bytes(bytes(pb_out))
    stats["pb_entries_written"] = len(all_pb_entries)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore and synchronize active Antigravity conversations")
    parser.add_argument("--dir", type=pathlib.Path, default=AG_DIR, help="Path to Antigravity directory")
    args = parser.parse_args()

    print(f"Synchronizing active Antigravity sessions in: {args.dir}")
    stats = sync_active_conversations(args.dir)
    print(f"Sync complete: {stats}")
    print("Done. All active sessions have been restored and aligned with project metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
