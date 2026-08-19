#!/usr/bin/env python3
"""Purge historical Antigravity conversations from agyhub_summaries_proto.pb, conversations/*.db, and brain/*."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
from datetime import datetime, timezone

CURRENT_SESSION_ID = os.environ.get("ANTIGRAVITY_CURRENT_CONVERSATION_ID", "18c30078-7555-4972-9f79-f21baf6da50f")

AG_DIR = pathlib.Path.home() / ".gemini" / "antigravity"
PB_FILE = AG_DIR / "agyhub_summaries_proto.pb"
CONV_DIR = AG_DIR / "conversations"
BRAIN_DIR = AG_DIR / "brain"


def parse_varint(buf: bytes, offset: int) -> tuple[int, int]:
    res = 0
    shift = 0
    while True:
        b = buf[offset]
        offset += 1
        res |= (b & 0x7f) << shift
        if not (b & 0x80):
            break
        shift += 7
    return res, offset


def encode_varint(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7f
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


def backup_storage() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if PB_FILE.exists():
        bak = PB_FILE.with_name(f"{PB_FILE.name}.backup-{ts}")
        shutil.copy2(PB_FILE, bak)
        print(f"backup pb: {bak.name}")


def purge_antigravity(keep_cids: set[str]) -> dict[str, int]:
    stats = {"pb_entries_removed": 0, "db_files_deleted": 0, "brain_folders_deleted": 0}
    
    # 1. Prune PB file
    if PB_FILE.exists():
        data = PB_FILE.read_bytes()
        entries = decode_pb_entries(data)
        before_count = len(entries)
        kept_entries = [e for e in entries if e[0] in keep_cids]
        stats["pb_entries_removed"] = before_count - len(kept_entries)
        
        # Re-encode PB
        new_data = bytearray()
        for _, entry_bytes in kept_entries:
            new_data.append(0x0a)  # Field 1, wire type 2
            new_data.extend(encode_varint(len(entry_bytes)))
            new_data.extend(entry_bytes)
            
        PB_FILE.write_bytes(bytes(new_data))
        print(f"pb file updated: {before_count} -> {len(kept_entries)} entries")

    # 2. Prune conversations/*.db
    if CONV_DIR.exists():
        for db_file in list(CONV_DIR.glob("*.db*")):
            cid = db_file.name.split(".")[0]
            if cid not in keep_cids:
                try:
                    db_file.unlink()
                    stats["db_files_deleted"] += 1
                except Exception as e:
                    print(f"  Failed to delete {db_file.name}: {e}")

    # 3. Prune brain/*
    if BRAIN_DIR.exists():
        for brain_folder in list(BRAIN_DIR.iterdir()):
            if not brain_folder.is_dir() or brain_folder.name == "tempmediaStorage":
                continue
            cid = brain_folder.name
            if cid not in keep_cids:
                try:
                    shutil.rmtree(brain_folder)
                    stats["brain_folders_deleted"] += 1
                except Exception as e:
                    print(f"  Failed to delete {brain_folder.name}: {e}")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge historical Antigravity conversations")
    parser.add_argument("--keep", nargs="*", default=[CURRENT_SESSION_ID], help="Conversation IDs to keep")
    parser.add_argument("--force", action="store_true", help="Execute without confirmation")
    args = parser.parse_args()

    keep_set = set(args.keep)
    print(f"Target Antigravity directory: {AG_DIR}")
    print(f"Keeping active conversation(s): {keep_set}")

    backup_storage()
    stats = purge_antigravity(keep_set)
    print(f"Purge complete: {stats}")
    print("Done. Antigravity Conversation History has been cleanly purged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
