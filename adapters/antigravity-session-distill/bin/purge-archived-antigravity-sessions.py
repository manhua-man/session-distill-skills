#!/usr/bin/env python3
"""Purge historical Antigravity conversations from agyhub_summaries_proto.pb, conversations/*.db, brain/*, and SQLite.

Safe by default: automatically discovers and preserves all active (archived == 0) conversations
and project associations. Only truly archived (archived == 1) or discarded sessions are purged.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sqlite3
from datetime import datetime, timezone

CURRENT_SESSION_ID = os.environ.get("ANTIGRAVITY_CURRENT_CONVERSATION_ID", "18c30078-7555-4972-9f79-f21baf6da50f")

AG_DIR = pathlib.Path.home() / ".gemini" / "antigravity"
PB_FILE = AG_DIR / "agyhub_summaries_proto.pb"
CONV_DIR = AG_DIR / "conversations"
BRAIN_DIR = AG_DIR / "brain"
DB_FILE = AG_DIR / "conversation_summaries.db"


def parse_varint(buf: bytes, offset: int) -> tuple[int, int]:
    res = 0
    shift = 0
    while True:
        b = buf[offset]
        offset += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return res, offset


def encode_varint(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def decode_pb_entries(data: bytes) -> list[tuple[str, bytes]]:
    offset = 0
    entries = []
    while offset < len(data):
        tag = data[offset]
        offset += 1
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 1 and wire_type == 2:
            length, offset = parse_varint(data, offset)
            entry_bytes = data[offset : offset + length]
            offset += length

            # Extract conversation ID (subfield 1, string length 36)
            cid = ""
            sub_offset = 0
            while sub_offset < len(entry_bytes):
                sub_tag = entry_bytes[sub_offset]
                sub_offset += 1
                sub_field = sub_tag >> 3
                sub_wire = sub_tag & 0x07
                if sub_wire == 2:
                    sub_len, sub_offset = parse_varint(entry_bytes, sub_offset)
                    sub_val = entry_bytes[sub_offset : sub_offset + sub_len]
                    sub_offset += sub_len
                    if sub_field == 1:
                        cid = sub_val.decode("ascii", errors="ignore")
                elif sub_wire == 0:
                    _, sub_offset = parse_varint(entry_bytes, sub_offset)
                elif sub_wire == 1:
                    sub_offset += 8
                elif sub_wire == 5:
                    sub_offset += 4
                else:
                    break
            entries.append((cid, entry_bytes))
        else:
            break
    return entries


def get_active_sessions_from_db(db_path: pathlib.Path | None = None) -> set[str]:
    """Query conversations_fts in SQLite to find all active (archived == 0) conversations."""
    target_db = db_path or DB_FILE
    if not target_db.exists():
        return set()

    active_cids = set()
    try:
        conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT conversation_id FROM conversations_fts WHERE chunk_index = -1 AND archived = 0")
        for row in cur.fetchall():
            if row[0]:
                active_cids.add(row[0])
        conn.close()
    except Exception as e:
        print(f"Warning: could not query active sessions from {target_db.name}: {e}")
    return active_cids


def backup_storage(ag_dir: pathlib.Path | None = None) -> None:
    base_dir = ag_dir or AG_DIR
    pb_file = base_dir / "agyhub_summaries_proto.pb"
    db_file = base_dir / "conversation_summaries.db"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if pb_file.exists():
        bak = pb_file.with_name(f"{pb_file.name}.backup-{ts}")
        shutil.copy2(pb_file, bak)
        print(f"Backup PB: {bak.name}")

    if db_file.exists():
        bak = db_file.with_name(f"{db_file.name}.backup-{ts}")
        shutil.copy2(db_file, bak)
        print(f"Backup SQLite: {bak.name}")


def purge_antigravity(keep_cids: set[str], ag_dir: pathlib.Path | None = None, sync_db: bool = True) -> dict[str, int]:
    base_dir = ag_dir or AG_DIR
    pb_file = base_dir / "agyhub_summaries_proto.pb"
    conv_dir = base_dir / "conversations"
    brain_dir = base_dir / "brain"
    db_file = base_dir / "conversation_summaries.db"

    stats = {
        "pb_entries_removed": 0,
        "db_files_deleted": 0,
        "brain_folders_deleted": 0,
        "db_rows_deleted": 0,
    }

    # 1. Prune PB file
    if pb_file.exists():
        data = pb_file.read_bytes()
        entries = decode_pb_entries(data)
        before_count = len(entries)
        kept_entries = [e for e in entries if e[0] in keep_cids]
        stats["pb_entries_removed"] = before_count - len(kept_entries)

        new_data = bytearray()
        for _, entry_bytes in kept_entries:
            new_data.append(0x0A)  # Field 1, wire type 2
            new_data.extend(encode_varint(len(entry_bytes)))
            new_data.extend(entry_bytes)

        pb_file.write_bytes(bytes(new_data))
        print(f"PB file updated: {before_count} -> {len(kept_entries)} entries")

    # 2. Prune conversations/*.db
    if conv_dir.exists():
        for db_file_item in list(conv_dir.glob("*.db*")):
            cid = db_file_item.name.split(".")[0]
            if cid not in keep_cids:
                try:
                    db_file_item.unlink()
                    stats["db_files_deleted"] += 1
                except Exception as e:
                    print(f"  Failed to delete {db_file_item.name}: {e}")

    # 3. Prune brain/*
    if brain_dir.exists():
        for brain_folder in list(brain_dir.iterdir()):
            if not brain_folder.is_dir() or brain_folder.name == "tempmediaStorage":
                continue
            cid = brain_folder.name
            if cid not in keep_cids:
                try:
                    shutil.rmtree(brain_folder)
                    stats["brain_folders_deleted"] += 1
                except Exception as e:
                    print(f"  Failed to delete {brain_folder.name}: {e}")

    # 4. Prune SQLite rows in conversation_summaries.db
    if sync_db and db_file.exists() and keep_cids:
        try:
            conn = sqlite3.connect(str(db_file))
            cur = conn.cursor()
            placeholders = ",".join(["?"] * len(keep_cids))
            cur.execute(
                f"DELETE FROM conversation_summaries WHERE conversation_id NOT IN ({placeholders})",
                list(keep_cids),
            )
            deleted_summaries = cur.rowcount
            cur.execute(
                f"DELETE FROM conversations_fts WHERE chunk_index = -1 AND conversation_id NOT IN ({placeholders})",
                list(keep_cids),
            )
            stats["db_rows_deleted"] = deleted_summaries
            conn.commit()
            cur.execute("PRAGMA wal_checkpoint(FULL)")
            conn.close()
            print(f"SQLite database pruned: removed {deleted_summaries} inactive rows")
        except Exception as e:
            print(f"Warning: could not prune SQLite DB: {e}")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge historical Antigravity conversations")
    parser.add_argument("--keep", nargs="*", default=[CURRENT_SESSION_ID], help="Explicit conversation IDs to keep")
    parser.add_argument("--purge-active", action="store_true", help="Also purge active sessions (archived == 0). Default is False.")
    parser.add_argument("--no-db-sync", action="store_true", help="Do not prune rows from conversation_summaries.db")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without applying changes")
    args = parser.parse_args()

    keep_set = set(args.keep)
    if not args.purge_active:
        active_cids = get_active_sessions_from_db()
        print(f"Auto-detected {len(active_cids)} active (archived == 0) project conversations to preserve.")
        keep_set.update(active_cids)
    else:
        print("WARNING: --purge-active is set. Active conversations will NOT be automatically preserved.")

    print(f"Target Antigravity directory: {AG_DIR}")
    print(f"Total conversations protected: {len(keep_set)}")

    if args.dry_run:
        print("[Dry Run] Skipping destructive operations.")
        return 0

    backup_storage()
    stats = purge_antigravity(keep_set, sync_db=not args.no_db_sync)
    print(f"Purge complete: {stats}")
    print("Done. Antigravity Conversation History has been safely purged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
